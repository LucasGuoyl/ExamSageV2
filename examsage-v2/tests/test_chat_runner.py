import threading
import time
import os

import pytest

from examsage.chat_runner import ChatRunner
from examsage.chat_store import ChatConflict, ChatNotFound
from examsage.model_runtime import RuntimeFailure
from test_chat_service import setup, answer


class Tutor:
    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def probe(self): return {'status': 'ready', 'generation_verified': False}

    def generate(self, context, specs, tools, cancel, on_status, *, before_send=lambda: None):
        self.calls += 1; self.started.set()
        if not self.release.wait(3): raise AssertionError('test did not release runtime')
        on_status('retrieving')
        result = tools('search_evidence', {'query': 'Darcy'})
        return answer([result['records'][0]['evidence_ids'][0]])


def wait_run(manager, scope, rid):
    end = time.monotonic() + 4
    while time.monotonic() < end:
        run = manager.get_run(scope, rid)
        if run['status'] != 'running': return run
        time.sleep(.01)
    raise AssertionError('run did not finish')


def test_duplicate_submit_starts_one_model_and_persists_answer(tmp_path):
    store, scope = setup(tmp_path); runtime = Tutor()
    manager = ChatRunner(tmp_path / 'chat', runtime=runtime)
    session = manager.store.create_session(scope)
    one = manager.submit(store, scope, session['id'], 'Darcy', 'request1')
    assert runtime.started.wait(2)
    two = manager.submit(store, scope, session['id'], 'Darcy', 'request1')
    assert one['id'] == two['id']
    runtime.release.set()
    result = wait_run(manager, scope, one['id'])
    assert result['status'] == 'completed'
    assert result['answer']['evidence'][0]['refs'][0]['page'] == 1
    assert runtime.calls == 1
    assert [m['role'] for m in manager.store.messages(scope, session['id'])] == ['user', 'assistant']
    manager.close()


def test_cancel_does_not_accept_late_model_answer(tmp_path):
    store, scope = setup(tmp_path); runtime = Tutor()
    manager = ChatRunner(tmp_path / 'chat', runtime=runtime)
    session = manager.store.create_session(scope)
    run = manager.submit(store, scope, session['id'], 'Darcy', 'request1')
    assert runtime.started.wait(2)
    with pytest.raises(ChatNotFound):
        manager.cancel(scope.model_copy(update={'course': 'other'}), run['id'])
    manager.cancel(scope, run['id']); runtime.release.set()
    manager.close()
    assert manager.get_run(scope, run['id'])['status'] == 'cancelled'
    assert len(manager.store.messages(scope, session['id'])) == 1


def test_connection_failure_is_visible_and_never_becomes_fake_answer(tmp_path):
    store, scope = setup(tmp_path)
    class Denied:
        def probe(self): raise RuntimeFailure('startup_denied', '连接被拒绝')
        def generate(self, *args, **kwargs): raise RuntimeFailure('startup_denied', '连接被拒绝')
    manager = ChatRunner(tmp_path / 'chat', runtime=Denied())
    assert manager.check_connection()['status'] == 'unavailable'
    session = manager.store.create_session(scope)
    run = manager.submit(store, scope, session['id'], 'Darcy', 'request1')
    result = wait_run(manager, scope, run['id'])
    assert result['status'] == 'failed' and result['error']['code'] == 'startup_denied'
    assert manager.store.messages(scope, session['id'])[0]['role'] == 'user'
    assert len(manager.store.messages(scope, session['id'])) == 1
    manager.close()


def test_connection_status_identifies_loaded_service_without_model_generation(tmp_path):
    runtime = Tutor(); manager = ChatRunner(tmp_path / 'chat', runtime=runtime)
    try:
        before = manager.status()
        checked = manager.check_connection()
        after = manager.status()
        assert before['server_pid'] == checked['server_pid'] == after['server_pid'] == os.getpid()
        assert before['runtime_revision'] == checked['runtime_revision'] == after['runtime_revision']
        assert before['runtime_revision'] and runtime.calls == 0
        assert after['generation_verified'] is False
    finally:
        manager.close()


def test_tool_limit_retains_successful_trace_and_rejected_call_without_answer(tmp_path):
    from test_model_runtime import Wire
    from examsage.model_runtime import SubscriptionRuntime
    store, scope = setup(tmp_path)
    events = [{'id': f'call{i}', 'method': 'item/tool/call', 'params': {
        'threadId': 't1', 'turnId': 'u1', 'tool': 'search_evidence',
        'arguments': {'query': 'Darcy'}}} for i in range(7)]
    wire = Wire(events=events)
    manager = ChatRunner(tmp_path / 'chat', runtime=SubscriptionRuntime(
        tmp_path / 'runtime', transport_factory=lambda: wire))
    session = manager.store.create_session(scope)
    try:
        run = manager.submit(store, scope, session['id'], 'Darcy', 'too-many-tools')
        result = wait_run(manager, scope, run['id'])
        assert result['status'] == 'failed' and result['answer'] is None
        assert result['error']['code'] == 'tool_limit'
        diagnostic = result['error']['diagnostics']
        assert len(diagnostic['trace']) == 6
        assert diagnostic['failure']['tool'] == 'search_evidence'
        assert diagnostic['failure']['arguments'] == {'query': 'Darcy'}
        assert diagnostic['failure']['attempt'] == 7
        assert len(wire.responses) == 6
        assert [m['role'] for m in manager.store.messages(scope, session['id'])] == ['user']
        with pytest.raises(ChatNotFound): manager.get_run(scope.model_copy(update={'course': 'other'}), run['id'])
    finally:
        manager.close()


@pytest.mark.parametrize('calls_tool', [True, False])
def test_scope_change_stops_inflight_tools_and_answer_persistence(tmp_path, calls_tool):
    store, scope = setup(tmp_path)
    revoked = threading.Event()
    class Waiting(Tutor):
        def generate(self, context, specs, tools, cancel, on_status, *, before_send=lambda: None):
            self.started.set(); assert self.release.wait(3)
            if calls_tool: tools('search_evidence', {'query': 'Darcy'})
            return answer([], 'insufficient')
    runtime = Waiting(); manager = ChatRunner(tmp_path / 'chat', runtime=runtime)
    session = manager.store.create_session(scope)
    run = manager.submit(store, scope, session['id'], 'Darcy', 'request1',
                         scope_guard=lambda: not revoked.is_set())
    assert runtime.started.wait(2)
    revoked.set(); runtime.release.set()
    result = wait_run(manager, scope, run['id'])
    assert result['status'] == 'failed' and result['error']['code'] == 'scope_changed'
    assert [m['role'] for m in manager.store.messages(scope, session['id'])] == ['user']
    manager.close()


def test_accepted_request_can_be_recovered_from_history_after_reply_is_lost(tmp_path):
    store, scope = setup(tmp_path); runtime = Tutor()
    manager = ChatRunner(tmp_path / 'chat', runtime=runtime)
    session = manager.store.create_session(scope)
    run = manager.submit(store, scope, session['id'], 'Darcy', 'lost-response')
    try:
        message = manager.store.messages(scope, session['id'])[-1]
        assert message['run_id'] == run['id']
        assert manager.get_run(scope, message['run_id'])['status'] == 'running'
    finally:
        runtime.release.set(); manager.close()


def test_verified_subscription_belongs_to_one_completed_turn(tmp_path):
    import json
    from test_model_runtime import Wire, completed
    from examsage.model_runtime import SubscriptionRuntime
    store, scope = setup(tmp_path)
    event = {'id':'c1','method':'item/tool/call','params':{'threadId':'t1','turnId':'u1',
             'tool':'search_evidence','arguments':{'query':'Darcy'}}}
    wire = Wire(events=[event, *completed(json.dumps(answer(['E1'])))])
    manager = ChatRunner(tmp_path/'chat',runtime=SubscriptionRuntime(tmp_path,transport_factory=lambda:wire))
    try:
        session = manager.store.create_session(scope)
        first = manager.submit(store,scope,session['id'],'Darcy','first-turn')
        verified = wait_run(manager,scope,first['id'])
        assert verified['status']=='completed', verified['error']
        assert verified['answer'].get('subscription_verified') is True
        manager.runtime = Tutor()
        manager.runtime.release.set()
        second = manager.submit(store,scope,session['id'],'Darcy units?','second-turn')
        ordinary = wait_run(manager,scope,second['id'])
        assert ordinary['status']=='completed', ordinary['error']
        assert 'subscription_verified' not in ordinary['answer']
        assert manager.store.messages(scope,session['id'])[1]['answer']['subscription_verified'] is True
    finally:
        manager.close()
