"""Student lookup, source scope, and executable audit checks for every SES part."""
from pathlib import Path
from collections import Counter
import json,argparse
from examsage.cli import load
from examsage.search import CourseQueryService
from examsage.numeric_audit import audit_numerical_check
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/recovery-ses-20261102'
parser=argparse.ArgumentParser();parser.add_argument('--qa',type=Path,default=QA);parser.add_argument('--data',type=Path,default=ROOT/'data/ses')
args=parser.parse_args();QA=args.qa
store,scope=load(args.data);service=CourseQueryService(store)
questions=[r for r in store.list_records(scope,'question') if r.details.get('scope')=='subquestion']
assert questions,'Build SES subquestions first'
exact=[];checks=[];failures=[]
def check(name,passed,qid=None):
    checks.append({'name':name,'passed':bool(passed),'question':qid})
def ancestors(record):
    result=[]
    while record:
        result.append(record.id)
        record=store.get(scope,record.parent_id) if record.parent_id else None
    return result
for q in questions:
    d=q.details;query=f"{d['exam_year']} Q{d['number']}"+''.join('('+x+')' for x in d['part'].split('.'))+' 答案'
    bundle=service.search_evidence(scope,query)
    passed=bool(bundle.records) and bundle.records[0].id==q.id
    exact.append({'query':query,'question':q.id,'passed':passed,'record_count':len(bundle.records),'limitations':bundle.limitations})
    if not passed:failures.append(exact[-1])
    paired=[e for e in store.related(scope,q.id) if e.kind=='has_answer' and e.source==q.id]
    answer=store.get(scope,paired[0].target) if paired else None
    expected=ancestors(q)+(ancestors(answer) if answer else [])
    direct=service.get_answer(scope,q.id)
    check('Complete question/answer parent context',[r.id for r in direct.records]==expected,q.id)
    check('Exact lookup includes mapped answer and ancestors',not passed or [r.id for r in bundle.records]==expected,q.id)
    check('Missing answer explicitly partial',bool(answer) or (d['audit']['status']=='partial' and direct.sufficiency=='insufficient'),q.id)
    if answer:
        check('Answer identity',all(d[k]==answer.details[k] for k in ['exam_year','number','part','year_basis']),q.id)
        check('Answer original document',answer.refs[0].document_id==d['paired_document_id'],q.id)
    for c in d['audit']['numerical_checks']:
        actual=audit_numerical_check(c)
        check('Arithmetic result and verdict reproducible',actual['computed_value']==c['computed_value'] and actual['comparison']==c['comparison'],q.id)
        check('A numerical mismatch cannot claim checked',c['comparison']!='mismatch' or d['audit']['status']!='checked',q.id)
    restricted=scope.model_copy(update={'allowed_sources':[q.refs[0].document_id]})
    hidden=service.get_answer(restricted,q.id)
    check('Question-only scope hides answer and joint audit',hidden.sufficiency=='insufficient' and not any(r.kind=='answer' or r.details.get('audit') for r in hidden.records),q.id)
for query in ['2099 Q1(a) 答案','2024 Q1(z) 答案','2024 Q1(a)(i)(x) 答案','2024 Q1(a) and (b) answer','2024 Q1 and Q2 answers']:
    check('Absent or ambiguous query refuses fallback: '+query,not service.search_evidence(scope,query).records)
report={'exact_queries':{'total':len(exact),'passed':sum(r['passed'] for r in exact),'results':exact},
    'checks':{'total':len(checks),'passed':sum(r['passed'] for r in checks),'results':checks},
    'failures':failures+[r for r in checks if not r['passed']]}
atomic_json(QA/'ses-verification.json',report)
print(json.dumps({k:{a:b for a,b in v.items() if a!='results'} for k,v in report.items() if k!='failures'}))
if report['failures']:print(json.dumps(report['failures'][:12],ensure_ascii=False))
