"""Source-bound visual descriptions and offline OCR, never replacements for native text."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from PIL import Image
from .domain import Document, Page, SourceRef
from .adjudication import validate_adjudication, adjudication_text


def _inside(root: Path, relative: str) -> Path:
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Supplement image escapes root')
    return path

def validate_recovery(recovery: dict, document_id: str, number: int) -> None:
    if recovery.get('schema')!='page-recovery-v1' or recovery.get('review')!='agent_source_checked':
        raise ValueError('Invalid recovery schema/review')
    if recovery.get('status') not in {'source_transcribed','diagram_described','partially_legible'}:
        raise ValueError('Invalid recovery status')
    blocks=recovery.get('blocks');unresolved=recovery.get('unresolved')
    if not isinstance(blocks,list) or not blocks:raise ValueError('Recovery blocks required')
    if not isinstance(unresolved,list) or any(not isinstance(x,str) or not x.strip() for x in unresolved):
        raise ValueError('Recovery unresolved list required')
    if bool(unresolved)!=(recovery['status']=='partially_legible'):
        raise ValueError('Recovery uncertainty must remain explicit')
    for block in blocks:
        if block.get('kind') not in {'text','equation','diagram','table'} or not isinstance(block.get('text'),str) or not block['text'].strip():
            raise ValueError('Invalid recovery block')
        if 'latex' in block and (not isinstance(block['latex'],str) or not block['latex'].strip()):
            raise ValueError('Invalid recovery formula')
        if 'bbox' in block:SourceRef(document_id=document_id,page=number,bbox=block['bbox'])


def apply_supplements(doc: Document, pages: list[Page], folder: Path, assets: Path) -> list[Page]:
    path=folder/(doc.sha256+'.json')
    if not path.exists():return pages
    package=json.loads(path.read_text(encoding='utf-8'))
    if package.get('schema')!='page-supplements-v1' or package.get('source_sha256')!=doc.sha256:
        raise ValueError('Supplement source/schema mismatch')
    copied=[p.model_copy(deep=True) for p in pages];by_number={p.number:p for p in copied};seen=set()
    for item in package['pages']:
        number=item['number'];page=by_number.get(number)
        if number in seen or page is None or page.hidden:raise ValueError('Invalid supplement page')
        seen.add(number)
        if sha256(page.text.encode('utf-8')).hexdigest()!=item['native_text_sha256']:
            raise ValueError('Supplement native text mismatch')
        image=_inside(folder,item['image']);image_hash=item['render_sha256']
        if sha256(image.read_bytes()).hexdigest()!=image_hash:raise ValueError('Supplement image mismatch')
        with Image.open(image) as bitmap:
            if bitmap.format!='PNG':raise ValueError('Supplement image must be PNG')
            width,height=bitmap.size
            bitmap.verify()
        audit=deepcopy(item['audit']);ocr=deepcopy(item['ocr'])
        if audit['number']!=number or audit['render_sha256']!=image_hash:
            raise ValueError('Audit image/page mismatch')
        if audit['category'] not in {'text','diagram','mixed','blank'} or not str(audit['summary']).strip():
            raise ValueError('Audit needs a page category and summary')
        if ocr.get('schema')!='page-ocr-v1' or ocr.get('status')!='recognized' or ocr.get('number')!=number:
            raise ValueError('OCR result incomplete')
        if ocr.get('source_sha256')!=doc.sha256 or ocr.get('render_sha256')!=image_hash:
            raise ValueError('OCR source/image mismatch')
        for word in ocr.get('words',[]):
            SourceRef(document_id=doc.id,page=number,bbox=word['bbox'])
            if not 0<=word.get('confidence',0)<=100:raise ValueError('Invalid OCR confidence')
        confidence=ocr.get('mean_confidence',0)
        if not isinstance(confidence,(int,float)) or not 0<=confidence<=100:raise ValueError('Invalid OCR mean confidence')
        ocr['review']='machine_checked'
        category=audit['category']
        recovery=audit.get('recovery')
        if recovery:
            validate_recovery(recovery,doc.id,number)
            if recovery.get('adjudication'):
                validate_adjudication(recovery['adjudication'],{doc.id:doc},{(doc.id,p.number) for p in pages if not p.hidden},{doc.id:doc.sha256})
        if category=='blank' and (audit.get('transcription') or audit.get('formulas')):
            raise ValueError('Blank page cannot have a transcription or formulas')
        relative='supplements/'+image_hash+'.png';dest=assets/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and sha256(dest.read_bytes()).hexdigest()!=image_hash:raise ValueError('Immutable supplement image corrupted')
        if not dest.exists():dest.write_bytes(image.read_bytes())
        page.supplement={'source_sha256':doc.sha256,'render_sha256':image_hash,'image_asset':relative,
                         'width':width,'height':height,'audit':audit,'ocr':ocr,
                         'review':'agent_source_checked','review_scope':'page_category_and_key_content',
                         'expert_acceptance':'pending','ocr_indexed':category!='blank' and confidence>=70,
                         'resolution':'blank_confirmed' if category=='blank' else 'text_transcribed' if audit.get('transcription') else 'source_described'}
        if recovery:page.supplement['recovery_status']=recovery['status']
        page.assets=list(dict.fromkeys(page.assets+[relative]))
        page.issues.append('Source image has a separate agent description; OCR remains unverified machine text.')
    return copied


def supplemental_text(supplement: dict) -> str:
    audit=supplement['audit']
    text='\n[原页补充导读 · 非官方答案]\n'+audit['summary']
    if audit.get('transcription'):text+='\n[代理核对转录]\n'+audit['transcription']
    text+=''.join('\n\\('+formula+'\\)' for formula in audit.get('formulas',[]))
    text+=''.join('\n核查注记：'+warning for warning in audit.get('warnings',[]))
    if audit.get('recovery'):
        recovery=audit['recovery'];text+='\n[低置信度页面内容复核 · 原始 OCR 保持不变]'
        for block in recovery['blocks']:
            text+='\n'+block['text']
            if block.get('latex'):text+='\n\\('+block['latex']+'\\)'
        text+=''.join('\n仍需核对：'+note for note in recovery['unresolved'])
        if recovery.get('adjudication'):text+=adjudication_text(recovery['adjudication'])
    if supplement.get('ocr_indexed'):text+='\n[OCR 自动识别候选 · 公式与数值未核验]\n'+supplement['ocr']['text']
    return text


def validated_supplement_asset(doc: Document, details: dict, assets: Path) -> Path | None:
    item=details.get('supplement')
    if not item or item.get('source_sha256')!=doc.sha256:return None
    try:
        path=_inside(assets,item['image_asset'])
        return path if path.suffix.lower()=='.png' and sha256(path.read_bytes()).hexdigest()==item['render_sha256'] else None
    except (ValueError,KeyError,OSError):return None
