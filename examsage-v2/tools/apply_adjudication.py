"""Apply review overlays to a new pilot; never rewrite the v0.3 baseline."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse,json
from examsage.cli import load
from examsage.domain import Page
from examsage.course_pilots import load_pilot
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/adjudication-20261102'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def main(complete=False):
    baseline=read(QA/'baseline.json');recipe=read(ROOT/'courses/ses_pilot_v3.json')
    records={r['id']:r for r in recipe['records']}
    pairs={e['source']:e['target'] for e in recipe['relations'] if e['kind']=='has_answer'}
    overlays=[]
    for name in ['gaps','2019_2020','2021_2023','2024_2025']:
        path=ROOT/'courses'/f'adjudication_{name}.json'
        if path.exists():overlays+=read(path)
    ids=[r['record_id'] for r in overlays]
    assert len(ids)==len(set(ids)),'Duplicate adjudication'
    expected={r['id'] for r in baseline['gaps']+baseline['conflicts']}
    assert set(ids)<=expected,'Outside frozen baseline'
    if complete:assert set(ids)==expected,'Incomplete adjudication scope'
    for entry in overlays:
        q=records[entry['record_id']];a=records[pairs[q['id']]]
        for target,key in [(q,'question_text'),(a,'answer_text')]:
            previous=deepcopy(target['details']['audit'])
            target['details']['audit']={**deepcopy(entry['audit']),'adjudication':deepcopy(entry['adjudication']),
                                      'previous_assessment':previous}
            if key in entry:target['text']=entry[key]
        for correction in entry.get('related_corrections',[]):
            target=records[correction['record_id']]
            if 'text' in correction:target['text']=correction['text']
            if 'audit' in correction:
                previous=target['details'].get('audit',{})
                target['details']['audit']={**deepcopy(correction['audit']),
                    'previous_assessment':deepcopy(previous.get('previous_assessment',previous))}
        for e in entry['adjudication']['evidence']:
            old=recipe['source_hashes'].get(e['document_id'])
            assert old is None or old==e['source_sha256']
            recipe['source_hashes'][e['document_id']]=e['source_sha256']
    dest=ROOT/'courses/ses_pilot_v4.json';atomic_json(dest,recipe)
    store,scope=load(ROOT/'data/ses');manifest=store.manifest(scope)
    pages=[Page.model_validate(p) for p in read(ROOT/'data/ses/pages.json')]
    checked,_,_=load_pilot(dest,manifest,pages)
    for row in read(ROOT/'courses/adjudication_pages.json'):
        slug=row['course'];sha=row['source_sha256'];n=row['number']
        path=ROOT/'courses'/f'{slug}_page_supplements.json';data=read(path)
        item=next(p for p in data['documents'][sha]['pages'] if p['number']==n)
        item['recovery']=deepcopy(row['recovery']);atomic_json(path,data)
        package_path=ROOT/'data'/slug/'page-supplements'/(sha+'.json');package=read(package_path)
        next(p for p in package['pages'] if p['number']==n)['audit']=deepcopy(item)
        atomic_json(package_path,package)
    config=read(ROOT/'courses/library.json');config['courses']['ses']['pilot']=dest.name
    atomic_json(ROOT/'courses/library.json',config)
    summary={'pages':5,'gap_reviews':sum(i in {r['id'] for r in baseline['gaps']} for i in ids),
             'conflict_reviews':sum(i in {r['id'] for r in baseline['conflicts']} for i in ids),
             'categories':dict(Counter(e['adjudication']['category'] for e in overlays))}
    atomic_json(QA/'integration.json',summary);print(json.dumps(summary))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--complete',action='store_true')
    main(parser.parse_args().complete)
