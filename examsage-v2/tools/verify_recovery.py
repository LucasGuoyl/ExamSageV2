"""Check all recovered sources, raw extraction, and student retrieval cases."""
from pathlib import Path
from hashlib import sha256
import json
from examsage.cli import load, service_for
from examsage.ingest import atomic_json

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'data/qa/recovery-ses-20261102'
inventory=json.loads((QA/'inventory.json').read_text(encoding='utf-8'))
services={}
checks=[]
for row in inventory:
    slug=row['course']
    if slug not in services:
        store,scope=load(ROOT/'data'/slug)
        services[slug]=(store,scope,service_for(ROOT/'data'/slug,store))
    store,scope,service=services[slug]
    page=service.get_source_page(scope,row['document_id'],row['number']).records[0]
    supplement=page.details['supplement']
    doc=next(d for d in store.manifest(scope).documents if d.id==row['document_id'])
    checks.append({'course':slug,'document_id':row['document_id'],'page':row['number'],
        'native_unchanged':page.details['raw_text']==row['native_text'],
        'ocr_unchanged':supplement['ocr']==row['ocr'],
        'ocr_not_promoted':not supplement['ocr_indexed'],
        'recovery_indexed':all(b['text'] in page.text for b in supplement['audit']['recovery']['blocks']),
        'image_unchanged':sha256(Path(row['image']).read_bytes()).hexdigest()==row['render_sha256'],
        'source_unchanged':sha256((ROOT/'data'/slug/'assets'/doc.asset).read_bytes()).hexdigest()==row['source_sha256']})
cases=[]
for name in ['bending','heat','other']:
    path=QA/f'{name}-evaluation.json'
    batch=json.loads(path.read_text(encoding='utf-8'))
    for case in batch['cases'] if isinstance(batch,dict) else batch:
        slug=case.get('course','geodynamics')
        bundle=services[slug][2].search_evidence(services[slug][1],case['query'])
        refs={(r.document_id,r.page) for record in bundle.records for r in record.refs}
        expected={(r['document_id'],r.get('page',r.get('number'))) for r in case['expected_refs']}
        cases.append({**case,'passed':expected<=refs,'actual_refs':[list(r) for r in sorted(refs)],'limitations':bundle.limitations})
flags=['native_unchanged','ocr_unchanged','ocr_not_promoted','recovery_indexed','image_unchanged','source_unchanged']
result={'page_checks':{'total':len(checks)*len(flags),'passed':sum(r[k] for r in checks for k in flags),'results':checks},
        'student_retrieval':{'total':len(cases),'passed':sum(c['passed'] for c in cases),'results':cases}}
atomic_json(QA/'recovery-verification.json',result)
print(json.dumps({key:{k:v for k,v in value.items() if k!='results'} for key,value in result.items()}))
