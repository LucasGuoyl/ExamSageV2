"""Resolve a citation from the selected conversation into the original course page."""
from pathlib import PurePosixPath

from .chat_store import ChatNotFound
from .knowledge_map import extracted_text
from .page_image import is_original_page, source_image


def _document(store, scope, ref):
    manifest = store.manifest(scope)
    allowed = store.permitted_documents(scope)
    docs = [doc for doc in manifest.documents if doc.id in allowed] if manifest else []
    if 'document_id' in ref:
        docs = [doc for doc in docs if doc.id == ref['document_id']]
    if 'filename' in ref or 'document_id' not in ref:
        # A basename alone is sufficient only when unique in this saved scope.
        docs = [doc for doc in docs if PurePosixPath(doc.relative_path).name == ref.get('filename')]
    if len(docs) != 1 or ('sha256' in ref and ref['sha256'] != docs[0].sha256):
        raise ValueError('当前课程无法核对这份引用文件。')
    return docs[0]


def completed_answer(desk, run_id):
    """Bind a saved answer to the open conversation before resolving any of its sources."""
    scope = desk._current()
    if not isinstance(run_id, str) or not desk.session_id:
        raise ValueError('请先选择一条已完成的回答。')
    try:
        run = desk.runner.store.get_run(scope, run_id)
    except ChatNotFound:
        raise ValueError('当前对话中找不到这条引用。') from None
    if run['session_id'] != desk.session_id or run['status'] != 'completed':
        raise ValueError('请选择当前对话中已完成回答的引用。')
    return scope, run['answer'] or {}


def read_citation(desk, run_id, evidence_id, ref_index=0, *, page=None, image=False):
    """Read the cited page or an authorized page of that same document, without inference."""
    scope, answer = completed_answer(desk, run_id)
    evidence = next((e for e in answer.get('evidence', [])
                     if isinstance(e, dict) and e.get('id') == evidence_id), None)
    if evidence is None or evidence.get('snapshot', scope.snapshot) != scope.snapshot:
        raise ValueError('当前课程版本中找不到这条引用。')
    refs = evidence.get('refs')
    if (not isinstance(refs, list) or type(ref_index) is not int or not 0 <= ref_index < len(refs)
            or not isinstance(refs[ref_index], dict)):
        raise ValueError('请选择这条引用中的有效页码。')
    ref = refs[ref_index]
    doc = _document(desk.store, scope, ref)
    quote = '' if evidence.get('kind') in {'calculation','exam_topic'} else evidence.get('text')
    return read_original(desk, scope, doc, ref.get('page'), quote, page=page, image=image)


def read_original(desk, scope, doc, cited_page, quote, *, page=None, image=False):
    """Render a document already resolved within the current, authorized conversation."""
    session, course, store = desk.session_id, desk.course_id, desk.store
    def original(number):
        if type(number) is int and 1 <= number <= doc.pages:
            record = store.get(scope, f'{doc.id}:p{number}')
            if is_original_page(record, doc.id, number):
                return record
        return None

    cited = original(cited_page)
    if cited is None:
        raise ValueError('当前课程无法读取这条引用的原页。')
    number = cited_page if page is None else page
    record = cited if type(number) is int and number == cited_page else original(number)
    if record is None:
        raise ValueError('本页不在当前课程可阅读的范围内。')
    text = extracted_text(record)
    highlight = quote if number == cited_page and isinstance(quote,str) and quote.strip() and quote in text else ''
    filename = PurePosixPath(doc.relative_path).name
    result = {'document_id':doc.id, 'filename':filename, 'page':number, 'pages':doc.pages, 'cited_page':cited_page,
              'text':text, 'highlight':highlight, 'can_previous':original(number-1) is not None,
              'can_next':original(number+1) is not None,
              'image_supported':PurePosixPath(filename).suffix.lower() in {'.pdf','.pptx'}}
    if image:
        metadata, png = source_image(store.path, doc, record, number)
        result.update(png=png, image_reason=metadata.get('reason'))
    if desk._current() != scope or desk.session_id != session or desk.course_id != course:
        raise ValueError('课程或对话已切换，请重新打开引用。')
    return result
