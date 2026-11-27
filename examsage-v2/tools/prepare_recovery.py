from pathlib import Path
from collections import Counter
import json
ROOT=Path(__file__).resolve().parents[1];PREV=ROOT/'data/qa/low-text-20261028';OUT=ROOT/'data/qa/recovery-ses-20261102'
OUT.mkdir(parents=True,exist_ok=True)
rows=[]
for row in json.loads((PREV/'inventory.json').read_text(encoding='utf-8')):
    ocr=json.loads((PREV/'ocr-en'/row['course']/f"{row['document_id']}-p{row['number']}.json").read_text(encoding='utf-8'))
    if ocr['mean_confidence']>=70:continue
    recipe=json.loads((ROOT/'courses'/f"{row['course']}_page_supplements.json").read_text(encoding='utf-8'))
    audit=next(p for p in recipe['documents'][row['source_sha256']]['pages'] if p['number']==row['number'])
    rows.append({**row,'ocr':ocr,'previous_audit':audit})
assert len(rows)==74
(OUT/'inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'total':len(rows),'courses':dict(Counter(r['course'] for r in rows)),
 'documents':dict(Counter(r['course']+' '+r['document_id']+' '+r['relative_path'] for r in rows))},ensure_ascii=False,indent=2))
