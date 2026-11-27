"""Integrate additional local-source checks without rewriting v0.4 or its reports."""
from pathlib import Path
from copy import deepcopy
import json
from examsage.cli import load
from examsage.domain import Page
from examsage.course_pilots import load_pilot
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/followup-20261102'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
    base=read(ROOT/'courses/ses_pilot_v4.json');recipe=deepcopy(base)
    oldstore,oldscope=load(ROOT/'data/releases/library-v0.4-20261102/ses')
    old={r.id:r.model_dump(mode='json') for r in oldstore.list_records(oldscope)}
    records={r['id']:r for r in recipe['records']};pairs={r['source']:r['target'] for r in recipe['relations'] if r['kind']=='has_answer'}
    seven=read(ROOT/'courses/followup_seven.json');gaps=read(ROOT/'courses/followup_gaps.json')
    expected={r['record_id'] for name in ['2019_2020','2021_2023','2024_2025'] for r in read(ROOT/'courses'/f'adjudication_{name}.json') if r['adjudication']['category']=='insufficient_evidence'}
    assert {r['record_id'] for r in seven}==expected and len(seven)==7
    assert {r['record_id'] for r in gaps}=={r['record_id'] for r in read(ROOT/'courses/adjudication_gaps.json')} and len(gaps)==3
    for e in seven+gaps:
        for target,key in [(records[e['record_id']],'question_text'),(records[pairs[e['record_id']]],'answer_text')]:
            target['details']['audit']={**deepcopy(e['audit']),'adjudication':deepcopy(e['adjudication']),'previous_assessment':deepcopy(old[target['id']]['details']['audit'])}
            if key in e:target['text']=e[key]
        for c in e.get('related_corrections',[]):
            target=records[c['record_id']]
            if 'text' in c:target['text']=c['text']
            if 'audit' in c:target['details']['audit']={**deepcopy(c['audit']),'previous_assessment':deepcopy(old[target['id']]['details'].get('audit',{}))}
        for ref in e['adjudication']['evidence']:recipe['source_hashes'][ref['document_id']]=ref['source_sha256']
    dest=ROOT/'courses/ses_pilot_v5.json';atomic_json(dest,recipe)
    s,sc=load(ROOT/'data/ses');pages=[Page.model_validate(p) for p in read(ROOT/'data/ses/pages.json')]
    load_pilot(dest,s.manifest(sc),pages)
    page_rows=read(ROOT/'courses/followup_pages.json');assert len(page_rows)==5
    assert {(p['document_id'],p['number']) for p in page_rows}=={(p['document_id'],p['number']) for p in read(ROOT/'courses/adjudication_pages.json')}
    for row in page_rows:
        slug=row['course'];sha=row['source_sha256'];n=row['number']
        path=ROOT/'courses'/f'{slug}_page_supplements.json';data=read(path)
        item=next(p for p in data['documents'][sha]['pages'] if p['number']==n);item['recovery']=row['recovery'];atomic_json(path,data)
        pp=ROOT/'data'/slug/'page-supplements'/(sha+'.json');package=read(pp)
        next(p for p in package['pages'] if p['number']==n)['audit']=deepcopy(item);atomic_json(pp,package)
    config=read(ROOT/'courses/library.json');config['courses']['ses']['pilot']=dest.name;atomic_json(ROOT/'courses/library.json',config)
    atomic_json(QA/'integration.json',{'conflicts':7,'gaps':3,'pages':5,'base':'library-v0.4-20261102'})
    print('Validated and integrated 7 conflicts, 3 gaps, 5 pages')
if __name__=='__main__':main()
