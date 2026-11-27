"""Prepare the audited low-native-text page inventory and images for offline review."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
import pypdfium2 as pdfium
from PIL import Image, ImageOps, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/qa/low-text-20261028'
OUT.mkdir(parents=True,exist_ok=True)
rows=[]
for slug in ['geodynamics','planetary_science','sea_level','ses']:
    data=ROOT/'data'/slug
    manifest=json.loads((data/'manifest.json').read_text(encoding='utf-8'))
    docs={d['id']:d for d in manifest['documents']}
    pages=json.loads((data/'pages.json').read_text(encoding='utf-8'))
    for page in pages:
        if len(page['text'].strip())>=30:continue
        doc=docs[page['document_id']];source=data/'assets'/doc['asset']
        assert sha256(source.read_bytes()).hexdigest()==doc['sha256']
        name=f"{doc['id']}-p{page['number']}.png"
        dest=OUT/'pages'/slug/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if not dest.exists():
            if doc['relative_path'].lower().endswith('.pdf'):
                with pdfium.PdfDocument(source) as pdf:
                    p=pdf[page['number']-1];scale=2400/max(p.get_size())
                    bitmap=p.render(scale=scale);bitmap.to_pil().save(dest);bitmap.close();p.close()
            else:
                if not page.get('render'):raise ValueError('PPTX needs complete native render first')
                dest.write_bytes((data/'assets'/page['render']['asset']).read_bytes())
        with Image.open(dest) as image:width,height=image.size
        rows.append({'course':slug,'document_id':doc['id'],'source_sha256':doc['sha256'],
            'number':page['number'],'relative_path':doc['relative_path'],'native_text':page['text'],
            'image':str(dest.resolve()),'render_sha256':sha256(dest.read_bytes()).hexdigest(),
            'width':width,'height':height})
(OUT/'inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
for slug in ['geodynamics','planetary_science','sea_level','ses']:
    subset=[r for r in rows if r['course']==slug]
    for start in range(0,len(subset),4):
        sheet=Image.new('RGB',(2200,1720),'#dddddd');draw=ImageDraw.Draw(sheet)
        for i,r in enumerate(subset[start:start+4]):
            x=(i%2)*1100;y=(i//2)*860
            draw.text((x+14,y+8),f"{slug} #{start+i+1} | {r['document_id'][-8:]} p{r['number']}",font=font,fill='black')
            with Image.open(r['image']) as original:
                image=ImageOps.contain(original.convert('RGB'),(1080,810))
                sheet.paste(image,(x+(1100-image.width)//2,y+42+(810-image.height)//2))
        destination=OUT/'sheets'/f'{slug}-{start+1:03}.jpg';destination.parent.mkdir(exist_ok=True)
        sheet.save(destination,quality=92)
print(json.dumps({'total':len(rows),'courses':dict(Counter(r['course'] for r in rows))}))
