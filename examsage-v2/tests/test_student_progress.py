"""Student routes reuse the current authorized page and persist only personal self-reports."""
import json
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from examsage.chat_runner import ChatRunner
from examsage.domain import Record, Scope, SourceRef
from examsage.student_web import create_student_app
from test_chat_api import routes
from test_core import example
from test_student_web import local_upload, mount, student


@pytest.fixture
def library(tmp_path):
    folder = tmp_path/'shared'
    db, manifest, _ = example(folder)
    record = Record(id='doc:p1',kind='block',title='First page',text='Visible conditions.',
                    refs=[SourceRef(document_id='doc',page=1)])
    sid = db.publish('school',manifest,[record],[],{})
    scope = Scope(workspace='school',course=manifest.course_key,snapshot=sid,allowed_sources=['doc'])
    (folder/'current.json').write_text(scope.model_dump_json(),encoding='utf8')
    (tmp_path/'library.json').write_text(json.dumps({'courses':[{'slug':'common','data':'shared'}]}))
    return folder, db, manifest, record, scope


@contextmanager
def session(default, ws):
    runner=ChatRunner(ws.chats,runtime=object())
    try:
        yield create_student_app(default,ws,chat_runner=runner)
    finally:
        runner.close()


def route(app,path,method='GET'):
    result=next((r for r in routes(app) if getattr(r,'path',None)==path and method in r.methods),None)
    assert result is not None, f'Missing student operation {method} {path}'
    return result.endpoint


def request(origin='http://127.0.0.1:8769'):
    return Request({'type':'http','method':'PUT','scheme':'http','path':'/courses/common/api/learning/doc/1',
        'client':('127.0.0.1',3456),'server':('127.0.0.1',8769),'headers':[(b'host',b'127.0.0.1:8769'),
        (b'origin',origin.encode()),(b'content-type',b'application/json')]})


PAGE='/api/learning/{doc_id}/{page}'


def save(app,doc,page,sid,revision,note,status='review',origin='http://127.0.0.1:8769'):
    from examsage.learning_web import PageUpdate
    return route(app,PAGE,'PUT')(doc,page,PageUpdate(source_id=sid,revision=revision,status=status,note=note),request(origin))


def test_students_reopen_their_own_review_page_without_changing_shared_content(library,tmp_path):
    default,db,_,_,scope=library
    alice=student(tmp_path/'people','first',['common'])
    bob=student(tmp_path/'people','second',['common'])
    with session(default,alice) as aa,session(default,bob) as bb:
        a,b=mount(aa,'/courses/common'),mount(bb,'/courses/common')
        read=route(a,PAGE)
        page=route(a,'/api/page/{doc_id}/{number}')('doc',1,None,None)
        sid=page['learning_source_id']
        assert read('doc',1,sid)['revision'] is None
        saved=save(a,'doc',1,sid,None,'核对水力梯度')
        assert saved['revision'] and route(b,PAGE)('doc',1,sid)['note']==''
        assert route(b,'/api/learning')()['pages']==[]
        with pytest.raises(HTTPException) as conflict:
            save(a,'doc',1,sid,None,'旧标签页')
        assert conflict.value.status_code==409
        with pytest.raises(HTTPException) as cross:
            save(a,'doc',1,sid,saved['revision'],'另一来源','confident','https://another.example')
        assert cross.value.status_code==403
        original=db.get(scope,'doc:p1')
        assert original.text=='Visible conditions.' and '核对水力梯度' not in original.model_dump_json()
    with session(default,alice) as reopened:
        course=mount(reopened,'/courses/common')
        row,=route(course,'/api/learning')()['pages']
        assert (row['document_id'],row['page'],row['source_id'],row['status'])==('doc',1,sid,'review')
        restored=route(course,PAGE)('doc',1,sid)
        assert restored['note']=='核对水力梯度' and restored['revision']==saved['revision']
        save(course,'doc',1,sid,restored['revision'],'已推导','confident')
        assert route(course,PAGE)('doc',1,sid)['status']=='confident'


def test_scope_change_refuses_old_save_and_refresh_reads_new_edition(library,tmp_path):
    default,db,manifest,record,scope=library
    ws=student(tmp_path/'people','first',['common'])
    with session(default,ws) as app:
        course=mount(app,'/courses/common')
        route(course,PAGE)
        old=route(course,'/api/page/{doc_id}/{number}')('doc',1,None,None)['learning_source_id']
        save(course,'doc',1,old,None,'第一版')
        new=db.publish('school',manifest,[record],[],{'edition':2})
        (default/'current.json').write_text(scope.model_copy(update={'snapshot':new}).model_dump_json())
        with pytest.raises(HTTPException): route(course,'/api/learning')()
        current=mount(app,'/courses/common')
        assert route(current,'/api/learning')()['pages']==[]
        with pytest.raises(HTTPException) as stale:save(current,'doc',1,old,None,'过期')
        assert stale.value.status_code==409
        student(ws.root,'first',[]).remember_public_grants()
        with pytest.raises(HTTPException): route(current,'/api/learning')()


def test_archive_view_has_no_personal_write_entry(library):
    from examsage.api import create_app
    app=create_app(library[0],course_id='common')
    assert not any(getattr(r,'path','').startswith('/api/learning') for r in routes(app))

def test_two_authorized_offerings_of_same_book_keep_separate_notes(library,tmp_path):
    default,_,_,_,_=library
    catalog=default.parent/'library.json'
    catalog.write_text(json.dumps({'courses':[{'slug':slug,'data':'shared'} for slug in ('autumn','spring')]}))
    ws=student(tmp_path/'people','student',['autumn','spring'])
    with session(default,ws) as app:
        autumn=mount(app,'/courses/autumn')
        spring=mount(app,'/courses/spring')
        one=route(autumn,'/api/page/{doc_id}/{number}')('doc',1,None,None)['learning_source_id']
        two=route(spring,'/api/page/{doc_id}/{number}')('doc',1,None,None)['learning_source_id']
        save(autumn,'doc',1,one,None,'秋季复习任务')
        student(ws.root,'student',['spring']).remember_public_grants()
        assert route(spring,PAGE)('doc',1,two)['note']==''
        assert route(spring,'/api/learning')()['pages']==[]


def test_lost_response_retry_preserves_original_review_time(tmp_path):
    import sqlite3
    from test_learning_state import setup
    learning,rid=setup(tmp_path)
    saved=learning.save('physics',rid,'review','same',expected_revision=None)
    with sqlite3.connect(tmp_path/'learning.sqlite3') as conn:
        conn.execute("UPDATE learning_progress SET updated_at='2025-01-01 12:00:00'")
    assert learning.save('physics',rid,'review','same',expected_revision=None)['revision']==saved['revision']
    assert learning.list('physics')[0]['updated_at']=='2025-01-01 12:00:00'

def test_imported_course_mount_persists_notes_only_for_its_owner(library,tmp_path,monkeypatch):
    from examsage import api
    from examsage.student_workspace import student_tools

    # Observe which real course app the authorized ASGI upload mount dispatches to.
    # Intercept only its final transport so this test needs no local socket.
    create=api.create_app
    dispatched=[]
    def capture(*args,**kwargs):
        course=create(*args,**kwargs)
        async def receiver(scope,receive,send):
            dispatched.append(course)
        return receiver
    monkeypatch.setattr(api,'create_app',capture)

    def dispatch(app,receipt):
        private='/courses/upload-{batch_id:uuid}'
        mounted=next(r.app for r in app.routes if getattr(r,'path','')==private)
        scope={**request().scope,'method':'GET','path':receipt['study_url'],'path_params':{'batch_id':receipt['id']}}
        events=[]
        async def send(event):
            events.append(event)
        dispatched.clear()
        operation=mounted(scope,None,send)
        with pytest.raises(StopIteration):
            operation.send(None)
        if dispatched:
            return dispatched[0]
        assert next(e['status'] for e in events if e['type']=='http.response.start') in {404,409}
        return None

    default=library[0]
    a,b=[student(tmp_path/'people',name,[]) for name in ('owner-a','owner-b')]
    receipts=[local_upload(w,'同一份文本。') for w in (a,b)]
    with session(default,a) as aa, session(default,b) as bb:
        for app,ws,own,peer in ((aa,a,receipts[0],receipts[1]),(bb,b,receipts[1],receipts[0])):
            course=dispatch(app,own)
            assert route(course,'/api/learning')()['pages']==[]
            binding,db=student_tools(None,ws)._course('upload-'+own['id'])
            doc=db.manifest(binding.scope).documents[0].id
            sid=route(course,'/api/page/{doc_id}/{number}')(doc,1,None,None)['learning_source_id']
            save(course,doc,1,sid,None,'私课 '+own['id'])
            assert dispatch(app,peer) is None
            assert route(dispatch(app,own),PAGE)(doc,1,sid)['note']=='私课 '+own['id']
