import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examsage.plugin_tools import Principal
from test_plugin_candidates import candidate_source
from test_web_intake import make_import


def test_running_student_tools_discover_own_uploads_and_restore_after_restart(tmp_path):
    from examsage.student_workspace import StudentWorkspace, student_tools
    library=candidate_source(tmp_path/'common')/'data'
    a=StudentWorkspace(tmp_path/'people',Principal('school:A',frozenset(['grt'])))
    b=StudentWorkspace(tmp_path/'people',Principal('school:B',frozenset(['grt','ses'])))
    tools_a,tools_b=student_tools(library,a),student_tools(library,b)
    def ids(api): return {c['course_id'] for c in api.call('list_courses',{})['courses']}
    assert ids(tools_a)=={'grt'} and ids(tools_b)=={'grt','ses'}
    assert not (tmp_path/'people').exists()
    alice=make_import(a.imports,[('notes.txt',io.BytesIO(b'Capillary rise in column A.'))])
    bob=make_import(b.imports,[('notes.txt',io.BytesIO(b'Phase changes in column B.'))])
    aid,bid='upload-'+alice['id'],'upload-'+bob['id']
    assert ids(tools_a)=={'grt',aid} and ids(tools_b)=={'grt','ses',bid}
    assert a.private_catalog()==[{'slug':aid,'name':'数学导论','url':alice['study_url']}]
    for api,my_id,marker in [(tools_a,aid,'Capillary rise'),(tools_b,bid,'Phase changes')]:
        page=api.call('browse_course_materials',{'course_id':my_id,'offset':0})['pages'][0]
        assert marker in page['excerpt']
        source=api.call('get_source_page',{'course_id':my_id,'document_id':page['document_id'],'page':1})
        assert source['sources'][0]['refs'][0]['filename']=='notes.txt'
    reopened=StudentWorkspace(tmp_path/'people',a.principal)
    assert a.open_import(alice['id'])==reopened.open_import(alice['id'])
    assert ids(student_tools(library,reopened))=={'grt',aid}
    assert a.chats!=b.chats and a.imports!=b.imports


def test_personal_only_and_legacy_courses_remain_separate(tmp_path):
    from examsage.student_workspace import StudentWorkspace, student_tools
    make_import(tmp_path/'legacy')
    w=StudentWorkspace(tmp_path/'students',Principal('pilot',frozenset()))
    api=student_tools(tmp_path/'no-public-library',w)
    assert api.call('list_courses',{})['courses']==[]
    receipt=make_import(w.imports)
    assert [r['course_id'] for r in api.call('list_courses',{})['courses']]==['upload-'+receipt['id']]
    assert len(list((tmp_path/'legacy').glob('*/import.json')))==1
    # An incomplete import remains unpublished until its receipt exists.
    (w.imports/'3d098184-6005-44b7-a347-c47dde56e5c9').mkdir()
    assert len(w.private_catalog())==1


def test_personal_plugin_and_web_launcher_resolve_same_local_account(tmp_path):
    from examsage.student_workspace import local_workspace
    a=local_workspace(tmp_path,['grt'])
    b=local_workspace(tmp_path,['ses'])
    assert a.principal.subject==b.principal.subject and a.imports==b.imports
    assert a.principal.course_ids!=b.principal.course_ids and not a.imports.exists()


def test_durable_selection_filters_an_already_open_personal_tool_catalog(tmp_path):
    from examsage.student_workspace import StudentWorkspace, student_tools
    lib=candidate_source(tmp_path/'common')/'data'
    root=tmp_path/'students'
    a=StudentWorkspace(root,Principal('A',frozenset(['grt','ses'])))
    api=student_tools(lib,a)
    def ids(): return {row['course_id'] for row in api.call('list_courses',{})['courses']}
    assert ids()=={'grt','ses'}
    StudentWorkspace(root,Principal('A',frozenset(['ses']))).remember_public_grants()
    assert ids()=={'ses'} and a.effective_public_grants()=={'ses'}
    StudentWorkspace(root,Principal('A',frozenset())).remember_public_grants()
    assert ids()==set()
    assert StudentWorkspace(root,Principal('B',frozenset(['grt']))).effective_public_grants()=={'grt'}


def test_course_menu_keeps_healthy_imports_during_partial_restore(tmp_path):
    from examsage.student_workspace import StudentWorkspace, student_tools
    w=StudentWorkspace(tmp_path/'students',Principal('A',frozenset()))
    healthy=make_import(w.imports)
    partial=make_import(w.imports)
    # Model a normal restore in which one database has not arrived yet.
    db=w.open_import(partial['id'])/'course.sqlite3'
    db.rename(db.with_suffix('.pending'))
    assert [c['slug'] for c in w.private_catalog()]==['upload-'+healthy['id']]
    assert len(student_tools(tmp_path,w).call('list_courses',{})['courses'])==1


def test_personal_tools_refresh_published_shared_snapshot(tmp_path):
    from examsage.domain import Scope
    from examsage.storage import Store
    from examsage.student_workspace import StudentWorkspace, student_tools
    lib=candidate_source(tmp_path/'common')/'data'
    api=student_tools(lib,StudentWorkspace(tmp_path/'students',Principal('A',frozenset(['grt']))))
    before=api.call('list_courses',{})['courses'][0]
    current=lib/'grt/current.json'
    s=Scope.model_validate_json(current.read_bytes())
    store=Store(lib/'grt/course.sqlite3')
    snapshot=store.publish(s.workspace,store.manifest(s),store.list_records(s),[],{'edition':2})
    current.write_text(s.model_copy(update={'snapshot':snapshot}).model_dump_json(),encoding='utf-8')
    assert api.call('list_courses',{})['courses'][0]['snapshot']==snapshot!=before['snapshot']


def test_private_only_plugin_package_does_not_require_public_library(tmp_path):
    from examsage.plugin_package import build_package
    report=build_package(tmp_path/'plugin',tmp_path/'absent',[],Path(sys.executable),student_root=tmp_path/'students')
    assert report['courses']==[]
    assert json.loads((tmp_path/'plugin/local-settings.json').read_text(encoding='utf-8'))['courses']==''


def test_packaged_stdio_sees_new_student_import_without_restart(tmp_path):
    from examsage.plugin_package import build_package
    from examsage.student_workspace import local_workspace
    root=tmp_path/'students'
    library=candidate_source(tmp_path/'common')/'data'
    package=tmp_path/'plugin'
    build_package(package,library,['grt'],Path(sys.executable),student_root=root)
    settings=next(iter(json.loads((package/'.mcp.json').read_text(encoding='utf-8'))['mcpServers'].values()))
    cmd=[settings['command'],*[v.replace('${PLUGIN_ROOT}',str(package)) for v in settings['args']]]
    env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','TEMP','TMP') if k in os.environ}
    with subprocess.Popen(cmd,cwd=package,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          text=True,encoding='utf-8') as server:
        def send(method,params,ident=None):
            msg={'jsonrpc':'2.0','method':method,'params':params}
            if ident is not None: msg['id']=ident
            server.stdin.write(json.dumps(msg)+'\n')
            server.stdin.flush()
            if ident is not None:
                return json.loads(server.stdout.readline())['result']
        def call(name,arguments,ident):
            result=send('tools/call',{'name':name,'arguments':arguments},ident)
            assert not result.get('isError'),result['content']
            return result['structuredContent']
        try:
            send('initialize',{'capabilities':{},'protocolVersion':'2025-11-25',
                               'clientInfo':{'name':'student-test','version':'1'}},1)
            send('notifications/initialized',{})
            assert [c['course_id'] for c in call('list_courses',{},2)['courses']]==['grt']
            w=local_workspace(root,['grt'])
            receipt=make_import(w.imports,[('lecture.txt',io.BytesIO(b'Magnetism in the sample.'))])
            cid='upload-'+receipt['id']
            assert {c['course_id'] for c in call('list_courses',{},3)['courses']}=={'grt',cid}
            rows=call('browse_course_materials',{'course_id':cid,'offset':0},4)
            assert rows['pages'][0]['excerpt']=='Magnetism in the sample.'
        finally:
            server.stdin.close()
            server.wait(timeout=10)
