"""Offline data audit and real-response fixtures for browser component checks.

No model/provider/network calls. This does NOT substitute for live HTTP tests.
"""
from pathlib import Path
from hashlib import sha256
from collections import Counter
from urllib.parse import urlencode
import json, time
from PIL import Image
from fastapi.encoders import jsonable_encoder
from fastapi import HTTPException
from examsage.api import create_app
from examsage.cli import load
from examsage.search import CourseQueryService
from examsage.slides import validated_slide_asset
from examsage.ingest import atomic_json

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'data/qa/comprehensive-20261106'
WEB=ROOT/'src/examsage/web'

def read(p): return json.loads(p.read_text(encoding='utf-8'))

def require_success(results):
    if any(not row['passed'] for row in results):
        raise SystemExit(1)

def main():
    QA.mkdir(parents=True,exist_ok=True)
    entries=read(ROOT/'data/library.json')['courses']
    catalog=[{'slug':e['slug'],'name':e['name'],'url':'/' if e['slug']=='grt' else '/courses/'+e['slug']+'/'} for e in entries]
    files=[*ROOT.glob('src/examsage/**/*.py'),*ROOT.glob('src/examsage/web/*.*'),*ROOT.glob('tests/test_*.py'),*ROOT.glob('courses/*.json')]
    if not (QA/'version-before.json').exists():
        atomic_json(QA/'version-before.json',{'files':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in files},'snapshots':{e['slug']:read(ROOT/'data'/e['slug']/'current.json') for e in entries}})
    fixtures={}; results=[]; stats={}; student=[]
    def check(name,passed,**details):results.append({'name':name,'passed':bool(passed),**details})
    def save(path,value):fixtures[path]={'status':200,'contentType':'application/json','body':json.dumps(jsonable_encoder(value),ensure_ascii=False)}
    def static(path,local,content_type):fixtures[path]={'status':200,'contentType':content_type,'path':str(local)}
    queries={
      'grt':['2023年Q1地下水年龄','2024 Q1 地下水年龄','2022 Q1','2024 Q1(ii)','2024 Q1(iv)','2024 Q100 地下水年龄','2023年真题试卷','2024 Q1 official answer','2024 Q1','2023 Q1','Darcy','比较 2023 Q1 和 2024 Q1','碳14校正推导','36Cl 推导','孔隙度与孔隙流速','反应前缘公式','Ozark 流动驱动力','地下水','预测下一年考试范围','请给我生成一份模拟试卷','这个课程怎么复习','xyzzynonexistent20261106'],
      'geodynamics':['板块弯曲','热传导','地幔对流','流变','板块弯曲推导','2024 Q1'],
      'planetary_science':['火星','陨石坑','行星形成','大气','2024 Q1'],
      'sea_level':['海平面','冰盖','冰后回弹','珊瑚','2024 Q1'],
      'ses':['潮流','输电','可再生能源','电力市场','官方答案','2024 Q2(a)(b) 答案','2024 Q1(c)(i) 答案','2024 Q1 c.i answer','2024 Q1c(i) answer','2019-20 Q1(a) 答案','2099 Q1(a)答案','2024 Q1(z)答案','2024 Q1(c)(i)(x)答案','2024 Q1(a) and (b) answers','2022 Q1(a)(ii) 答案','2022 Q3(d)(iv) 答案','2023 Q4(a) 答案','2019 Q4(b)(ii) 答案','2020 Q4(f) 答案','2021 Q2(f) 答案','2021 Q2(g) 答案','2023 Q2(c)(b) 答案','2023 Q2(c)(c) 答案','2024 Q4(c)(iv) 答案']}
    for p in WEB.rglob('*'):
        if p.is_file():
            ext=p.suffix.lower();ct={'.html':'text/html','.css':'text/css','.js':'text/javascript','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf'}.get(ext,'application/octet-stream')
            static('/static/'+p.relative_to(WEB).as_posix(),p,ct)
    fixtures['/favicon.ico']={'status':204,'body':''}
    for entry in entries:
        slug=entry['slug'];folder=ROOT/'data'/slug;base='' if slug=='grt' else '/courses/'+slug
        app=create_app(folder,catalog);routes={r.path:r.endpoint for r in app.routes if hasattr(r,'endpoint')}
        store,scope=load(folder);service=CourseQueryService(store);records=store.list_records(scope);manifest=store.manifest(scope)
        by_id={r.id:r for r in records};docs={d.id:d for d in manifest.documents}
        stats[slug]={'snapshot':scope.snapshot,'documents':len(docs),'pages':sum(d.pages for d in docs.values()),'records':len(records),'kinds':dict(Counter(r.kind for r in records))}
        fixtures[base+'/']={'status':200,'contentType':'text/html','path':str(WEB/'index.html')}
        for path in ['/api/status','/api/documents','/api/courses']:save(base+path,routes[path]())
        for kind in ['concept','example','formula','question']:
            for roots in [False,True]:
                q={'kind':kind}
                if roots:q['roots']='true'
                save(base+'/api/records?'+urlencode(sorted(q.items())),routes['/api/records'](kind=kind,topic=None,parent=None,roots=roots))
            for t in (store.metadata(scope) or {}).get('topics',[]):
                save(base+'/api/records?'+urlencode(sorted({'kind':kind,'topic':t['id']}.items())),routes['/api/records'](kind=kind,topic=t['id'],parent=None,roots=False))
        for r in records:
            if r.kind in ['concept','formula','example']:
                save(base+'/api/related/'+r.id,service.get_related_questions(scope,r.id))
            if r.details.get('derivation'):
                save(base+'/api/record/'+r.id,routes['/api/record/{record_id:path}'](r.id))
        if slug=='ses':
            for qid in ['imperial:elec70076:exam:2024:q2','imperial:elec70076:exam:2024:q2:a','imperial:elec70076:exam:2024:q2:a.b']:
                save(base+'/api/records?'+urlencode(sorted({'kind':'question','parent':qid}.items())),routes['/api/records'](kind='question',topic=None,parent=qid,roots=False))
                save(base+'/api/question/'+qid,service.get_question(scope,qid));save(base+'/api/answer/'+qid,service.get_answer(scope,qid))
        query_pages=set()
        for query in queries[slug]:
            start=time.perf_counter();bundle=service.search_evidence(scope,query);ms=(time.perf_counter()-start)*1000
            save(base+'/api/search?'+urlencode({'q':query}),bundle)
            student.append({'course':slug,'query':query,'milliseconds':round(ms,2),'sufficiency':bundle.sufficiency,'ids':[r.id for r in bundle.records],'limitations':bundle.limitations})
            query_pages.update((ref.document_id,ref.page) for r in bundle.records for ref in r.refs)
        page_targets={(d.id,1) for d in docs.values()}|{(d.id,d.pages) for d in docs.values() if d.relative_path.lower().endswith('.pptx')}
        page_targets|=query_pages
        if slug=='grt':
            page_targets|={(d.id,n) for d in docs.values() for n in range(1,d.pages+1) if d.kind=='exam' or 'groundwater' in d.relative_path.lower()}
        if slug=='sea_level':page_targets.add(('doc_853032ec56a887ddfeea1636',16))
        if slug=='ses':page_targets|={('doc_f12ea8990d648711e1b6dd3d',n) for n in [16,19,21,24,25,26,31]}
        for r in records:
            check('record source references',all(ref.document_id in docs and 1<=ref.page<=docs[ref.document_id].pages for ref in r.refs),course=slug,id=r.id)
            if r.kind!='block':page_targets|={(ref.document_id,ref.page) for ref in r.refs}
            else:
                if (r.details.get('supplement') or {}).get('recovery_status'):page_targets|={(r.refs[0].document_id,r.refs[0].page)}
                if r.details.get('render'):
                    p=validated_slide_asset(docs[r.refs[0].document_id],r.details,folder/'assets')
                    try:
                        assert p is not None
                        with Image.open(p) as img: img.verify()
                        check('complete PPTX image decode',True,course=slug,id=r.id)
                    except Exception as e:check('complete PPTX image decode',False,course=slug,id=r.id,error=str(e))
        blocks=[r for r in records if r.kind=='block']
        for doc in docs.values():
            check('original source hash',sha256((folder/'assets'/doc.asset).read_bytes()).hexdigest()==doc.sha256,course=slug,id=doc.id)
            visible=[r for r in blocks if r.refs[0].document_id==doc.id]
            check('visible pages unique',len(visible)==len({r.refs[0].page for r in visible}),course=slug,id=doc.id)
        for doc_id,number in sorted(page_targets):
            try:
                value=routes['/api/page/{doc_id}/{number}'](doc_id,number);save(base+f'/api/page/{doc_id}/{number}',value)
                if value['preview_url']:
                    response=routes['/api/preview/{doc_id}/{number}'](doc_id,number)
                    static(base+value['preview_url'],Path(response.path),'image/png')
                    with Image.open(response.path) as img: img.verify()
                    check('selected PDF/PPTX preview decode',True,course=slug,id=doc_id,page=number)
            except HTTPException as e:
                fixtures[base+f'/api/page/{doc_id}/{number}']={'status':e.status_code,'body':json.dumps({'detail':e.detail})}
                # Hidden slides intentionally have no visible record.
                hidden=not any(r.refs[0].document_id==doc_id and r.refs[0].page==number for r in blocks)
                check('selected page intentionally hidden',hidden and e.status_code==404,course=slug,id=doc_id,page=number)
            except Exception as e:check('selected PDF/PPTX preview decode',False,course=slug,id=doc_id,page=number,error=str(e))
        print(slug,stats[slug],flush=True)
        atomic_json(QA/'offline-data.json',{'total':len(results),'passed':sum(r['passed'] for r in results),'courses':stats,'results':results})
    atomic_json(QA/'student-queries.json',student)
    atomic_json(QA/'browser-fixtures.json',fixtures)
    # Embed generated JSON in a JS function so browser tooling needs no filesystem API.
    harness='async(page)=>{ const fixtures='+json.dumps(fixtures,ensure_ascii=False)+';const misses=[]; await page.route("http://127.0.0.1:8766/**",async route=>{const u=new URL(route.request().url());const pairs=[...u.searchParams.entries()].sort(([a],[b])=>a.localeCompare(b));const q=new URLSearchParams(pairs).toString();const key=decodeURIComponent(u.pathname)+(q?"?"+q:"");const value=fixtures[key]||(u.pathname.endsWith("/")?fixtures[u.pathname]:null);if(value){await route.fulfill(value);}else{misses.push(key);await route.fulfill({status:404,contentType:"application/json",body:JSON.stringify({detail:"Unrecorded fixture: "+key})});}});globalThis.__qaFixtureMisses=misses;return {mode:"real-snapshot response replay; NOT live HTTP",fixtures:Object.keys(fixtures).length};}'
    (QA/'setup-browser.js').write_text(harness,encoding='utf-8')
    print('passed',sum(r['passed'] for r in results),'/',len(results),'fixtures',len(fixtures),flush=True)
    require_success(results)

if __name__=='__main__':main()
