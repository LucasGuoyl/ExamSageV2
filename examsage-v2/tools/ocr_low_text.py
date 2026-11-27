"""Offline English OCR; results remain machine candidates, separate from visual audit."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import sys
import os
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data/tooling/tesserocr'))
import tesserocr

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--limit',type=int,default=0)
args=parser.parse_args()
qa=ROOT/'data/qa/low-text-20261028'
inventory=json.loads((qa/'inventory.json').read_text(encoding='utf-8'))
if args.limit:inventory=inventory[:args.limit]
model=ROOT/'data/tooling/tessdata/eng.traineddata'
assert sha256(model.read_bytes()).hexdigest()=='7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'
os.chdir(ROOT)
# The native Windows library does not reliably open a Unicode tessdata path.
with tesserocr.PyTessBaseAPI(path='data/tooling/tessdata',lang='eng',psm=tesserocr.PSM.AUTO) as api:
    for i,entry in enumerate(inventory,1):
        dest=qa/'ocr-en'/entry['course']/f"{entry['document_id']}-p{entry['number']}.json"
        if dest.exists():continue
        image=Path(entry['image']);assert sha256(image.read_bytes()).hexdigest()==entry['render_sha256']
        with Image.open(image) as bitmap:
            api.SetPageSegMode(tesserocr.PSM.AUTO);api.SetImage(bitmap);api.Recognize()
            text=api.GetUTF8Text().strip();mode='auto'
            if len(text)<12:
                api.SetPageSegMode(tesserocr.PSM.SPARSE_TEXT);api.Recognize();text=api.GetUTF8Text().strip();mode='sparse'
            words=[];iterator=api.GetIterator()
            if iterator:
                for result in tesserocr.iterate_level(iterator,tesserocr.RIL.WORD):
                    try:
                        word=result.GetUTF8Text(tesserocr.RIL.WORD);box=result.BoundingBox(tesserocr.RIL.WORD)
                    except RuntimeError:
                        continue  # A graphics-only iterator element can have no text.
                    if not word or not box:continue
                    x0,y0,x1,y1=box
                    words.append({'text':word,'confidence':round(result.Confidence(tesserocr.RIL.WORD),2),
                                  'bbox':[x0/bitmap.width,y0/bitmap.height,x1/bitmap.width,y1/bitmap.height]})
            record={'schema':'page-ocr-v1','number':entry['number'],'source_sha256':entry['source_sha256'],
                    'render_sha256':entry['render_sha256'],'engine':'Tesseract 5.5.3 / tesserocr 2.12.0',
                    'language':'eng','model_sha256':sha256(model.read_bytes()).hexdigest(),
                    'status':'recognized','segmentation':mode,'text':text,'words':words,
                    'mean_confidence':api.MeanTextConf(),'review':'machine_checked'}
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        if i%20==0 or args.limit:print(f'OCR {i}/{len(inventory)}',flush=True)
print(f'English OCR complete: {len(inventory)} pages',flush=True)
