"""Validate and assemble every SES paper's explicit subquestion tree."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import json
from examsage.cli import load
from examsage.course_pilots import load_pilot
from examsage.domain import Page
from examsage.ingest import atomic_json

ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/recovery-ses-20261102'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
base=read(ROOT/'courses/ses_pilot.json');recipe=deepcopy(base)
years=[];coverage=[];batches=[]
for name in ['2019_2020','2021_2023','2024_2025']:
    batch=read(ROOT/'courses'/f'ses_subquestions_{name}.json')
    assert batch['schema']=='ses-subquestion-batch-v1'
    years+=batch['years'];coverage+=batch['coverage'];batches+=batch['records']
    assert all(r['details']['scope']=='subquestion' and r['details']['exam_year'] in batch['years'] for r in batch['records'])
    recipe['records']+=batch['records'];recipe['relations']+=batch['relations']
assert sorted(years)==list(range(2019,2026))
questions=[r for r in batches if r['kind']=='question'];parents={r['parent_id'] for r in questions}
leaves=[r for r in questions if r['id'] not in parents]
assert {(r['details']['exam_year'],str(r['details']['number'])) for r in questions}=={(y,str(q)) for y in years for q in range(1,5)}
assert len(coverage)==28
assert len({(r['year'],str(r['number'])) for r in coverage})==28
for item in coverage:
    actual={r['details']['part'] for r in leaves if r['details']['exam_year']==item['year'] and str(r['details']['number'])==str(item['number'])}
    assert set(item['leaf_parts'])==actual,(item['year'],item['number'],item['leaf_parts'],actual)
recipe['subquestion_coverage']=coverage
recipe['limitations']=list(dict.fromkeys(recipe.get('limitations',[])+['Subquestion audits are agent source checks; independent expert acceptance remains pending.']))
dest=ROOT/'courses/ses_pilot_v3.json';atomic_json(dest,recipe)
store,scope=load(ROOT/'data/ses');manifest=store.manifest(scope)
pages=[Page.model_validate(p) for p in read(ROOT/'data/ses/pages.json')]
records,edges,metadata=load_pilot(dest,manifest,pages)
paired={e.source for e in edges if e.kind=='has_answer'}
checked=[r for r in records if r.kind=='question' and r.details.get('scope')=='subquestion']
checks=[c for r in checked for c in r.details['audit']['numerical_checks']]
leaf_ids={r['id'] for r in leaves};leaf_records=[r for r in checked if r.id in leaf_ids]
leaf_checks=[c for r in leaf_records for c in r.details['audit']['numerical_checks']]
report={'years':sorted(years),'whole_questions':28,'subquestions':len(checked),'leaf_subquestions':len(leaves),
    'subquestion_pairs':sum(r.id in paired for r in checked),'unpaired_subquestions':[r.id for r in checked if r.id not in paired],
    'audit_states':dict(Counter(r.details['audit']['status'] for r in checked)),
    'numerical_checks':len(checks),'numeric_comparisons':dict(Counter(c['comparison'] for c in checks)),
    'leaf_numerical_checks':len(leaf_checks),'leaf_numeric_comparisons':dict(Counter(c['comparison'] for c in leaf_checks)),
    'leaf_audit_states':dict(Counter(r.details['audit']['status'] for r in leaf_records)),
    'leaf_numerical_states':dict(Counter(r['details']['audit']['numerical_status'] for r in leaves)),
    'coverage':coverage,'expert_acceptance':'pending'}
atomic_json(QA/'ses-coverage.json',report)
config=read(ROOT/'courses/library.json');config['courses']['ses']['pilot']=dest.name
atomic_json(ROOT/'courses/library.json',config)
print(json.dumps({k:v for k,v in report.items() if k not in {'coverage','unpaired_subquestions'}},ensure_ascii=False))
