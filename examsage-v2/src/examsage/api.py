"""Local evidence and subscription chat API. Not a public multi-tenant deployment."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from pathlib import Path
from io import StringIO
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit
import json

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .cli import load
from .domain import PaperSelection, Scope, digest, record_source_id
from .exam_outlook import evaluate_outlook
from .search import CourseQueryService, source_page_course, supports_paper_selection
from .ingest import render_pdf_page
from .import_receipt import checked_child
from .release import inside
from .slides import validated_slide_asset
from .source_paths import source_path
from .storage import Store
from .supplements import validated_supplement_asset
from .web_intake import STUDENT_HOME_LINK


CitationId = Annotated[str | None,Query(pattern=r'^src_[0-9a-f]{64}$')]
CitationPage = Annotated[int | None,Query(ge=1)]


def create_app(data: Path, course_catalog: list | Callable[[], list] | None=None, *, chat_runner=None,
               course_id=None, private_preview_root: Path | None=None, is_authorized=None,
               student_navigation=False, open_learning=None) -> FastAPI:
    data=Path(data).resolve()
    if private_preview_root is None:
        store,scope=load(data)
        previews=data/'previews'
    else:
        scope=Scope.model_validate_json((data/'current.json').read_bytes())
        store=Store(data/'course.sqlite3',read_only=True)
        previews=private_preview_root
    service=CourseQueryService(store,course_id=course_id)
    app=FastAPI(title='ExamSage v2 Course Evidence',version='2.0.0a1')
    app.mount('/static',StaticFiles(directory=Path(__file__).parent/'web'),name='static')
    from .chat_api import install_chat
    current_scope=install_chat(app, data, store, scope, runner=chat_runner, course_id=course_id,
                               is_authorized=is_authorized)
    if private_preview_root is not None:
        app.router.dependencies.append(Depends(current_scope))

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        host=urlsplit('http://'+request.headers.get('host','')).hostname
        if host not in {'127.0.0.1','localhost','::1'}:
            return JSONResponse({'detail':'Local host required'},status_code=403)
        origin=request.headers.get('origin')
        base=urlsplit(str(request.base_url))
        if origin and origin!=f'{base.scheme}://{base.netloc}':
            return JSONResponse({'detail':'Same origin required'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'"
        return response

    def document(doc_id):
        manifest=store.manifest(scope)
        if manifest is None or doc_id not in store.permitted_documents(scope):
            raise HTTPException(404,'Source not available')
        return next(d for d in manifest.documents if d.id==doc_id)

    def source(doc_id):
        doc=document(doc_id)
        if not doc.asset:
            raise HTTPException(404,'Source asset unavailable')
        try:path=inside(data/'assets',doc.asset)
        except ValueError:raise HTTPException(404,'Invalid source asset') from None
        if not path.is_file():raise HTTPException(404,'Source asset missing')
        return doc,path

    def cited_page(doc_id,number,expected=None):
        from .page_image import is_original_page
        record = store.get(scope,f'{doc_id}:p{number}')
        if not is_original_page(record,doc_id,number):
            raise HTTPException(404,'原页不可用。')
        sid = record_source_id(course_id or scope.course,scope,digest(record.model_dump(mode='json')))
        if expected is not None and expected!=sid:
            raise HTTPException(409,'原页引用已变化，请重新回测后打开。')
        return record,sid

    if open_learning is not None:
        from .learning_web import install_learning
        install_learning(app, course_id, current_scope, cited_page, store, open_learning)

    @app.get('/',response_class=HTMLResponse)
    def home():
        html = (Path(__file__).parent/'web/index.html').read_text(encoding='utf-8')
        if open_learning is not None:
            html = html.replace('<!-- student-progress-script -->','<script defer src="/static/learning.js"></script>')
            html = html.replace('<!-- student-progress -->','<button type="button" class="navbtn" id="learningNav">我的复习</button>')
        return html.replace('<!-- student-home -->', STUDENT_HOME_LINK if student_navigation else '')

    def scoped_record(record):
        if record.kind=='question' and 'has_answer' in record.details:
            bundle=service.get_question(scope,record.id)
            return bundle.records[0] if bundle.records else None
        return service.with_question_topics(scope,[record])[0]

    @app.get('/api/status')
    def status():
        manifest=store.manifest(scope)
        allowed=store.permitted_documents(scope)
        docs=[d for d in manifest.documents if d.id in allowed]
        records=store.list_records(scope)
        topics=(store.metadata(scope) or {}).get('topics')
        if topics is None:
            topics=json.loads((data/'topics.json').read_text(encoding='utf-8')) if (data/'topics.json').exists() else []
        source_mode=source_page_course(store.metadata(scope) or {})
        reviewed=sum(r.details.get('visual_status')=='agent_reviewed' for r in records if r.kind=='block')
        supplements=sum(bool(r.details.get('supplement')) for r in records if r.kind=='block')
        recoveries=Counter(r.details['supplement']['recovery_status'] for r in records if r.kind=='block' and (r.details.get('supplement') or {}).get('recovery_status'))
        questions=[r for r in records if r.kind=='question'];parents={r.parent_id for r in questions}
        checks=[c for r in questions for c in r.details.get('audit',{}).get('numerical_checks',[])]
        leaf_checks=[c for r in questions if r.parent_id and r.id not in parents for c in r.details.get('audit',{}).get('numerical_checks',[])]
        return {'course':manifest.course_name,'course_key':manifest.course_key,'snapshot':scope.snapshot,'documents':len(docs),'pages':sum(d.pages for d in docs),
                'counts':dict(Counter(r.kind for r in records)),'topics':topics,'status':'candidate',
                'structure_mode':'source_pages' if source_mode else 'curated','supplement_pages':supplements,
                'recovery_pages':sum(recoveries.values()),'recovery_states':dict(recoveries),
                'whole_questions':sum(not r.parent_id for r in questions),'subquestions':sum(bool(r.parent_id) for r in questions),
                'leaf_subquestions':sum(bool(r.parent_id) and r.id not in parents for r in questions),
                'numerical_checks':len(checks),'numerical_comparisons':dict(Counter(c['comparison'] for c in checks)),
                'leaf_numerical_checks':len(leaf_checks),'leaf_numerical_comparisons':dict(Counter(c['comparison'] for c in leaf_checks)),
                'pilot_records':sum(bool(r.details.get('pilot_record')) for r in records),
                'pilot_answer_pairs':sum(any(e.kind=='has_answer' and e.source==r.id for e in store.related(scope,r.id)) for r in records if r.kind=='question'),
                'suggested_queries':list((store.metadata(scope) or {}).get('query_aliases',{}))[:4],
                'paper_selection_available':supports_paper_selection(store.metadata(scope) or {}),
                'exam_years':sorted({d.exam_year for d in docs if d.exam_year}),
                'notice':('本课程已支持原页浏览与关键词检索；知识结构和逐题对应尚未验收。' if source_mode else f'已对照 {reviewed} 页完成代理视觉核查；其余页面和独立专家验收仍待完成。')+(f'已补充 {supplements} 个低文本页的分类与导读，OCR 仍需对照原页。' if supplements else '')+'当前不提供已验证的考试预测。'}

    @app.get('/api/courses')
    def courses():
        if callable(course_catalog):
            return course_catalog()
        return course_catalog or [{'slug':data.name,'name':store.manifest(scope).course_name,'url':'/'}]

    @app.get('/api/documents')
    def documents():
        m=store.manifest(scope)
        allowed=store.permitted_documents(scope)
        first = store.first_visible_pages(scope)
        received = (store.metadata(scope) or {}).get('received_on_utc')
        return [{**d.model_dump(mode='json'),'first_visible_page':first.get(d.id),'availability':d.availability(received)}
                for d in m.documents if d.id in allowed]

    @app.get('/api/exam-outlook/review')
    def review_exam(target_year: Annotated[int,Query(ge=1900,le=2200)],
                    top_k: Annotated[int,Query(ge=1,le=10)],
                    history_mode: Literal['paper_year','strict'],
                    offset: Annotated[int,Query(ge=0,le=10000000)] = 0,
                    review_scope: Annotated[str | None,Query(pattern=r'^[0-9a-f]{64}$')] = None):
        grant = current_scope()
        slug = course_id or grant.course
        key = digest([slug,grant.model_dump(mode='json'),target_year,top_k,history_mode])
        if review_scope is not None and review_scope!=key:
            raise HTTPException(409,'课程资料、访问范围或回测条件已变化，请重新回测。')
        report = evaluate_outlook(store,grant,slug,target_year,top_k,history_mode,offset=offset,question_limit=20)
        current_scope()
        return {**report,'review_scope':key}

    @app.get('/api/search')
    def search(q: str=Query(min_length=1,max_length=4000), *,
               paper_id: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
               solution_id: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
               exam_year: Annotated[int | None, Query(ge=1900, le=2199)] = None):
        selection = None
        if any(value is not None for value in (paper_id, solution_id, exam_year)):
            if not paper_id or exam_year is None:
                raise HTTPException(422, '请选择试卷并填写考年。')
            selection = PaperSelection(paper_id=paper_id, solution_id=solution_id, exam_year=exam_year)
        return service.search_evidence(scope, q, selection=selection)

    @app.get('/api/records')
    def records(kind: str=Query(pattern='^(concept|formula|example|question)$'),topic: str | None=None,parent: str | None=None,roots: bool=False):
        found = [scoped_record(r) for r in store.list_records(scope,kind)
                 if (parent is None or r.parent_id==parent) and (not roots or r.parent_id is None)]
        return [r for r in found if r is not None and (topic is None or r.topic==topic or
                any(e['topic']==topic for e in r.details.get('exam_topic_evidence', [])))]

    @app.get('/api/record/{record_id:path}')
    def record(record_id: str):
        found=store.get(scope,record_id)
        if found is None:raise HTTPException(404,'Record not available')
        scoped=scoped_record(found)
        if scoped is None:raise HTTPException(404,'Shared record context not available')
        return {'record':scoped,'relations':store.related(scope,record_id),
                'children_count':sum(r.parent_id==record_id and scoped_record(r) is not None for r in store.list_records(scope,found.kind))}

    @app.get('/api/related/{concept_id:path}')
    def related(concept_id: str):
        return service.get_related_questions(scope,concept_id)

    @app.get('/api/answer/{question_id:path}')
    def answer(question_id: str):
        return service.get_answer(scope,question_id)

    @app.get('/api/question/{question_id:path}')
    def question(question_id: str):
        return service.get_question(scope,question_id)

    @app.get('/api/page/{doc_id}/{number}')
    def page(doc_id: str,number: int,source_id: CitationId = None, source_page: CitationPage = None):
        if source_page is not None and source_id is None:
            raise HTTPException(422,'请提供原页引用。')
        if source_id is not None:
            current_scope()
        doc=document(doc_id)
        bundle=service.get_source_page(scope,doc_id,number)
        if not bundle.records:raise HTTPException(404,'Page not available')
        sid = None
        if source_id is not None:
            if source_page is not None and source_page!=number:
                cited_page(doc_id,source_page,source_id)
                _,sid = cited_page(doc_id,number)
            else:
                _,sid = cited_page(doc_id,number,source_id)
        details=bundle.records[0].details
        is_pdf=doc.relative_path.lower().endswith('.pdf')
        full_slide=validated_slide_asset(doc,details,data/'assets')
        render_asset=(details.get('render') or {}).get('asset')
        if source_id is not None:
            current_scope()
        preview_url = f'/api/preview/{doc_id}/{number}'+(f'?source_id={sid}' if sid else '')
        from .study_file import page_erratum
        review_hash = None if scope.strict_history else (store.metadata(scope) or {}).get('page_erratum_digest')
        return {'document':doc,'bundle':bundle,'source_id':sid,
                'learning_source_id':cited_page(doc_id,number)[1] if open_learning is not None else None,
                'page_erratum':page_erratum(bundle.records[0],doc,review_hash),
                'preview_url':preview_url if is_pdf or full_slide else None,
                'preview_kind':'pdf' if is_pdf else 'pptx_full_slide' if full_slide else None,
                'media_urls':[] if sid else [f'/api/media/{doc_id}/{number}/{i}' for i,asset in enumerate(details.get('assets',[])) if asset!=render_asset]}

    @app.get('/api/source/{doc_id}')
    def source_file(doc_id: str,page: CitationPage = None,source_id: CitationId = None):
        if source_id is not None or page is not None:
            if source_id is None or page is None:
                raise HTTPException(422,'请提供对应的页码和来源编号。')
            from .page_image import verified_source_bytes
            current_scope()
            doc = document(doc_id)
            cited_page(doc_id,page,source_id)
            try:
                original = verified_source_bytes(store.path,doc)
            except (OSError,ValueError) as exc:
                raise HTTPException(409,'原文件未能通过校验，请核对课程版本。') from exc
            current_scope()
            return Response(original,media_type='application/octet-stream',headers={
                'Content-Disposition':"attachment; filename*=UTF-8''"+quote(Path(doc.relative_path).name,safe=''),
                'X-ExamSage-Source-ID':source_id})
        doc,path=source(doc_id)
        return FileResponse(path,filename=Path(doc.relative_path).name)

    @app.get('/api/study-file/{doc_id}')
    def study_file(doc_id: str):
        from .study_file import write_study_text
        current_scope()
        doc = document(doc_id)
        text = StringIO()
        try:
            write_study_text(text,store,scope,course_id or scope.course,[doc.id])
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from None
        current_scope()
        filename = quote(Path(doc.relative_path).stem+'-学习资料.txt',safe='')
        return Response(text.getvalue(),media_type='text/plain; charset=utf-8',
                        headers={'Content-Disposition':"attachment; filename*=UTF-8''"+filename})

    def verified_image(doc_id,number,expected,*,attachment):
        from .page_image import source_image
        current_scope()
        doc = document(doc_id)
        if not 1 <= number <= doc.pages:
            raise HTTPException(404,'Original page unavailable')
        record,sid = cited_page(doc_id,number,expected)
        metadata, png = source_image(store.path,doc,record,number,download=True)
        if png is None:
            if metadata.get('reason') == 'png_size_limit':
                raise HTTPException(413,'本页图片超过 16 MiB 下载上限，可返回课件查看原页或下载原文件。')
            raise HTTPException(404,'Verified full-page image unavailable')
        current_scope()
        filename = quote(f'{Path(doc.relative_path).stem}-p{number}-{sid[:16]}.png',safe='')
        return Response(png,media_type='image/png',headers={
            'Content-Disposition': ("attachment" if attachment else "inline")+"; filename*=UTF-8''"+filename,
            'X-ExamSage-Source-ID': sid})

    @app.get('/api/study-image/{doc_id}/{number}')
    def study_image(doc_id: str,number: int,source_id: CitationId = None):
        return verified_image(doc_id,number,source_id,attachment=True)

    @app.get('/api/preview/{doc_id}/{number}')
    def preview(doc_id: str,number: int,source_id: CitationId = None):
        if source_id is not None:
            return verified_image(doc_id,number,source_id,attachment=False)
        doc,path=source(doc_id)
        if not 1<=number<=doc.pages:
            raise HTTPException(404,'Preview unavailable')
        bundle=service.get_source_page(scope,doc_id,number)
        if not bundle.records:
            raise HTTPException(404,'Page unavailable')
        if path.suffix.lower()=='.pptx':
            slide=validated_slide_asset(doc,bundle.records[0].details,data/'assets')
            if slide is None:raise HTTPException(404,'Full slide render unavailable')
            return FileResponse(slide,media_type='image/png')
        if path.suffix.lower()!='.pdf':raise HTTPException(404,'Preview unavailable')
        try:
            dest=checked_child(source_path(previews.parent),Path(previews.name)/doc.sha256/f'{number}.png')
        except (OSError, ValueError):
            raise HTTPException(404,'Preview unavailable') from None
        render_pdf_page(path,number,dest)
        return FileResponse(dest,media_type='image/png')

    @app.get('/api/media/{doc_id}/{number}/{index}')
    def media(doc_id: str,number: int,index: int):
        doc=document(doc_id)
        bundle=service.get_source_page(scope,doc_id,number)
        if not bundle.records:raise HTTPException(404,'Page unavailable')
        items=bundle.records[0].details.get('assets',[])
        if not 0<=index<len(items):raise HTTPException(404,'Media unavailable')
        if items[index]==(bundle.records[0].details.get('render') or {}).get('asset'):
            path=validated_slide_asset(doc,bundle.records[0].details,data/'assets')
            if path is None:raise HTTPException(404,'Full slide render unavailable')
            return FileResponse(path,media_type='image/png')
        if items[index]==(bundle.records[0].details.get('supplement') or {}).get('image_asset'):
            path=validated_supplement_asset(doc,bundle.records[0].details,data/'assets')
            if path is None:raise HTTPException(404,'Supplement image unavailable')
            return FileResponse(path,media_type='image/png')
        try:path=inside(data/'assets',items[index])
        except ValueError:raise HTTPException(404,'Invalid asset path') from None
        if not path.is_file() or path.suffix.lower() not in {'.png','.jpg','.jpeg','.gif','.webp'}:
            raise HTTPException(404,'Native media format cannot be previewed; open original source')
        return FileResponse(path)

    return app
