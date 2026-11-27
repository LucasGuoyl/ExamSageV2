import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examsage.cli import main
from examsage.model_runtime import safe_environment
from examsage.plugin_tools import Principal
from examsage.student_workspace import StudentWorkspace
from test_chat_api import endpoint
from test_student_web import public_library


def host(tmp_path, monkeypatch):
    from examsage import student_server
    public_library(tmp_path)
    monkeypatch.setattr(student_server,'local_workspace',lambda root,courses:
        StudentWorkspace(root,Principal('simulated-owner',frozenset(courses))))
    runners = []
    original = student_server.ChatRunner
    def runner(path):
        instance = original(path,runtime=object())
        runners.append(instance)
        return instance
    monkeypatch.setattr(student_server,'ChatRunner', runner)
    args = ['serve-student','--library',str(tmp_path),'--workspace-root',str(tmp_path/'students')]
    return student_server, args, runners


@pytest.mark.parametrize(('args','expected'), [
    ([],{'common','optional'}), (['--course','optional'],{'optional'}), (['--private-only'],set()),
])
def test_personal_cli_serves_selected_courses_on_loopback(tmp_path,monkeypatch,args,expected):
    server, base, runners = host(tmp_path,monkeypatch)
    menus = []
    def serve(app, *, host, port, proxy_headers):
        assert (host,port,proxy_headers)==('127.0.0.1',8769,False)
        menus.append({c['slug'] for c in endpoint(app,'/api/courses')()})
        assert endpoint(app,'/api/chat/status')()['workspace_mode']=='personal_student'
    monkeypatch.setattr(server.uvicorn,'run',serve)
    assert main(base + args)==0
    assert menus==[expected]
    assert len(runners)==1 and runners[0].closed


def test_duplicate_start_preserves_active_run_and_releases_after_exit(tmp_path,monkeypatch):
    from examsage.domain import Scope
    server, args, runners = host(tmp_path,monkeypatch)
    scope = Scope.model_validate_json((tmp_path/'common/current.json').read_bytes())
    def study(app, **kwargs):
        runner = runners[0]
        session = runner.store.create_session(scope,'正在复习')
        run = runner.store.begin_run(scope,session['id'],'再解释一遍','question-1')
        assert main(args+['--port','8770','--private-only'])==1
        assert len(runners)==1
        assert {row['slug'] for row in endpoint(app,'/api/courses')()} == {'common','optional'}
        assert runner.store.get_run(scope,run['id'])['status']=='running'
        runner.store.cancel_run(scope,run['id'])
    monkeypatch.setattr(server.uvicorn,'run',study)
    assert main(args)==0
    monkeypatch.setattr(server.uvicorn,'run',lambda app,**kwargs: None)
    assert main(args)==0
    assert len(runners)==2 and all(r.closed for r in runners)


def test_default_start_reuses_the_students_last_explicit_selection(tmp_path,monkeypatch):
    server,args,runners=host(tmp_path,monkeypatch)
    menus=[]
    monkeypatch.setattr(server.uvicorn,'run',lambda app,**kw:
                        menus.append({c['slug'] for c in endpoint(app,'/api/courses')()}))
    for selection in (['--course','common'],[],['--private-only'],[]):
        assert main(args+selection)==0
    assert menus==[{'common'},{'common'},set(),set()]


def test_workspace_lock_covers_other_processes(tmp_path):
    from examsage.student_server import student_process_lock
    chat = tmp_path/'chat'
    script = """from pathlib import Path
import os,sys
from examsage.student_server import student_process_lock, StudentServerBusy
try:
    with student_process_lock(Path(sys.argv[1])):
        print('acquired',flush=True)
        if len(sys.argv)>2:
            os._exit(0)
except StudentServerBusy:
    print('busy')
"""
    env = safe_environment()
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]/'src')
    def another_process(*args):
        return subprocess.run([sys.executable,'-c',script,str(chat),*args],env=env,capture_output=True,
                              text=True,check=True,timeout=20).stdout.strip()
    with student_process_lock(chat):
        assert another_process()=='busy'
    assert another_process('abrupt-exit')=='acquired'
    assert another_process()=='acquired'


def test_invalid_public_selection_stops_before_runner(tmp_path,monkeypatch):
    server, args, runners = host(tmp_path,monkeypatch)
    assert main(args+['--course','unregistered'])==1
    assert runners==[]


def test_public_course_granted_from_a_nested_course_pack_library(tmp_path,monkeypatch):
    from test_course_pack_formats import import_source,make_pdf
    server,args,runners=host(tmp_path,monkeypatch)
    nested=tmp_path/'courses'
    nested.mkdir()
    source=nested/'notes.pdf'
    make_pdf(source)
    import_source(nested,source)
    registry={'courses':[{'slug':'formats','data':'courses/imported'}]}
    (tmp_path/'library.json').write_text(json.dumps(registry),encoding='utf-8')
    menus=[]
    monkeypatch.setattr(server.uvicorn,'run',lambda app,**kw: menus.append(endpoint(app,'/api/courses')()))
    assert main(args+['--course','formats'])==0
    assert [[row['slug'] for row in menu] for menu in menus]==[['formats']]


def test_private_only_works_without_a_shared_library(tmp_path,monkeypatch):
    server,args,runners=host(tmp_path,monkeypatch)
    missing=tmp_path/'no-public-library'
    args[args.index('--library')+1]=str(missing)
    menus=[]
    monkeypatch.setattr(server.uvicorn,'run',lambda app,**kw: menus.append(endpoint(app,'/api/courses')()))
    assert main(args+['--private-only'])==0
    assert main(args)==0
    assert menus==[[],[]] and not missing.exists()


def test_host_start_failure_closes_runner_and_allows_retry(tmp_path,monkeypatch):
    server,args,runners=host(tmp_path,monkeypatch)
    def failed_start(app,**kwargs):
        raise OSError('port already in use')
    monkeypatch.setattr(server.uvicorn,'run',failed_start)
    assert main(args)==1 and runners[0].closed
    monkeypatch.setattr(server.uvicorn,'run',lambda app,**kwargs: None)
    assert main(args)==0 and len(runners)==2 and runners[1].closed


@pytest.mark.skipif(os.name!='nt',reason='Windows batch entry')
def test_double_click_entry_passes_personal_cli_and_default_port(tmp_path):
    root = Path(__file__).resolve().parents[1]
    launcher = '启动押题宝学生版.bat'
    folder = tmp_path/'含 空格的项目'
    folder.mkdir()
    for name in (launcher,'run.ps1'):
        (folder/name).write_bytes((root/name).read_bytes())
    probe = folder/'probe.ps1'
    probe.write_text("$args | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 -LiteralPath $env:EXAMSAGE_TEST_ARGS_PATH\nexit 0\n",encoding='ascii')
    output = folder/'arguments.json'
    env = safe_environment()
    env.update(EXAMSAGE_PYTHON=str(probe),EXAMSAGE_TEST_ARGS_PATH=str(output))
    run = subprocess.run(['cmd.exe','/d','/c',launcher],cwd=folder,env=env,capture_output=True,
                         timeout=20,input=b'',creationflags=subprocess.CREATE_NO_WINDOW)
    assert run.returncode==0,run.stderr
    args = [str(value) for value in json.loads(output.read_text(encoding='utf-8-sig'))]
    assert args[:5]==['-X','utf8','-m','examsage','serve-student']
    assert args[args.index('--port')+1]=='8769'
