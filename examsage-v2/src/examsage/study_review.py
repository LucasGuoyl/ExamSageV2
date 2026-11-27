"""Page-level self-assessment in the downloaded student's private course."""
from pathlib import PurePosixPath

from .learning_state import LearningStore, StudentLearning, revision
from .page_image import is_original_page
from .plugin_tools import Principal
from .study_reader import _document, read_original


def _learning(desk):
    course = desk.course_id
    principal = Principal(desk.workspace.principal.subject, frozenset([course]))
    return StudentLearning(LearningStore(desk.workspace.learning_database(course)), [desk.binding], principal)


def _item(doc, number, cue, status, version):
    return {'document_id':doc.id, 'page':number, 'filename':PurePosixPath(doc.relative_path).name,
            'cue':cue, 'status':status, 'version':version}


def list_reviews(desk):
    scope = desk._current()
    docs = {doc.id:doc for doc in desk.store.manifest(scope).documents}
    items = []
    for row, record in _learning(desk).entries(desk.course_id):
        ref = record.refs[0]
        doc = docs.get(ref.document_id)
        if doc and ref.page <= doc.pages and is_original_page(record, doc.id, ref.page):
            items.append(_item(doc, ref.page, row['cue'], row['status'], revision(row)))
    desk._current()
    return {'items':sorted(items, key=lambda item:(item['filename'], item['document_id'], item['page']))}


def review_page(desk, document_id, number, *, image=False):
    scope = desk._current()
    doc = _document(desk.store, scope, {'document_id':document_id})
    return read_original(desk, scope, doc, number, '', image=image)


def save_review(desk, args):
    scope = desk._current()
    doc = _document(desk.store, scope, {'document_id':args.get('document_id')})
    number = args.get('page')
    if type(number) is not int or not 1 <= number <= doc.pages:
        raise ValueError('请选择当前课件的有效页码。')
    record_id = f'{doc.id}:p{number}'
    if not is_original_page(desk.store.get(scope, record_id), doc.id, number):
        raise ValueError('本页不在当前课程可阅读的范围内。')
    if 'version' not in args or (args['version'] is not None and not isinstance(args['version'], str)):
        raise ValueError('请重新读取这页的复习记录后保存。')
    learning = _learning(desk)
    fields = {name:args[name] for name in ('cue','status') if name in args}
    desk._current()
    saved = learning.save_recall(desk.course_id, record_id, expected_revision=args['version'], **fields)
    return _item(doc, number, saved['cue'], saved['status'], saved['revision'])
