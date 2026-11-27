"""Run held source-locator cases; this does not grade generated explanations."""
import json
import sys
from pathlib import Path
from examsage.cli import load
from examsage.search import CourseQueryService
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/low-text-20261028'
results=[]
for slug,file in [('geodynamics','geodynamics-evaluation.json'),('planetary_science','planetary-evaluation.json'),('ses','ses-evaluation.json')]:
    cases=json.loads((QA/file).read_text(encoding='utf-8'));store,scope=load(ROOT/'data'/slug);service=CourseQueryService(store)
    for case in cases.get('cases',cases.get('queries',[])):
        query=case.get('query',case.get('question'));bundle=service.search_evidence(scope,query)
        actual_ids={r.id for r in bundle.records};actual_refs={(r.document_id,r.page) for record in bundle.records for r in record.refs}
        if slug=='ses':
            missing=case['expected_behavior'] in ['report_not_in_loaded_sources','subquestion_not_extracted']
            expected=set(case.get('expected_question_ids',[])+(case.get('expected_answer_ids',[]) if case['expected_behavior']!='return_question' else []))
            passed=not bundle.records and bundle.sufficiency=='insufficient' if missing else expected<=actual_ids
        else:
            refs=case.get('expected_refs',case.get('expected',[]))
            expected={(r['document_id'],r.get('page',r.get('number'))) for r in refs}
            passed=bool(expected) and expected<=actual_refs
        results.append({'id':case.get('id'),'course':slug,'query':query,'passed':passed,'returned':[r.id for r in bundle.records],
                        'expected':sorted(expected),'limitations':bundle.limitations})
report={'round':'source-locator-natural-queries','total':len(results),'passed':sum(r['passed'] for r in results),'results':results,
        'scope':'Checks source localization and answer associations only, not generated educational answers.'}
(QA/(sys.argv[1] if len(sys.argv)>1 else 'round3.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'total':report['total'],'passed':report['passed'],'failed':[{'id':r['id'],'query':r['query'],'returned':r['returned'][:3]} for r in results if not r['passed']]},ensure_ascii=False))
