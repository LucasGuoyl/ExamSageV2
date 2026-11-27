"""Write selected, visible source pages as a portable UTF-8 chat attachment."""
import json
import os
import re
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile

from .domain import digest, record_source_id
from .knowledge_map import extracted_text
from .plugin_tools import load_library


CONTROL_BYTES = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


def page_erratum(record, doc, reviewed_digest):
    """Return only an adopted correction evidenced entirely by this physical page."""
    note = (record.details.get('audit') or {}).get('adjudication')
    if (not reviewed_digest or not isinstance(note, dict) or digest(note) != reviewed_digest
            or note.get('category') != 'source_error' or note.get('review') != 'agent_source_checked'):
        return None
    evidence = note.get('evidence')
    if not evidence or not all((r['document_id'], r['page'], r['source_sha256'])
                               == (doc.id, record.refs[0].page, doc.sha256) for r in evidence):
        return None
    return note['summary']


def page_lines(record, source_id, erratum=None):
    status = record.details.get('extraction_status')
    label = {'text_extracted':'已提取文字','partial':'部分提取','failed':'提取失败'}.get(status,'未知')
    lines = [f'物理页 {record.refs[0].page}　来源编号 {source_id}',f'提取状态：{label}']
    if record.details.get('supplement') or record.details.get('visual_review'):
        lines.append('此页另有核查导读。此处保留原始提取，涉及公式或图表请核对原页。')
    if record.details.get('source_reviews'):
        lines.append('此页有单独保存的学习注记，可在课程阅读器中核对。')
    if erratum:
        lines.append('原页勘误（代理核查）　'+erratum)
    original = extracted_text(record)
    original,replacements = CONTROL_BYTES.subn(lambda m:f'〔U+{ord(m.group()):04X}〕',original)
    if replacements:
        lines.append('原始提取含不可显示的控制字符，已在对应位置标出编码，请核对原页。')
    if original.strip():
        # Prefix each source line so page text stays visibly distinct from the citation.
        lines.extend('│ '+line for line in original.replace('\r\n','\n').replace('\r','\n').split('\n'))
    else:
        lines.append('此页没有可用的提取文字，请核对原页。')
    return '\n'.join(lines)


def write_study_text(target, store, scope, course_id, document_ids=None):
    manifest = store.manifest(scope)
    if manifest is None:
        raise ValueError('课程快照不可用。')
    allowed = store.permitted_documents(scope)
    docs = {doc.id:doc for doc in manifest.documents if doc.id in allowed}
    selection = list(dict.fromkeys(document_ids)) if document_ids is not None else list(docs)
    if not selection or any(key not in docs for key in selection):
        raise ValueError('选中的资料不可用。')
    metadata = store.metadata(scope) or {}
    reviewed_digest = None if scope.strict_history else metadata.get('page_erratum_digest')
    profile = metadata.get('course_profile') or {}
    label = '开发演示资料' if profile.get('material_status')=='demonstration' else '课程资料'
    def quoted(value):
        return json.dumps(value,ensure_ascii=False)
    target.write(f'押题宝 · {label}\n课程：{quoted(manifest.course_name)}\n课程编号：{quoted(course_id)}\n'
                 f'快照：{scope.snapshot}\n已选文件：{len(selection)}\n\n')
    target.write('本文件收录当前范围内可见原页的提取文字，页号按原文件物理顺序。引用时请给出文件名、页码和来源编号。'
                 '图表、公式版式、题答对应、冲突核查与解题导读请回到原课件或押题宝核对。'
                 '带 │ 的行是课件内容。\n')
    visible = 0
    for key in selection:
        doc = docs[key]
        offset = 0
        while True:
            total, rows = store.original_page_slice(scope,offset,64,document_id=key)
            if offset == 0:
                target.write(f'\n文件：{quoted(PurePosixPath(doc.relative_path).name)}\n'
                             f'文档编号：{quoted(doc.id)}　类型：{doc.kind}\n'
                             f'文件 SHA256：{doc.sha256}\n可见原页：{total} / {doc.pages}\n')
            for record in rows:
                if not 1 <= record.refs[0].page <= doc.pages:
                    raise ValueError('原页超出文档的物理页数。')
                sid = record_source_id(course_id,scope,digest(record.model_dump(mode='json')))
                target.write('\n'+page_lines(record,sid,page_erratum(record,doc,reviewed_digest))+'\n')
            visible += len(rows)
            offset += len(rows)
            if offset >= total:
                break
            if not rows:
                raise ValueError('课程原页读取不完整。')
    if not visible:
        raise ValueError('所选资料没有可导出的可见原页。')
    return visible


def export_study_file(library,course_id,document_ids,output):
    def current_course():
        return load_library(library,[course_id])._course(course_id)

    binding,store = current_course()
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise FileExistsError('请选择新的输出文件。')
    with NamedTemporaryFile(dir=output.parent,mode='w',encoding='utf-8',newline='\n',delete=False) as tmp:
        staged = Path(tmp.name)
    try:
        with staged.open('w',encoding='utf-8',newline='\n') as target:
            pages = write_study_text(target,store,binding.scope,course_id,document_ids)
        latest,_ = current_course()
        if latest != binding:
            raise ValueError('导出期间课程登记或资料范围发生变化，请重新选择资料。')
        # Both operations publish the complete file and refuse to replace an existing target.
        if os.name=='nt':
            staged.rename(output)
        else:
            os.link(staged,output)
    finally:
        staged.unlink(missing_ok=True)
    return {'output':str(output),'visible_pages':pages,'snapshot':binding.scope.snapshot,'model_called':False}
