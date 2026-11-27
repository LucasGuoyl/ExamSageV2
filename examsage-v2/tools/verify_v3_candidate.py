"""Reopen the v3 candidate and verify original sources, exports and all parts."""
from pathlib import Path
from hashlib import sha256
import json,argparse
from examsage.cli import load
from examsage.search import CourseQueryService
from examsage.evaluate import evaluate
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/recovery-ses-20261102'
release=ROOT/'data/releases/library-v0.3-20261102'
parser=argparse.ArgumentParser();parser.add_argument('--release',type=Path,default=release);parser.add_argument('--qa',type=Path,default=QA)
args=parser.parse_args();release=args.release;QA=args.qa
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
result={'status':'passed','sources':0,'hashed_files':0,'supplements':0,'recovery_pages':0,'subquestion_pairs':0,'courses':{}}
for row in read(ROOT.parent/'output/course-audit/2026-10-25-course-inventory.json')['files']:
    path=ROOT.parent/'files/exam_predictor/exam_predictor/data_samples'/row['relative_path']
    assert sha256(path.read_bytes()).hexdigest()==row['sha256'];result['sources']+=1
for entry in read(release/'library.json')['courses']:
    folder=release/entry['data'];manifest=read(folder/'release_manifest.json')
    for relative,expected in manifest['files'].items():
        assert sha256((folder/relative).read_bytes()).hexdigest()==expected;result['hashed_files']+=1
    store,scope=load(folder);service=CourseQueryService(store)
    records=store.list_records(scope)
    result['courses'][entry['slug']]={'records':len(records),'snapshot':scope.snapshot}
    for row in read(ROOT/'data/qa/low-text-20261028/inventory.json'):
        if row['course']!=entry['slug']:continue
        block=service.get_source_page(scope,row['document_id'],row['number']).records[0]
        assert block.details['raw_text']==row['native_text'];s=block.details['supplement']
        assert s['render_sha256']==row['render_sha256'] and s['expert_acceptance']=='pending'
        assert sha256((folder/'assets'/s['image_asset']).read_bytes()).hexdigest()==row['render_sha256'];result['supplements']+=1
        if s.get('recovery_status'):
            assert not s['ocr_indexed'] and s['audit']['recovery']['blocks'];result['recovery_pages']+=1
    if entry['slug']=='ses':
        for q in [r for r in records if r.kind=='question' and r.details.get('scope')=='subquestion']:
            query=f"{q.details['exam_year']} Q{q.details['number']}"+''.join('('+p+')' for p in q.details['part'].split('.'))+' 答案'
            bundle=service.search_evidence(scope,query);assert bundle.records[0].id==q.id
            answer=next(r for r in bundle.records if r.kind=='answer')
            assert all(answer.details[k]==q.details[k] for k in ['exam_year','number','part'])
            assert answer.refs[0].document_id==q.details['paired_document_id'];result['subquestion_pairs']+=1
    if entry['slug']=='grt':
        report=evaluate(read(ROOT/'evaluation/grt_cases.json'),service,scope)
        assert report['passed']==report['total']==40;result['grt_cases']=40
assert result['sources']==98 and result['supplements']==208 and result['recovery_pages']==74 and result['subquestion_pairs']==329
atomic_json(QA/'release-verification.json',result)
print(json.dumps(result,ensure_ascii=False))
