from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import json
import os

from .domain import Scope, digest
from .storage import Store
from .search import CourseQueryService
from .ingest import atomic_json, ingest, PARSER_VERSION


def load(data: Path):
    scope=Scope.model_validate_json((data/'current.json').read_text(encoding='utf-8'))
    return Store(data/'course.sqlite3'),scope


def service_for(data: Path, store: Store) -> CourseQueryService:
    settings=data/'embedding-route.json'
    if settings.exists() and os.environ.get('EXAMSAGE_EMBEDDING_KEY'):
        from .embeddings import EmbeddingClient,VectorIndex
        config=json.loads(settings.read_text(encoding='utf-8'))
        client=EmbeddingClient(config['base_url'],os.environ['EXAMSAGE_EMBEDDING_KEY'],config['model'])
        index=VectorIndex(data/'vectors.sqlite3',client.route)
        return CourseQueryService(store,index,lambda q:client.embed([q])[0])
    return CourseQueryService(store)


def build(source: Path, audit: Path, recipe_path: Path, data: Path) -> dict:
    from .manifest import build_manifest
    from .curriculum import build_catalog,map_questions
    from .transcriptions import parse_reviewed_exam
    manifest=build_manifest(source,audit)
    extracted=ingest(source,manifest,data)
    recipe=json.loads(recipe_path.read_text(encoding='utf-8'))
    transcription_path=recipe_path.with_name('grt_transcriptions.json')
    transcriptions=json.loads(transcription_path.read_text(encoding='utf-8')) if transcription_path.exists() else {}
    visual_path=recipe_path.with_name('grt_visual_review.json')
    visual_recipe=json.loads(visual_path.read_text(encoding='utf-8')) if visual_path.exists() else {}
    from .visual_review import apply_visual_review
    from .ingest import page_records
    reviewed_pages=[]
    derivations=[]
    for doc in manifest.documents:
        updated,derived=apply_visual_review(doc,[p for p in extracted['pages'] if p.document_id==doc.id],visual_recipe,manifest.course_key)
        reviewed_pages.extend(updated)
        derivations.extend(derived)
    extracted['pages']=reviewed_pages
    extracted['records']=[r for doc in manifest.documents for r in page_records([p for p in reviewed_pages if p.document_id==doc.id],doc)]
    catalog,relations=build_catalog(manifest,extracted['pages'],recipe)
    questions=[]
    for doc in manifest.documents:
        if doc.kind=='exam':
            found=parse_reviewed_exam(doc,extracted['pages'],manifest.course_key,transcriptions)
            parents=[q for q in found if q.parent_id is None]
            if len(parents)!=6 or sum(q.details['marks'] or 0 for q in parents)!=100:
                raise ValueError(f'Exam structure/marks validation failed for {doc.relative_path}')
            questions.extend(found)
    relations+=map_questions(questions,catalog,recipe)
    records=extracted['records']+catalog+questions+derivations
    metadata={'schema':'v1','recipe':recipe['version'],'recipe_hash':digest(recipe),'parser':PARSER_VERSION,
              'transcription_hash':digest(transcriptions),'visual_review_hash':digest(visual_recipe),
              'review':'candidate','model':'no-generation-model-used','topics':recipe['topics']}
    if 'groundwater_age_review_hash' in recipe:
        from .source_corrections import apply_review_to_records
        correction_path = recipe_path.with_name('grt_source_correction_20261116.json')
        correction = json.loads(correction_path.read_text(encoding='utf-8'))
        if digest(correction) != recipe['groundwater_age_review_hash']:
            raise ValueError('Groundwater age review changed; verify the evidence before adopting it')
        apply_review_to_records(manifest, records, correction, rebuilt_hashes=recipe.get('groundwater_age_rebuilt_hashes'))
        metadata.update(source_correction_hash=digest(correction), page_erratum_digest=digest(correction['adjudication']))
    from .paper_topics import structured_topic_metadata
    metadata.update(structured_topic_metadata(manifest,records,data/'course.sqlite3'))
    store=Store(data/'course.sqlite3')
    sid=store.publish('local',manifest,records,relations,metadata)
    scope=Scope(workspace='local',course=manifest.course_key,snapshot=sid,allowed_sources=[d.id for d in manifest.documents])
    atomic_json(data/'pages.json',[p.model_dump() for p in extracted['pages']])
    atomic_json(data/'topics.json',recipe['topics'])
    atomic_json(data/'current.json',scope.model_dump(mode='json'))
    report={'snapshot':sid,'documents':len(manifest.documents),'pages':len(extracted['pages']),
            'records':dict(Counter(r.kind for r in records)),'relations':len(relations),
            'newly_parsed_documents':extracted['processed'],'cached_documents':extracted['cached'],
            'visual_review_pending':sum(p.visual_status=='not_reviewed' for p in extracted['pages']),
            'full_slide_renders':sum(bool(p.render) for p in extracted['pages']),
            'agent_reviewed_pages':sum(p.visual_status=='agent_reviewed' for p in extracted['pages']),
            'failed_pages':sum(p.status=='failed' for p in extracted['pages']),
            'human_acceptance':'pending','source_validation':'all hashes match audited source inventory'}
    atomic_json(data/'build_report.json',report)
    return report


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(prog='examsage',description='ExamSage v2 evidence-first course data')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('build');p.add_argument('--source',type=Path,required=True);p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--recipe',type=Path,required=True);p.add_argument('--data',type=Path,default=Path('data/grt'))
    p=sub.add_parser('build-library');p.add_argument('--source',type=Path,required=True);p.add_argument('--audit',type=Path,required=True)
    p.add_argument('--config',type=Path,default=Path('courses/library.json'));p.add_argument('--data',type=Path,default=Path('data'))
    p=sub.add_parser('serve-student',help='Open a personal loopback web app for the current OS account')
    p.add_argument('--library',type=Path,default=Path('data'))
    p.add_argument('--workspace-root',type=Path,default=Path('data/student-workspaces'))
    p.add_argument('--port',type=int,default=8769)
    selection=p.add_mutually_exclusive_group()
    selection.add_argument('--course',action='append',help='Grant a registered public course; repeat to choose several')
    selection.add_argument('--private-only',action='store_true',help='Show only courses imported by this student')
    p=sub.add_parser('serve-mcp-local',help='Serve read-only course tools to a loopback HTTP MCP client')
    p.add_argument('--library',type=Path,default=Path('data'))
    p.add_argument('--workspace-root',type=Path,default=Path('data/student-workspaces'))
    p.add_argument('--course',action='append',default=[],help='Include a registered public course; repeat as needed')
    p.add_argument('--port',type=int,default=8770)
    p=sub.add_parser('import-courses',help='Import explicit course packs into a new local library')
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--pack',action='append',required=True,help='Pack path relative to source root; repeat for each course')
    p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('draft-course',help='Create a portable course-pack draft from selected raw files')
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--file',action='append',required=True,help='Selected relative file; repeat for each source')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--course-id',required=True);p.add_argument('--name',required=True)
    p.add_argument('--discipline',action='append',required=True)
    p.add_argument('--workspace',default='local');p.add_argument('--institution')
    for field in ['curriculum-system','stage','language','syllabus-version']:
        p.add_argument('--'+field,default='unspecified')
    p.add_argument('--material-status',choices=['imported_course_material','demonstration'],default='imported_course_material')
    p.add_argument('--kind',default='unknown')
    p=sub.add_parser('apply-source-reviews',help='Apply a source-bound review request into a new course draft')
    for field in ['draft','library','request','output']:
        p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--course-id',required=True)
    p=sub.add_parser('render-knowledge-map',help='Check a source-bound topic outline and export a single-course reader')
    for field in ['library','proposal','output']:
        p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--course-id',required=True)
    p=sub.add_parser('study-file',help='Export visible source pages for study in an existing chat')
    p.add_argument('--library',type=Path,required=True)
    p.add_argument('--course-id',required=True)
    p.add_argument('--document',action='append',help='Select a source document ID; repeat to combine documents')
    p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('exam-outlook',help='Rank topics from past papers or evaluate a held-out exam year')
    p.add_argument('--library',type=Path,required=True)
    p.add_argument('--course-id',required=True)
    p.add_argument('--target-year',type=int,required=True)
    p.add_argument('--top-k',type=int,default=4)
    p.add_argument('--history-mode',choices=['paper_year','strict'],required=True)
    p.add_argument('--evaluate',action='store_true',help='After ranking, compare with the target sitting in this snapshot')
    for name in ['search','concept','question','related','page','evaluate','publish','serve','embed','status']:
        p=sub.add_parser(name);p.add_argument('--data',type=Path,default=Path('data/grt'))
        if name=='search':p.add_argument('--query',required=True)
        if name in {'concept','question','related'}:p.add_argument('--id',required=True)
        if name=='page':p.add_argument('--document',required=True);p.add_argument('--number',type=int,required=True)
        if name=='evaluate':
            p.add_argument('--cases',type=Path,required=True);p.add_argument('--split',choices=['development','reserved']);p.add_argument('--benchmark',action='store_true')
        if name=='publish':p.add_argument('--out',type=Path,required=True)
        if name=='serve':p.add_argument('--port',type=int,default=8766)
        if name=='embed':p.add_argument('--base-url',required=True);p.add_argument('--model',required=True)
    args=parser.parse_args(argv)
    if args.command=='serve-mcp-local':
        from .mcp_http import serve_local
        try:
            serve_local(args.library,args.workspace_root,args.course,args.port)
        except (OSError,ValueError) as exc:
            print(f'本机课程 MCP 启动失败：{exc}')
            return 1
        return 0
    if args.command=='serve-student':
        from .student_server import serve_student, StudentServerBusy
        try:
            serve_student(args.library,args.workspace_root,[] if args.private_only else args.course,args.port)
        except (OSError,ValueError,KeyError,StudentServerBusy) as exc:
            print(str(exc))
            return 1
        return 0
    elif args.command=='study-file':
        from .study_file import export_study_file
        try:
            result=export_study_file(args.library,args.course_id,args.document,args.output)
        except (ValueError,OSError) as exc:
            print(json.dumps({'status':'study_file_failed','error':str(exc)},ensure_ascii=False))
            return 1
    elif args.command=='exam-outlook':
        from .exam_outlook import exam_outlook,evaluate_outlook
        from .plugin_tools import load_library
        try:
            binding, store = load_library(args.library,[args.course_id])._course(args.course_id)
            analyze = evaluate_outlook if args.evaluate else exam_outlook
            result = analyze(store,binding.scope,args.course_id,args.target_year,args.top_k,args.history_mode)
        except (ValueError,OSError) as exc:
            print(json.dumps({'status':'outlook_failed','error':str(exc)},ensure_ascii=False))
            return 1
    elif args.command=='render-knowledge-map':
        from .course_reader import render_map_reader
        from .plugin_tools import load_library
        try:
            tools=load_library(args.library,[args.course_id])
            candidate=json.loads(args.proposal.read_text(encoding='utf-8'))
            result=render_map_reader(tools,args.course_id,candidate,args.output)
        except (ValueError,OSError) as exc:
            print(json.dumps({'status':'map_failed','error':str(exc)},ensure_ascii=False))
            return 1
    elif args.command=='apply-source-reviews':
        from .review_application import apply_source_reviews
        try:
            result=apply_source_reviews(args.draft,args.library,args.course_id,
                json.loads(args.request.read_text(encoding='utf-8')),args.output)
        except (ValueError,OSError) as exc:
            print(json.dumps({'status':'review_failed','error':str(exc),'model_called':False},ensure_ascii=False))
            return 1
    elif args.command=='draft-course':
        from .course_draft import create_course_draft
        try:
            result=create_course_draft(args.source_root,args.file,args.output,
                course_id=args.course_id,name=args.name,disciplines=args.discipline,workspace=args.workspace,
                curriculum_system=args.curriculum_system,institution=args.institution,stage=args.stage,
                language=args.language,syllabus_version=args.syllabus_version,
                material_status=args.material_status,kind=args.kind)
        except (ValueError,OSError) as exc:
            print(json.dumps({'status':'draft_failed','error':str(exc),'model_called':False},ensure_ascii=False))
            return 1
    elif args.command=='import-courses':
        from .course_library_import import import_course_library
        from pypdf.errors import PdfReadError
        from xml.etree.ElementTree import ParseError
        from zipfile import BadZipFile
        try:
            result=import_course_library(args.source_root,args.pack,args.output)
        except (ValueError,OSError,PdfReadError,BadZipFile,ParseError) as exc:
            print(json.dumps({'status':'import_failed','error':str(exc),'model_called':False},ensure_ascii=False))
            return 1
    elif args.command=='build-library':
        from .library import build_library
        result=build_library(args.source,args.audit,args.config,args.data)
    elif args.command=='build':
        result=build(args.source,args.audit,args.recipe,args.data)
    else:
        store,scope=load(args.data)
        service=service_for(args.data,store)
        if args.command=='search':result=service.search_evidence(scope,args.query).model_dump(mode='json')
        elif args.command=='concept':result=service.get_concept(scope,args.id).model_dump(mode='json')
        elif args.command=='question':result=service.get_question(scope,args.id).model_dump(mode='json')
        elif args.command=='related':result=service.get_related_questions(scope,args.id).model_dump(mode='json')
        elif args.command=='page':result=service.get_source_page(scope,args.document,args.number).model_dump(mode='json')
        elif args.command=='evaluate':
            from .evaluate import evaluate,benchmark
            cases=json.loads(args.cases.read_text(encoding='utf-8'))
            result=evaluate(cases,service,scope,args.split)
            if args.benchmark:result['performance']=benchmark(service,scope,[c['query'] for c in cases['cases'] if not c.get('missing')])
            atomic_json(args.data/'evaluation'/('report-'+(args.split or 'all')+'.json'),result)
        elif args.command=='publish':
            from .release import publish_release
            result=publish_release(store,scope,args.data/'assets',args.out,evaluation_dir=args.data/'evaluation')
        elif args.command=='serve':
            import uvicorn
            from .library import create_library_app
            uvicorn.run(create_library_app(args.data),host='127.0.0.1',port=args.port)
            return 0
        elif args.command=='embed':
            from .embeddings import EmbeddingClient,VectorIndex
            key=os.environ.get('EXAMSAGE_EMBEDDING_KEY')
            if not key:raise ValueError('Set EXAMSAGE_EMBEDDING_KEY in environment before explicit embedding build')
            client=EmbeddingClient(args.base_url,key,args.model)
            records=store.list_records(scope)
            vectors={}
            for offset in range(0,len(records),16):
                batch=records[offset:offset+16]
                texts=[r.title+'\n'+r.text for r in batch]
                vectors.update({r.id:v for r,v in zip(batch,client.embed(texts))})
            VectorIndex(args.data/'vectors.sqlite3',client.route).replace(scope.snapshot,vectors)
            atomic_json(args.data/'embedding-route.json',{'base_url':args.base_url,'model':args.model,'route':client.route})
            result={'snapshot':scope.snapshot,'embedded_records':len(vectors)}
        else:
            result=json.loads((args.data/'build_report.json').read_text(encoding='utf-8')) if (args.data/'build_report.json').exists() else {'snapshot':scope.snapshot}
            if result.get('snapshot') != scope.snapshot:
                result = {'snapshot':scope.snapshot, 'report_status':'build_report_snapshot_mismatch'}
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    if args.command=='build-library' and any('error' in course for course in result.values()):
        return 1
    return 0
