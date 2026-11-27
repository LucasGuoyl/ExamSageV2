"""Attach reviewed recovery blocks only to the frozen 74-page inventory."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
from examsage.supplements import validate_recovery
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/recovery-ses-20261102'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
inventory=read(QA/'inventory.json');expected={(r['document_id'],r['number']):r for r in inventory};found={}
for name in ['bending','heat','other']:
    package=read(ROOT/'courses'/f'recovery_{name}.json')
    assert package['schema']=='page-recovery-batch-v1'
    for item in package['pages']:
        key=item['document_id'],item['number'];assert key not in found and key in expected
        source=expected[key]
        assert item['source_sha256']==source['source_sha256'] and item['render_sha256']==source['render_sha256']
        assert sha256(Path(source['image']).read_bytes()).hexdigest()==source['render_sha256']
        validate_recovery(item['recovery'],*key);found[key]=item
assert len(found)==len(expected)==74
recipes={slug:read(ROOT/'courses'/f'{slug}_page_supplements.json') for slug in {r['course'] for r in inventory}}
for key,item in found.items():
    row=expected[key];pages=recipes[row['course']]['documents'][row['source_sha256']]['pages']
    page=next(p for p in pages if p['number']==row['number']);page['recovery']=item['recovery']
for slug,recipe in recipes.items():atomic_json(ROOT/'courses'/f'{slug}_page_supplements.json',recipe)
report={'pages':74,'states':dict(Counter(r['recovery']['status'] for r in found.values())),
        'blocks':sum(len(r['recovery']['blocks']) for r in found.values()),'unresolved_pages':[{'document_id':k[0],'number':k[1],'notes':v['recovery']['unresolved']} for k,v in found.items() if v['recovery']['unresolved']],
        'native_and_ocr_unchanged':True,'expert_acceptance':'pending'}
atomic_json(QA/'recovery-coverage.json',report);print(json.dumps({k:v for k,v in report.items() if k!='unresolved_pages'}))
