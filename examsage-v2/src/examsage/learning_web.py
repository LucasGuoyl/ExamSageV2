"""Personal study progress on student-hosted course pages."""
import sqlite3
from fastapi import HTTPException, Request
from pydantic import Field

from .domain import digest, record_source_id
from .learning_state import ProgressConflict, ProgressUpdate
from .page_image import is_original_page


class PageUpdate(ProgressUpdate):
    source_id: str = Field(pattern=r'^src_[0-9a-f]{64}$')
    revision: str | None = Field(pattern=r'^[0-9a-f]{64}$')


def install_learning(app, course_id, current_scope, cited_page, store, open_learning):
    def personal():
        scope = current_scope()
        try:
            learning = open_learning(course_id,scope)
        except (ValueError, OSError, sqlite3.DatabaseError) as error:
            raise HTTPException(409,'课程或个人学习库暂不可用，请重新打开课程。') from error
        return scope, learning

    @app.get('/api/learning')
    def progress():
        scope, learning = personal()
        docs = {d.id:d for d in store.manifest(scope).documents}
        pages = []
        for row, record in learning.entries(course_id):
            ref = record.refs[0]
            if is_original_page(record,ref.document_id,ref.page):
                pages.append({'document_id':ref.document_id, 'page':ref.page,
                              'filename':docs[ref.document_id].relative_path,
                              'source_id':record_source_id(course_id,scope,digest(record.model_dump(mode='json'))),
                              'status':row['status'], 'updated_at':row['updated_at']})
        pages.sort(key=lambda page:page['updated_at'], reverse=True)
        return {'snapshot':scope.snapshot, 'pages':pages}

    @app.get('/api/learning/{doc_id}/{page}')
    def read(doc_id: str, page: int, source_id: str):
        _, learning = personal()
        record, _ = cited_page(doc_id,page,source_id)
        return learning.get(course_id,record.id)

    @app.put('/api/learning/{doc_id}/{page}')
    def write(doc_id: str, page: int, update: PageUpdate, request: Request):
        origin = f'{request.url.scheme}://{request.url.netloc}'
        if (request.headers.get('origin') != origin or request.headers.get('sec-fetch-site') == 'cross-site'
                or request.headers.get('content-type','').split(';')[0].lower() != 'application/json'):
            raise HTTPException(403,'请从本机学生课程页保存复习记录。')
        _, learning = personal()
        record, _ = cited_page(doc_id,page,update.source_id)
        try:
            return learning.save(course_id,record.id,update.status,update.note,expected_revision=update.revision)
        except ProgressConflict as error:
            raise HTTPException(409,str(error)) from error
