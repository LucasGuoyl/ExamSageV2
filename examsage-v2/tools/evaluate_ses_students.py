from pathlib import Path
import json
from examsage.cli import load
from examsage.search import CourseQueryService
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/recovery-ses-20261102'
store,scope=load(ROOT/'data/ses');service=CourseQueryService(store);results=[]
for path in sorted(QA.glob('ses-*-evaluation.json')):
    batch=json.loads(path.read_text(encoding='utf-8'))
    for case in batch['cases'] if isinstance(batch,dict) else batch:
        bundle=service.search_evidence(scope,case['query'])
        ids={r.id for r in bundle.records};refs={(s.document_id,s.page) for r in bundle.records for s in r.refs}
        expected=case.get('expected_ids') or case.get('expected_record_ids') or [case['expected_question_id'],case['expected_answer_id']]
        wanted={(r['document_id'],r.get('page',r.get('number'))) for r in case['expected_refs']}
        results.append({'query':case['query'],'passed':set(expected)<=ids and wanted<=refs,'expected':expected,'returned_ids':sorted(ids),'limitations':bundle.limitations})
for query,qid in [('2019 Q3(f)(i) 1400万家庭热泵每年用电的答案。','imperial:elec70076:exam:2019:q3:f.i'),('2020 Q1(d)(iii) 500 W每平方米光伏阵列输出的答案单位。','imperial:elec70076:exam:2020:q1:d.iii')]:
    bundle=service.search_evidence(scope,query);results.append({'query':query,'passed':bool(bundle.records) and bundle.records[0].id==qid})
report={'total':len(results),'passed':sum(r['passed'] for r in results),'results':results}
atomic_json(QA/'ses-student-retrieval.json',report)
print(json.dumps({k:v for k,v in report.items() if k!='results'}))
print(json.dumps([r for r in results if not r['passed']],ensure_ascii=False))
