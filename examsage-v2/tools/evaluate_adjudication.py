"""Student scenarios and exact frozen-scope audit coverage, with saved evidence."""
from pathlib import Path
from collections import Counter
import argparse,json,math
from examsage.cli import load,service_for
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/adjudication-20261102'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def evaluate(data,phase):
    b=read(QA/'baseline.json');services={};results=[]
    def course(slug):
        if slug not in services:
            s,sc=load(data/slug);services[slug]=(s,sc,service_for(data/slug,s))
        return services[slug]
    if phase=='first':
        for row in b['pages']:
            s,sc,service=course(row['course']);r=service.get_source_page(sc,row['document_id'],row['number']).records[0]
            recovery=r.details['supplement']['audit']['recovery'];v=recovery.get('adjudication',{})
            tests={'explicit_conclusion':bool(v.get('category')),'original_uncertainty_kept':bool(recovery['unresolved']),
                   'linked_context':len(v.get('evidence',[]))>=2,'native_unchanged':r.details['raw_text']==row['native_text']}
            if row['course']=='ses' and row['number']==21:
                text=' '.join(x['text']+x.get('latex','') for x in recovery['blocks'])
                tests['literal_vs_corrected']='X_{13}' in text and 'X_{23}' in text and v.get('category')=='both'
                # Independent residual checks for the teaching example: all MW and radians.
                f12=100*(.12-.11)/.1;f13=100*.12/.3;f23=100*.11/.1
                tests['dcopf_residuals']=all(math.isclose(x,0,abs_tol=1e-10) for x in [50-f12-f13,100+f12-f23,f13+f23-150]) and math.isclose(f13,40)
            results.append({'id':r.id,'scenario':'学生查看原页并区分可读含义、校正式及字面缺口','checks':tests,'passed':all(tests.values())})
        for row in b['gaps']:
            s,sc,service=course('ses');d=row['details'];query=f"{d['exam_year']} Q{d['number']}"+''.join('('+p+')' for p in d['part'].split('.'))+' 怎么算，依据和假设是什么？'
            bundle=service.search_evidence(sc,query);target=next((r for r in bundle.records if r.id==row['id']),None)
            a=target.details.get('audit',{}) if target else {};v=a.get('adjudication',{})
            tests={'exact_question':target is not None,'answer_present':any(r.kind=='answer' and r.details.get('part')==d['part'] for r in bundle.records),
                   'gap_not_hidden':a.get('status')=='partial' and bool(v.get('remaining')),
                   'source_bound_guidance':bool(v.get('evidence')) and bool(v.get('actions'))}
            results.append({'id':row['id'],'scenario':query,'checks':tests,'passed':all(tests.values()),'limitations':bundle.limitations})
    else:
        s,sc,service=course('ses')
        for row in b['conflicts']:
            d=row['details'];query=f"{d['exam_year']} Q{d['number']}"+''.join('('+p+')' for p in d['part'].split('.'))+' 答案有错吗？请核对条件、公式和数值。'
            bundle=service.search_evidence(sc,query);target=next((r for r in bundle.records if r.id==row['id']),None)
            a=target.details.get('audit',{}) if target else {};v=a.get('adjudication',{})
            full=s.get(sc,row['id']);fa=full.details.get('audit',{})
            tests={'exact_question':target is not None,'answer_present':any(r.kind=='answer' and r.details.get('part')==d['part'] for r in bundle.records),
                   'classified':v.get('category') in {'system_error','source_error','both','insufficient_evidence'},
                   'source_evidence':bool(v.get('evidence')),'history_preserved':bool(fa.get('previous_assessment'))}
            results.append({'id':row['id'],'scenario':query,'checks':tests,'category':v.get('category'),'passed':all(tests.values()),'limitations':bundle.limitations})
    return {'phase':phase,'data':str(data),'total':len(results),'passed':sum(r['passed'] for r in results),'results':results}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=ROOT/'data');p.add_argument('--phase',choices=['first','conflicts'],required=True);p.add_argument('--label',required=True);args=p.parse_args()
    report=evaluate(args.data,args.phase);atomic_json(QA/(args.label+'.json'),report)
    print(json.dumps({k:v for k,v in report.items() if k!='results'}));print('Failed:',[r['id'] for r in report['results'] if not r['passed']])
