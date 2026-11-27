"""Bind the exact visual audit inventory to offline OCR without changing sources."""
from pathlib import Path
from collections import Counter, defaultdict
from hashlib import sha256
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'data/qa/low-text-20261028'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    inventory=read(QA/'inventory.json');assert len(inventory)==208
    prepared=[];report={}
    for slug,count in {'geodynamics':72,'planetary_science':67,'sea_level':50,'ses':19}.items():
        recipe=read(ROOT/'courses'/f'{slug}_page_supplements.json')
        audits={(sha,p['number']):p for sha,d in recipe['documents'].items() for p in d['pages']}
        rows=[r for r in inventory if r['course']==slug]
        assert len(rows)==count and len(audits)==count
        assert set(audits)=={(r['source_sha256'],r['number']) for r in rows}
        packages=defaultdict(list)
        for row in rows:
            audit=audits[row['source_sha256'],row['number']]
            assert audit['render_sha256']==row['render_sha256']
            image=Path(row['image']);assert sha256(image.read_bytes()).hexdigest()==row['render_sha256']
            ocr=read(QA/'ocr-en'/slug/f"{row['document_id']}-p{row['number']}.json")
            assert ocr['source_sha256']==row['source_sha256'] and ocr['render_sha256']==row['render_sha256']
            relative='images/'+row['render_sha256']+'.png'
            item={'number':row['number'],'render_sha256':row['render_sha256'],'image':relative,
                'native_text_sha256':sha256(row['native_text'].encode()).hexdigest(),'ocr':ocr,'audit':audit}
            packages[row['source_sha256']].append(item)
            prepared.append((image,ROOT/'data'/slug/'page-supplements'/relative))
        for sha,pages in packages.items():
            prepared.append(({'schema':'page-supplements-v1','source_sha256':sha,'pages':pages},
                ROOT/'data'/slug/'page-supplements'/(sha+'.json')))
        report[slug]={'pages':count,'categories':dict(Counter(a['category'] for a in audits.values())),
            'ocr_indexed':sum(p['ocr']['mean_confidence']>=70 and p['audit']['category']!='blank' for ps in packages.values() for p in ps)}
    for value,path in prepared:
        if isinstance(value,dict):write(path,value)
        else:
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(value,path)
    write(QA/'coverage.json',{'total':208,'courses':report,'expert_acceptance':'pending',
        'scope':'Page category and key content reviewed against source images; OCR confidence is not accuracy.'})
    print(json.dumps(report))
if __name__=='__main__':main()
