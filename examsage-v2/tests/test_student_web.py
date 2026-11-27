"""Student-bound course menus and chat, through the normal registered route handlers."""
from io import BytesIO
import json
from pathlib import Path

import pytest

from examsage.chat_api import NewSession
from examsage.chat_runner import ChatRunner
from examsage.domain import Scope
from examsage.plugin_tools import Principal
from examsage.web_intake import import_selection
from test_chat_api import endpoint, routes
from test_core import example


def public_library(tmp_path):
    entries = []
    for slug in ('common', 'optional'):
        folder = tmp_path / slug
        store, manifest, record = example(folder)
        manifest.course_key = slug
        snapshot = store.publish('public',manifest,[record],[],{})
        scope = Scope(workspace='public',course=slug,snapshot=snapshot,allowed_sources=['doc'])
        (folder/'current.json').write_text(scope.model_dump_json(), encoding='utf-8')
        entries.append({'slug':slug, 'name':slug, 'data':slug})
    (tmp_path/'library.json').write_text(json.dumps({'courses':entries}), encoding='utf-8')
    return tmp_path/'common'


def student(root, subject, public):
    from examsage.student_workspace import StudentWorkspace
    return StudentWorkspace(root, Principal(subject, frozenset(public)))


def local_upload(workspace, text):
    return import_selection(workspace.imports, '同名私课', '数学', [('讲义.txt', BytesIO(text.encode()))])


def mount(app, name):
    target = next(route.app for route in app.routes if getattr(route, 'path', '') == name)
    return target.current_app() if hasattr(target,'current_app') else target


def read_course_route(app, path, *args):
    """Run the route's registered scope dependency and its synchronous handler."""
    route = next(r for r in routes(app) if getattr(r,'path','') == path)
    for dependency in route.dependant.dependencies:
        if dependency.call.__name__ == 'current_scope':
            dependency.call()
    return route.endpoint(*args)


def test_scoped_menu_and_shared_course_history_survive_reopening(tmp_path):
    from examsage.student_web import create_student_app
    default = public_library(tmp_path)
    root = tmp_path/'users'
    a = student(root,'student-a',['common'])
    b = student(root,'student-b',['common','optional'])
    ar, br = ChatRunner(a.chats, runtime=object()), ChatRunner(b.chats, runtime=object())
    try:
        alice = create_student_app(default, a, chat_runner=ar)
        bob = create_student_app(default, b, chat_runner=br)
        ac = mount(alice, '/courses/common')
        bc = mount(bob, '/courses/common')
        alice_menu = endpoint(ac,'/api/courses')
        assert [e['slug'] for e in alice_menu()] == ['common']
        assert {e['slug'] for e in endpoint(bc,'/api/courses')()} == {'common','optional'}
        assert not any(getattr(r,'path','')=='/courses/optional' for r in alice.routes)
        a1 = local_upload(a,'甲的第一个学期')
        a2 = local_upload(a,'甲的第二个学期')
        b1 = local_upload(b,'乙的第一个学期')
        updated = alice_menu()
        assert {e['url'] for e in updated} == {'/courses/common/', a1['study_url'], a2['study_url']}
        assert len({e['name'] for e in updated if e['name'].startswith('同名私课')}) == 2
        assert {e['url'] for e in endpoint(bob,'/api/courses')()} == {'/courses/common/','/courses/optional/', b1['study_url']}
        home = endpoint(alice,'/')()
        assert a1['study_url'] in home and a2['study_url'] in home and b1['study_url'] not in home
        assert a1['reader_url'] in home and a2['reader_url'] in home and b1['reader_url'] not in home
        scope = Scope.model_validate_json((default/'current.json').read_text())
        endpoint(ac,'/api/chat/sessions','POST')(NewSession(title='甲的复习'),scope)
        endpoint(bc,'/api/chat/sessions','POST')(NewSession(title='乙的复习'),scope)
        assert [s['title'] for s in endpoint(ac,'/api/chat/sessions')(scope)] == ['甲的复习']
        assert [s['title'] for s in endpoint(bc,'/api/chat/sessions')(scope)] == ['乙的复习']
        elective = Scope.model_validate_json((default.parent/'optional/current.json').read_text())
        assert endpoint(mount(bob,'/courses/optional'),'/api/chat/sessions')(elective) == []
    finally:
        ar.close()
        br.close()
    reopened = ChatRunner(a.chats, runtime=object())
    try:
        again = create_student_app(default, a, chat_runner=reopened)
        assert [s['title'] for s in endpoint(mount(again,'/courses/common'),'/api/chat/sessions')(scope)] == ['甲的复习']
    finally:
        reopened.close()


def test_private_only_student_can_start_empty_and_find_own_import(tmp_path):
    from examsage.student_web import create_student_app
    default = public_library(tmp_path)
    a = student(tmp_path/'students','private-only',[])
    ar = ChatRunner(a.chats,runtime=object())
    try:
        app = create_student_app(default, a, chat_runner=ar)
        assert endpoint(app,'/api/courses')() == []
        assert endpoint(app,'/api/chat/status')() == {**ar.status(),'workspace_mode':'personal_student'}
        assert 'href="/import/"' in endpoint(app,'/')()
        result = local_upload(a,'数列条件')
        assert [row['url'] for row in endpoint(app,'/api/courses')()] == [result['study_url']]
        intake = mount(app,'/import')
        from uuid import UUID
        response = endpoint(intake,'/{batch_id:uuid}/reader')(UUID(result['id']))
        assert Path(response.path).is_file() and Path(response.path).is_relative_to(a.imports)
        current = a.open_import(result['id'])/'current.json'
        scope = Scope.model_validate_json(current.read_bytes()).model_copy(update={'allowed_sources':[]})
        current.write_text(scope.model_dump_json(),encoding='utf-8')
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as updated:
            endpoint(intake,'/{batch_id:uuid}/reader')(UUID(result['id']))
        assert updated.value.status_code == 409
        assert endpoint(app,'/api/courses')() == []
    finally:
        ar.close()


def test_host_must_bind_personal_chat_storage(tmp_path):
    from examsage.student_web import create_student_app
    default = public_library(tmp_path)
    a = student(tmp_path/'students','alice',[])
    with pytest.raises(ValueError):
        create_student_app(default, a, chat_runner=None)
    shared = ChatRunner(tmp_path/'shared-history', runtime=object())
    try:
        with pytest.raises(ValueError):
            create_student_app(default, a, chat_runner=shared)
    finally:
        shared.close()


def test_shared_pdf_preview_is_saved_in_personal_workspace(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from examsage.source_paths import source_path
    from examsage.student_web import create_student_app
    from test_course_pack_formats import import_source, make_pdf
    source = tmp_path/'notes.pdf'
    make_pdf(source)
    import_source(tmp_path,source)
    data = tmp_path/'imported'
    (tmp_path/'library.json').write_text(json.dumps({'courses':[
        {'slug':'formats','name':'Physics','data':'imported'}]}),encoding='utf-8')
    workspace = student(tmp_path/'users','alice',['formats'])
    runner = ChatRunner(workspace.chats,runtime=object())
    try:
        app = create_student_app(data,workspace,chat_runner=runner)
        response = endpoint(mount(app,'/courses/formats'),'/api/preview/{doc_id}/{number}')('source',1)
        image = Path(response.path)
        assert image.is_file() and image.is_relative_to(source_path(workspace.chats/'previews'))
        assert not (data/'previews').exists()
        def unavailable(*args):
            raise ValueError('Storage unavailable')
        monkeypatch.setattr('examsage.api.checked_child', unavailable)
        with pytest.raises(HTTPException) as error:
            endpoint(mount(app,'/courses/formats'),'/api/preview/{doc_id}/{number}')('source',1)
        assert error.value.status_code == 404
    finally:
        runner.close()


def test_updated_public_material_scope_expires_old_sources_and_preview(tmp_path):
    from fastapi import HTTPException
    from examsage.student_web import create_student_app
    from test_course_pack_formats import import_source,make_pdf
    source=tmp_path/'notes.pdf'
    make_pdf(source)
    import_source(tmp_path,source)
    data=tmp_path/'imported'
    (tmp_path/'library.json').write_text(json.dumps({'courses':[
        {'slug':'formats','data':'imported'}]}),encoding='utf-8')
    workspace=student(tmp_path/'users','alice',['formats'])
    runner=ChatRunner(workspace.chats,runtime=object())
    try:
        app=create_student_app(data,workspace,chat_runner=runner)
        course=mount(app,'/courses/formats')
        paths=[('/api/documents',()),('/api/search',('positive',)),
               ('/api/page/{doc_id}/{number}',('source',1)),
               ('/api/source/{doc_id}',('source',)),('/api/preview/{doc_id}/{number}',('source',1))]
        for path,args in paths:
            assert read_course_route(course,path,*args)
        current=data/'current.json'
        scope=Scope.model_validate_json(current.read_bytes()).model_copy(update={'allowed_sources':[]})
        current.write_text(scope.model_dump_json(),encoding='utf-8')
        for path,args in paths:
            with pytest.raises(HTTPException) as error:
                read_course_route(course,path,*args)
            assert error.value.status_code == 409
        again=mount(create_student_app(data,workspace,chat_runner=runner),'/courses/formats')
        assert read_course_route(again,'/api/documents') == []
    finally:
        runner.close()


def test_changed_public_grant_updates_menu_and_stops_active_chat(tmp_path):
    from fastapi import HTTPException
    from examsage.chat_api import SendMessage
    from examsage.student_web import create_student_app
    from test_chat_runner import Tutor,wait_run
    data=public_library(tmp_path)
    workspace=student(tmp_path/'users','alice',['common','optional'])
    runtime=Tutor()
    runner=ChatRunner(workspace.chats,runtime=runtime)
    try:
        app=create_student_app(data,workspace,chat_runner=runner)
        course=mount(app,'/courses/common')
        scope=Scope.model_validate_json((data/'current.json').read_bytes())
        session=runner.store.create_session(scope,'复习')
        turn=endpoint(course,'/api/chat/sessions/{session_id}/messages','POST')(
            session['id'],SendMessage(text='Darcy',client_request_id='one'),scope)
        assert runtime.started.wait(2)
        student(tmp_path/'users','alice',['optional']).remember_public_grants()
        runtime.release.set()
        result=wait_run(runner,scope,turn['id'])
        assert result['error']['code']=='scope_changed' and result['answer'] is None
        assert {row['slug'] for row in endpoint(app,'/api/courses')()}=={'optional'}
        assert '/courses/common/' not in endpoint(app,'/')()
        with pytest.raises(HTTPException) as error:
            read_course_route(course,'/api/documents')
        assert error.value.status_code==409
    finally:
        runtime.release.set()
        runner.close()


def test_students_upload_and_study_through_their_own_web_apps(tmp_path):
    from fastapi.testclient import TestClient
    from examsage.student_web import create_student_app
    from test_student_navigation import Links
    default = public_library(tmp_path)
    root = tmp_path/'students'
    a, b = student(root,'alice',['common']), student(root,'bob',[])
    ar, br = ChatRunner(a.chats,runtime=object()), ChatRunner(b.chats,runtime=object())
    try:
        for workspace, runner, wording in [(a,ar,'甲的水头条件'),(b,br,'乙的发电条件')]:
            app = create_student_app(default,workspace,chat_runner=runner)
            with TestClient(app,base_url='http://localhost',client=('127.0.0.1',51122)) as client:
                assert client.get('/').status_code == 200
                assert client.get('/static/course-intake.js').status_code == 200
                assert client.get('/import/').status_code == 200
                res = client.post('/import/',data={'name':'同名私课','discipline':'物理'},
                                  files={'files':('资料.txt',wording.encode(),'text/plain')},
                                  headers={'Origin':'http://localhost'})
                assert res.status_code==200, res.text
                item=res.json()
                assert item['study_url'] in client.get('/').text
                for link in (item['reader_url'], item['study_url']):
                    page = client.get(link)
                    assert page.status_code == 200
                    assert ('我的课程', '/') in Links(page.text).items
                menu=client.get(item['study_url']+'api/courses').json()
                assert menu==client.get('/api/courses').json()
                docs=client.get(item['study_url']+'api/documents').json()
                page=client.get(item['study_url']+'api/page/'+docs[0]['id']+'/1').json()
                assert wording in page['bundle']['records'][0]['text']
                sessions=item['study_url']+'api/chat/sessions'
                assert client.post(sessions,json={'title':wording}).status_code==200
                assert [session['title'] for session in client.get(sessions).json()]==[wording]
                current=workspace.open_import(item['id'])/'current.json'
                scope=Scope.model_validate_json(current.read_bytes()).model_copy(update={'allowed_sources':[]})
                current.write_text(scope.model_dump_json(),encoding='utf-8')
                for url in (item['reader_url'],item['study_url']+'api/documents',sessions):
                    response=client.get(url)
                    assert response.status_code==409 and '重新打开课程' in response.json()['detail']
    finally:
        ar.close()
        br.close()
