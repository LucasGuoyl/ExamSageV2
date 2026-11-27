"""Freeze the prior release's exact unresolved/flagged scope, never overwrite it."""
from pathlib import Path
import json
from examsage.cli import load
from examsage.ingest import atomic_json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/adjudication-20261102'
old=ROOT/'data/qa/recovery-ses-20261102'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
    dest=QA/'baseline.json'
    if dest.exists():raise FileExistsError('Adjudication baseline is immutable')
    store,scope=load(ROOT/'data/releases/library-v0.3-20261102/ses')
    questions=[r for r in store.list_records(scope,'question') if r.details.get('audit')]
    parents={r.parent_id for r in questions};leaves=[r for r in questions if r.id not in parents]
    conflicts=[r.model_dump(mode='json') for r in leaves if r.details['audit']['status']=='source_conflict']
    gaps=[r.model_dump(mode='json') for r in leaves if r.details['audit']['status']=='partial']
    unresolved=read(old/'recovery-coverage.json')['unresolved_pages']
    pages=[]
    for row in read(old/'inventory.json'):
        if not any(r['document_id']==row['document_id'] and r['number']==row['number'] for r in unresolved):continue
        ps,sc=load(ROOT/'data'/row['course']);block=ps.get(sc,f"{row['document_id']}:p{row['number']}")
        pages.append({**row,'current_recovery':block.details['supplement']['audit']['recovery']})
    assert len(conflicts)==46 and len(gaps)==3 and len(pages)==5
    atomic_json(dest,{'schema':'adjudication-baseline-v1','source_release':'library-v0.3-20261102','ses_snapshot':scope.snapshot,'pages':pages,'gaps':gaps,'conflicts':conflicts})
    print({'pages':len(pages),'gaps':len(gaps),'conflicts':len(conflicts)})
if __name__=='__main__':main()
