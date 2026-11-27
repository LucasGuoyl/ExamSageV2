"""Student retrieval, conditional answers, source provenance and current review checks."""
from pathlib import Path
import json
from examsage.cli import load,service_for
from examsage.numeric_audit import audit_numerical_check
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/followup-20261102'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    services={}
    def get(slug):
        if slug not in services:
            s,sc=load(ROOT/'data'/slug);services[slug]=(s,sc,service_for(ROOT/'data'/slug,s))
        return services[slug]
    for name in ['seven','gaps']:
        rows=[];s,sc,service=get('ses')
        for entry in read(ROOT/'courses'/f'followup_{name}.json'):
            r=s.get(sc,entry['record_id']);d=r.details
            q=f"{d['exam_year']} Q{d['number']}"+''.join('('+x+')' for x in d['part'].split('.'))+' 答案，条件从哪里来？'
            bundle=service.search_evidence(sc,q);a=d['audit'];v=a['adjudication']
            checks={'exact_question':bool(bundle.records) and bundle.records[0].id==r.id,
                    'answer_present':any(x.kind=='answer' and x.details.get('part')==d['part'] for x in bundle.records),
                    'updated_evidence':v==entry['adjudication'],
                    'history':bool(a.get('previous_assessment')),
                    'uncertainty_explicit':a['status']!='partial' or bool(v['remaining']),
                    'numeric_reproducible':all(audit_numerical_check(c)['computed_value']==c['computed_value'] for c in a['numerical_checks'])}
            restricted=sc.model_copy(update={'allowed_sources':[r.refs[0].document_id]})
            checks['question_only_scope']='audit' not in s.get(restricted,r.id).details
            rows.append({'id':r.id,'query':q,'passed':all(checks.values()),'checks':checks})
        atomic_json(QA/(name+'-students.json'),{'total':len(rows),'passed':sum(x['passed'] for x in rows),'results':rows})
        print(name,sum(x['passed'] for x in rows),'/',len(rows))
    rows=[]
    for e in read(ROOT/'courses/followup_pages.json'):
        s,sc,service=get(e['course']);r=service.get_source_page(sc,e['document_id'],e['number']).records[0]
        a=r.details['supplement']['audit']['recovery'];rows.append({'id':r.id,'passed':a==e['recovery'] and bool(a.get('adjudication',{}).get('evidence')) and bool(a.get('previous_assessment'))})
    atomic_json(QA/'pages-students.json',{'total':5,'passed':sum(x['passed'] for x in rows),'results':rows});print('pages',sum(x['passed'] for x in rows),'/5')
if __name__=='__main__':main()
