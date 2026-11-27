"""Browser study host checks use an isolated workspace and deterministic model transport."""
import base64
from contextlib import closing
import json
import threading
import time

import pytest

from examsage import study_host
from examsage.model_runtime import SubscriptionRuntime
from examsage.student_workspace import Principal, StudentWorkspace
from examsage.study_window import StudyDesk
from test_model_runtime import Wire, completed


def command(studio, state, action, **fields):
    return studio.request({**{k:state[k] for k in ('course_id', 'session_id', 'revision')},
                           'action':action, **fields})


def test_browser_course_chat_follow_up_citation_and_stale_submit(tmp_path):
    calls = []
    event = {'id':'tool1', 'method':'item/tool/call', 'params':{
        'threadId':'t1', 'turnId':'u1', 'callId':'c1', 'tool':'search_evidence',
        'arguments':{'query':'Hooke spring stiffness'}}}
    answer = json.dumps({'paragraphs':[{'text':'The spring has a stiffness of 200 N/m.',
                         'kind':'source', 'citations':['E1']}], 'limitations':[]})
    def transport():
        calls.append(True)
        return Wire(events=[event, *completed(answer)])
    def runtime(folder):
        return SubscriptionRuntime(folder, transport_factory=transport)
    workspace = StudentWorkspace(tmp_path, Principal('isolated test', frozenset()))
    with closing(StudyDesk(workspace, runtime_factory=runtime)) as desk:
        ui = study_host.Studio(desk)
        state = ui.request({'action':'state'})
        assert not state['courses'] and not state['messages']
        state = command(ui, state, 'import', name='Lecture', subject='Physics', files=[{
            'name':'lesson.txt', 'role':'lecture',
            'data':base64.b64encode(b'Hooke spring stiffness is 200 N/m.').decode()}])
        assert state['courses'][0]['slug'] == state['course_id']
        for question in ['What is the stiffness?', 'What were its units?']:
            before = state
            state = command(ui, state, 'send', question=question)
            rid = state['run_id']
            with pytest.raises(study_host.StaleView):
                command(ui, before, 'send', question=question)
            for _ in range(150):
                state = command(ui, state, 'poll', run_id=rid)
                if state['run']['status'] != 'running':
                    break
                time.sleep(.02)
            assert state['run']['status'] == 'completed', state['run']
            source = command(ui, state, 'citation', run_id=rid, evidence_id='E1', ref_index=0)
            assert (source['filename'], source['page'], source['text']) == (
                'lesson.txt', 1, 'Hooke spring stiffness is 200 N/m.')
            assert state['messages'][-1]['answer']['subscription_verified'] is True
        assert len(calls) == 2 and len(state['messages']) == 4
        session_id = state['session_id']
        other = command(ui, state, 'session', id=None)
        assert not other['messages']
        with pytest.raises(ValueError):
            command(ui, other, 'citation', run_id=rid, evidence_id='E1')
        restored = command(ui, other, 'session', id=session_id)
        assert len(restored['messages']) == 4
        desk.clear_selection()
        reopened = study_host.Studio(desk).request({'action':'state'})
        assert reopened['session_id'] == session_id and len(reopened['messages']) == 4
        receipt = next(workspace.imports.glob('*/import.json'))
        receipt.rename(receipt.with_suffix('.withdrawn'))
        expired = ui.request({'action':'state'})
        assert not expired['course_id'] and not expired['messages']


def test_bundled_example_selected_and_invalid_session_doesnt_replace_it(tmp_path):
    workspace = StudentWorkspace(tmp_path, Principal('example test', frozenset()))
    with closing(StudyDesk(workspace)) as desk:
        studio = study_host.Studio(desk)
        state = command(studio, studio.request({'action':'state'}), 'example')
        assert state['courses'] == [{'name':'物理示例 · 线性弹簧', 'slug':state['course_id']}]
        with pytest.raises(ValueError):
            command(studio, state, 'session', id='missing')
        assert studio.request({'action':'state'}) == state
        with pytest.raises(ValueError):
            command(studio, state, 'import', name='x', subject='x',
                    files=[{'name':'a.txt', 'role':'lecture', 'data':'invalid!'}])
        assert studio.request({'action':'state'}) == state


def test_only_issued_local_browser_can_read_or_change_study_state():
    from email.message import Message
    def headers(**replace):
        h = Message()
        for key, value in {'Host':'127.0.0.1:54321','Origin':'http://127.0.0.1:54321',
                         'X-ExamSage-Local':'local-capability', **replace}.items():
            h[key] = value
        return h
    local = study_host.local_browser
    assert local(headers(), '127.0.0.1:54321', 'local-capability')
    for h in (headers(Origin='null'),headers(Host='localhost:54321'),
              headers(**{'X-ExamSage-Local':'other'}), headers(**{'Sec-Fetch-Site':'cross-site'})):
        assert not local(h, '127.0.0.1:54321', 'local-capability')
    h = headers()
    h['Origin'] = 'http://127.0.0.1:54321'
    assert not local(h, '127.0.0.1:54321', 'local-capability')


def test_http_local_launcher_reopens_same_instance_and_removes_entry(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from http.client import HTTPConnection
    from queue import Queue
    from urllib.parse import urlsplit

    workspace = StudentWorkspace(tmp_path, Principal('HTTP test', frozenset()))
    opened = Queue()
    with ThreadPoolExecutor(max_workers=1) as worker:
        process = worker.submit(study_host.open_studio, workspace=workspace, launch=opened.put)
        try:
            url = opened.get(timeout=5)
            parts = urlsplit(url)
            origin = 'http://' + parts.netloc
            assert parts.hostname == '127.0.0.1' and parts.fragment
            def fetch(method, path, body=None, headers=None):
                with closing(HTTPConnection(parts.hostname, parts.port, timeout=5)) as conn:
                    conn.request(method, path, body=body, headers=headers or {})
                    response = conn.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
            status, headers, content = fetch('GET','/vendor/katex/katex.min.css')
            assert status == 200 and b'@font-face' in content
            assert headers['Referrer-Policy'] == 'no-referrer'
            assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
            assert fetch('GET','/api/studio')[0] == 404
            auth = {'Origin':origin, 'X-ExamSage-Local':parts.fragment,
                    'Content-Type':'application/json'}
            body = json.dumps({'action':'state'})
            assert fetch('POST','/api/studio',body,{'Content-Type':'application/json'})[0] == 403
            status, _, raw = fetch('POST','/api/studio',body,auth)
            assert status == 200 and not json.loads(raw)['courses']
            state = json.loads(raw)
            args = {k:state[k] for k in ('revision','session_id','course_id')}
            action = json.dumps({**args,'action':'example'})
            assert fetch('POST','/api/studio',action,auth)[0] == 200
            assert fetch('POST','/api/studio',action,auth)[0] == 409
            study_host.open_studio(workspace=workspace, launch=opened.put)
            assert opened.get(timeout=2) == url
        finally:
            monkeypatch.setattr(study_host, 'IDLE_SECONDS', 0)
            process.result(timeout=6)
    assert not (workspace.chats/'study-window'/'studio-active.json').exists()


def test_pdf_original_page_sent_as_png_and_pause_while_model_is_running(tmp_path):
    from test_course_pack_formats import make_pdf
    from test_study_reader import ref, save_turn
    from examsage.model_runtime import RuntimeFailure
    started = threading.Event()
    class Waiting:
        def __init__(self, folder): pass
        def generate(self, context, specs, call, cancel, phase, *, before_send):
            started.set()
            cancel.wait(4)
            raise RuntimeFailure('cancelled','已停止')
    workspace = StudentWorkspace(tmp_path/'student', Principal('PDF test', frozenset()))
    source = tmp_path/'lesson.pdf'
    make_pdf(source)
    with closing(StudyDesk(workspace, runtime_factory=Waiting)) as desk:
        ui = study_host.Studio(desk)
        state = command(ui, ui.request({'action':'state'}), 'import', name='PDF', subject='Physics',
                        files=[{'name':source.name,'data':base64.b64encode(source.read_bytes()).decode()}])
        desk.session_id = desk.runner.store.create_session(desk._current())['id']
        rid = save_turn(desk, [ref(desk,1)])
        state = ui.request({'action':'state'})
        image = command(ui, state, 'citation', run_id=rid, evidence_id='E1', image=True)
        assert base64.b64decode(image['png']).startswith(b'\x89PNG') and image['can_next']
        next_page = command(ui, state, 'citation', run_id=rid, evidence_id='E1', page=2)
        assert next_page['page'] == 2 and next_page['cited_page'] == 1
        state = command(ui, state, 'send', question='What does the document say?')
        assert started.wait(2)
        with pytest.raises(ValueError):
            command(ui, state, 'session', id=None)
        stopped = command(ui, state, 'stop', run_id=state['run_id'])
        assert not stopped['run_id'] and stopped['run']['status'] == 'cancelled'


def test_resume_selected_course_and_conversation_after_restart(tmp_path):
    workspace = StudentWorkspace(tmp_path, Principal('returning student', frozenset()))
    with closing(StudyDesk(workspace)) as desk:
        studio = study_host.Studio(desk)
        state = studio.request({'action':'state'})
        for name in ['Gravity', 'Groundwater']:
            state = command(studio, state, 'import', name=name, subject='Earth',
                            files=[{'name':'lecture.txt','data':base64.b64encode(name.encode()).decode()}])
        selected = state['courses'][-1]['slug']
        state = command(studio, state, 'course', id=selected)
        first = desk.runner.store.create_session(desk._current(), 'Review the pressure gradient')['id']
        desk.runner.store.create_session(desk._current(), 'Another session')
        command(studio, state, 'session', id=first)
    with closing(StudyDesk(workspace)) as desk:
        reopened = study_host.Studio(desk)
        state = reopened.request({'action':'state'})
        assert (state['course_id'], state['session_id']) == (selected, first)
        command(reopened, state, 'session', id=None)
    with closing(StudyDesk(workspace)) as desk:
        state = study_host.Studio(desk).request({'action':'state'})
        assert (state['course_id'], state['session_id']) == (selected, None)
