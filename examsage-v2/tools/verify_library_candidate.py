"""Verify exported hashes, raw sources and reopened course behavior."""
from pathlib import Path
from hashlib import sha256
import json
from examsage.cli import load
from examsage.search import CourseQueryService
from examsage.evaluate import evaluate
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/low-text-20261028'
release=ROOT/'data/releases/library-v0.2-20261028'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
result={'status':'passed','sources':0,'hashed_files':0,'supplements':0,'answer_pairs':0,'courses':{}}
for row in read(ROOT.parent/'output/course-audit/2026-10-25-course-inventory.json')['files']:
    source=ROOT.parent/'files/exam_predictor/exam_predictor/data_samples'/Path(row['relative_path'])
    assert sha256(source.read_bytes()).hexdigest()==row['sha256'];result['sources']+=1
for entry in read(release/'library.json')['courses']:
    folder=release/entry['data'];manifest=read(folder/'release_manifest.json')
    for relative,expected in manifest['files'].items():
        assert sha256((folder/relative).read_bytes()).hexdigest()==expected;result['hashed_files']+=1
    store,scope=load(folder);service=CourseQueryService(store)
    result['courses'][entry['slug']]={'records':len(store.list_records(scope)),'snapshot':scope.snapshot}
    inventory=[r for r in read(QA/'inventory.json') if r['course']==entry['slug']]
    for row in inventory:
        block=service.get_source_page(scope,row['document_id'],row['number']).records[0]
        assert block.details['raw_text']==row['native_text']
        supplement=block.details['supplement'];assert supplement['render_sha256']==row['render_sha256']
        assert sha256((folder/'assets'/supplement['image_asset']).read_bytes()).hexdigest()==row['render_sha256']
        assert supplement['expert_acceptance']=='pending';result['supplements']+=1
    if entry['slug']=='ses':
        for q in store.list_records(scope,'question'):
            b=service.get_answer(scope,q.id);assert len(b.records)==2
            a=b.records[1];assert a.details['exam_year']==q.details['exam_year'] and a.details['number']==q.details['number']
            assert a.refs[0].document_id==q.details['paired_document_id'];result['answer_pairs']+=1
    if entry['slug']=='grt':
        report=evaluate(read(ROOT/'evaluation/grt_cases.json'),service,scope)
        assert report['passed']==report['total']==40;result['grt_cases']=40
assert result['sources']==98 and result['supplements']==208 and result['answer_pairs']==28
(QA/'release-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
