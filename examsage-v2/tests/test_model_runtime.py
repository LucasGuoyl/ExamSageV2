import threading
from collections import deque
import queue
import time
import json
import io

import pytest

from examsage.model_runtime import SubscriptionRuntime, RuntimeFailure, safe_environment, _Transport


def test_installed_program_hint_is_used_when_launcher_path_has_no_codex(tmp_path, monkeypatch):
    from examsage.model_runtime import resolve_program
    monkeypatch.setattr('examsage.model_runtime.shutil.which', lambda _: None)
    installed = tmp_path / 'installed' / 'codex.exe'
    installed.parent.mkdir(); installed.write_bytes(b'test-only-not-executed')
    (tmp_path / 'codex-program.json').write_text(json.dumps({'executable': str(installed)}), encoding='utf-8')
    assert resolve_program(tmp_path) == str(installed)


@pytest.mark.parametrize('hint', ['codex.exe', 'missing/codex.exe', 'python.exe'])
def test_unusable_program_hint_fails_without_running_other_programs(tmp_path, monkeypatch, hint):
    from examsage.model_runtime import resolve_program
    monkeypatch.setattr('examsage.model_runtime.shutil.which', lambda _: None)
    monkeypatch.setattr('examsage.model_runtime.registered_cli', lambda: None)
    (tmp_path / 'codex-program.json').write_text(json.dumps({'executable': hint}), encoding='utf-8')
    with pytest.raises(RuntimeFailure) as error:
        resolve_program(tmp_path)
    assert error.value.code == 'not_installed'


def test_current_path_takes_priority_over_an_old_program_hint(tmp_path, monkeypatch):
    from examsage.model_runtime import resolve_program
    monkeypatch.setattr('examsage.model_runtime.shutil.which', lambda _: 'current/codex.exe')
    (tmp_path / 'codex-program.json').write_text('{invalid', encoding='utf-8')
    assert resolve_program(tmp_path) == 'current/codex.exe'


def test_isolated_runtime_can_use_shared_program_location_without_copying_credentials(tmp_path, monkeypatch):
    from examsage.model_runtime import resolve_program
    monkeypatch.setattr('examsage.model_runtime.shutil.which', lambda _: None)
    program = tmp_path / 'codex.exe'; program.write_bytes(b'not-executed')
    hint = tmp_path / 'codex-program.json'
    hint.write_text(json.dumps({'executable': str(program)}), encoding='utf-8')
    assert resolve_program(tmp_path / 'isolated', installation_hint=hint) == str(program)
    assert not (tmp_path / 'isolated').exists()


def test_transport_keeps_official_tool_host_without_enabling_general_tools(tmp_path, monkeypatch):
    captured = {}
    class Process:
        stdin = io.StringIO(); stdout = io.StringIO(); stderr = io.StringIO()
        def poll(self): return 0
    def spawn(args, **kwargs):
        captured['args'] = args; captured['env'] = kwargs['env']; return Process()
    monkeypatch.setattr('examsage.model_runtime.resolve_program', lambda *args, **kwargs: 'codex.exe')
    monkeypatch.setattr('examsage.model_runtime.subprocess.Popen', spawn)
    wire = _Transport(tmp_path)
    try:
        args = captured['args']
        config = dict(arg.split('=', 1) for i, arg in enumerate(args) if i and args[i - 1] == '-c')
        assert config['features.code_mode_host'] == 'true'
        for feature in ('code_mode', 'shell_tool', 'browser_use', 'computer_use', 'apps', 'plugins', 'multi_agent'):
            assert config['features.' + feature] == 'false'
        assert config['sandbox_mode'] == '"read-only"'
        assert config['forced_login_method'] == '"chatgpt"'
    finally:
        wire.close()


class Wire:
    def __init__(self, auth='chatgpt', events=None):
        self.auth = auth
        self.events = list(events or [])
        self.calls = []
        self.responses = []
        self.closed = False

    def request(self, method, params, **kwargs):
        self.calls.append((method, params))
        if method == 'initialize': return {}
        if method == 'account/read':
            return {'account': {'type': self.auth, 'planType': 'plus'}, 'requiresOpenaiAuth': True}
        if method == 'account/rateLimits/read':
            return {'ordinaryUsageAllowed': True, 'rateLimits': {'primary': {'usedPercent': 30}}}
        if method == 'model/list':
            return {'data': [{'id': 'available-model', 'model': 'available-model', 'isDefault': True}]}
        if method == 'thread/start': return {'thread': {'id': 't1'}, 'modelProvider': 'openai'}
        if method == 'turn/start': return {'turn': {'id': 'u1'}}
        if method == 'turn/interrupt': return {}
        raise AssertionError(method)

    def notify(self, method, params): pass
    def receive(self, **kwargs): return self.events.pop(0)
    def respond(self, request_id, result): self.responses.append((request_id, result))
    def close(self): self.closed = True


def completed(text='{"paragraphs":[],"limitations":[]}'):
    return [
        {'method': 'item/completed', 'params': {'threadId': 't1', 'turnId': 'u1',
          'item': {'type': 'agentMessage', 'text': text, 'phase': 'final_answer'}}},
        {'method': 'turn/completed', 'params': {'threadId': 't1',
          'turn': {'id': 'u1', 'status': 'completed', 'error': None}}},
    ]


def runtime(tmp_path, wire):
    return SubscriptionRuntime(tmp_path, transport_factory=lambda: wire)


@pytest.mark.parametrize('auth', ['apiKey', 'amazonBedrock', None, 'chatgptAuthTokens'])
def test_other_auth_never_starts_model(tmp_path, auth):
    wire = Wire(auth)
    with pytest.raises(RuntimeFailure, match='ChatGPT'):
        runtime(tmp_path, wire).generate('question', [], lambda *_: {}, threading.Event())
    assert not any(m in {'thread/start', 'turn/start'} for m, _ in wire.calls)
    assert wire.closed


def test_credentials_and_custom_endpoints_are_not_forwarded():
    env = safe_environment({'PATH': 'ok', 'OPENAI_API_KEY': 'forbidden',
                            'CODEX_ACCESS_TOKEN': 'forbidden', 'OPENAI_BASE_URL': 'bad',
                            'EXAMSAGE_EMBEDDING_KEY': 'forbidden', 'SystemRoot': 'windows'})
    assert env == {'PATH': 'ok', 'SystemRoot': 'windows'}


def test_dynamic_tool_is_executed_and_final_completion_required(tmp_path):
    event = {'id': 'tool1', 'method': 'item/tool/call', 'params': {
        'threadId': 't1', 'turnId': 'u1', 'callId': 'c1', 'tool': 'search_evidence',
        'namespace': None, 'arguments': {'query': 'Darcy'}}}
    wire = Wire(events=[event, *completed()])
    calls = []
    result = runtime(tmp_path, wire).generate('question', [],
        lambda name, args: calls.append((name, args)) or {'evidence': ['E1']}, threading.Event())
    assert calls == [('search_evidence', {'query': 'Darcy'})]
    assert wire.responses[0][1]['success'] is True
    assert result['paragraphs'] == []
    start = next(p for m, p in wire.calls if m == 'thread/start')
    assert start['environments'] == [] and start['ephemeral'] is True
    assert start['modelProvider'] == 'openai'
    assert wire.closed


def test_partial_output_is_not_success(tmp_path):
    wire = Wire(events=[*completed()[:1], {'method': 'turn/completed', 'params': {
        'threadId': 't1', 'turn': {'id': 'u1', 'status': 'failed',
        'error': {'message': 'secret upstream detail'}}}}])
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('q', [], lambda *_: {}, threading.Event())
    assert 'secret' not in str(error.value)


def test_cancel_before_call_never_starts_model(tmp_path):
    wire = Wire(); cancel = threading.Event(); cancel.set()
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('q', [], lambda *_: {}, cancel)
    assert error.value.code == 'cancelled'
    assert not wire.calls


def test_unexpected_builtin_tool_stops_run(tmp_path):
    wire = Wire(events=[{'method': 'item/started', 'params': {'threadId': 't1',
        'turnId': 'u1', 'item': {'type': 'commandExecution'}}}])
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('q', [], lambda *_: {}, threading.Event())
    assert error.value.code == 'unexpected_tool'
    assert wire.closed


@pytest.mark.parametrize('allowed', [False, None])
def test_unknown_or_disallowed_included_usage_never_starts_model(tmp_path, allowed):
    class Limited(Wire):
        def request(self, method, params, **kwargs):
            if method == 'account/rateLimits/read':
                return {'ordinaryUsageAllowed': allowed,
                        'rateLimits': {'primary': {'usedPercent': 10},
                                       'credits': {'hasCredits': True}}}
            return super().request(method, params, **kwargs)
    wire = Limited()
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('q', [], lambda *_: {}, threading.Event())
    assert error.value.code in {'usage_limit', 'usage_unknown'}
    assert not any(m == 'thread/start' for m, _ in wire.calls)


def test_exhausted_subscription_notification_stops_before_next_tool(tmp_path):
    event = {'method': 'account/rateLimits/updated', 'params': {
        'rateLimits': {'primary': {'usedPercent': 100}}}}
    tool = {'id': 'c1', 'method': 'item/tool/call', 'params': {'threadId': 't1',
        'turnId': 'u1', 'tool': 'search_evidence', 'arguments': {'query': 'Darcy'}}}
    wire = Wire(events=[event, tool, *completed()]); calls = []
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('q', [], lambda *args: calls.append(args) or {}, threading.Event())
    assert error.value.code == 'usage_limit'
    assert not calls and wire.closed


def test_included_usage_is_rechecked_before_returning_tool_results(tmp_path):
    class Changed(Wire):
        reads = 0
        def request(self, method, params, **kwargs):
            if method == 'account/rateLimits/read':
                self.reads += 1
                return {'ordinaryUsageAllowed': self.reads == 1, 'rateLimits': {}}
            return super().request(method, params, **kwargs)
    tool = {'id': 'c1', 'method': 'item/tool/call', 'params': {'threadId': 't1',
        'turnId': 'u1', 'tool': 'search_evidence', 'arguments': {'query': 'Darcy'}}}
    wire = Changed(events=[tool, *completed()]); calls = []
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('q', [], lambda *args: calls.append(args) or {}, threading.Event())
    assert error.value.code == 'usage_limit' and not calls


def test_usage_rpc_preserves_parallel_course_tool_request():
    wire = _Transport.__new__(_Transport)
    wire.sequence = 0; wire.pending = deque(); wire.incoming = queue.Queue()
    wire._send = lambda message: None
    tool = {'id': 'tool2', 'method': 'item/tool/call', 'params': {'tool': 'search_evidence'}}
    wire.incoming.put(tool)
    wire.incoming.put({'id': 1, 'result': {'ordinaryUsageAllowed': True}})
    assert wire.request('account/rateLimits/read', {}, allow_tool_requests=True)['ordinaryUsageAllowed'] is True
    assert wire.receive(deadline=time.monotonic() + 1) == tool


@pytest.mark.parametrize('upstream, expected', [
    ({'code': -32600, 'message': 'private-account-detail',
      'data': {'reason': 'serverShuttingDown', 'unrelated': 'private-account-detail'}},
     {'method': 'account/rateLimits/read', 'rpc_code': -32600, 'reason': 'serverShuttingDown'}),
    ({'code': -32000, 'message': 'private-account-detail',
      'data': {'reason': 'private-account-detail',
               'codexErrorInfo': {'httpConnectionFailed': {'httpStatusCode': 503, 'body': 'private-account-detail'}}}},
     {'method': 'account/rateLimits/read', 'rpc_code': -32000,
      'error_type': 'httpConnectionFailed', 'http_status': 503}),
    ({'code': 'private-account-detail', 'message': 'private-account-detail', 'data': ['private-account-detail']},
     {'method': 'account/rateLimits/read'}),
])
def test_rpc_failure_records_safe_location_without_raw_upstream_text(upstream, expected):
    wire = _Transport.__new__(_Transport)
    wire.sequence = 0; wire.pending = deque(); wire.incoming = queue.Queue()
    sent = []
    wire._send = sent.append
    wire.incoming.put({'id': 1, 'error': upstream})
    with pytest.raises(RuntimeFailure) as error:
        wire.request('account/rateLimits/read', {})
    assert error.value.code == 'protocol_error'
    assert error.value.details == expected
    assert 'private-account-detail' not in str(error.value) + json.dumps(error.value.details)
    assert len(sent) == 1  # Diagnostic capture never retries or changes billing.


def test_revocation_during_connection_prevents_sending_old_context(tmp_path):
    revoked = threading.Event()
    class Revoking(Wire):
        def request(self, method, params, **kwargs):
            result = super().request(method, params, **kwargs)
            if method == 'thread/start': revoked.set()
            return result
    wire = Revoking(events=completed())
    def guard():
        if revoked.is_set(): raise RuntimeFailure('scope_changed', '权限已变化')
    with pytest.raises(RuntimeFailure) as error:
        runtime(tmp_path, wire).generate('old source text', [], lambda *_: {}, threading.Event(), before_send=guard)
    assert error.value.code == 'scope_changed'
    assert not any(method == 'turn/start' for method, _ in wire.calls)
