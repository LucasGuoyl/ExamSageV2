import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_plugin_tools import api


def initialized(server):
    result = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}})
    assert result['result']['protocolVersion'] == '2025-11-25'
    assert server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) is None


def test_protocol_initialization_tools_and_safe_failure(tmp_path):
    from examsage.mcp_server import MCPServer
    server = MCPServer(api(tmp_path))
    assert server.handle({'jsonrpc': '2.0', 'id': 0, 'method': 'tools/list'})['error']['code'] == -32000
    initialized(server)
    definitions = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})['result']['tools']
    assert len(definitions) >= 9
    assert all(t['annotations']['readOnlyHint'] for t in definitions)
    result = server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
        'name': 'search_evidence', 'arguments': {'course_id': 'physics', 'query': 'Darcy'}}})['result']
    assert result['structuredContent']['records']
    assert json.loads(result['content'][0]['text']) == result['structuredContent']
    result = server.handle({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {
        'name': 'get_source_page', 'arguments': {'course_id': 'physics', 'document_id': 'doc', 'page': True}}})
    assert result['result']['isError'] is True


@pytest.mark.parametrize('message', [[], {}, {'jsonrpc': '2.0', 'id': True, 'method': 'ping'},
    {'jsonrpc': '1.0', 'id': 1, 'method': 'ping'}, {'jsonrpc': '2.0', 'id': None, 'method': 'ping'}])
def test_invalid_envelopes(tmp_path, message):
    from examsage.mcp_server import MCPServer
    assert MCPServer(api(tmp_path)).handle(message)['error']['code'] == -32600


def test_unsupported_version_is_negotiated_not_echoed(tmp_path):
    from examsage.mcp_server import MCPServer
    server = MCPServer(api(tmp_path))
    result = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2099-01-01', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
    assert result['result']['protocolVersion'] == '2025-11-25'


@pytest.mark.parametrize('name', [[], {}, True, 1, None])
def test_malformed_tool_names_do_not_crash_server(tmp_path, name):
    from examsage.mcp_server import MCPServer
    server = MCPServer(api(tmp_path))
    initialized(server)
    response = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': name}})
    assert response['error']['code'] == -32602
    assert server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'ping'})['result'] == {}


def test_stdio_rejects_bad_json_recovers_and_never_responds_to_notifications(tmp_path):
    from examsage.mcp_server import MCPServer, serve_stdio
    source = io.BytesIO(b'{bad\n{"jsonrpc":"2.0","method":"notifications/cancelled"}\n'
                        b'{"jsonrpc":"2.0","id":9,"method":"ping"}\n')
    target = io.BytesIO()
    serve_stdio(MCPServer(api(tmp_path)), source, target)
    messages = [json.loads(line) for line in target.getvalue().splitlines()]
    assert len(messages) == 2
    assert messages[0]['error']['code'] == -32700
    assert messages[1] == {'jsonrpc': '2.0', 'id': 9, 'result': {}}


def test_invalid_unicode_id_does_not_terminate_stdio(tmp_path):
    from examsage.mcp_server import MCPServer, serve_stdio
    messages = [dict(jsonrpc='2.0', id='\ud800', method='ping'),
                dict(jsonrpc='2.0', id=7, method='ping')]
    source = io.BytesIO(('\n'.join(json.dumps(m) for m in messages)+'\n').encode('ascii'))
    output = io.BytesIO()
    serve_stdio(MCPServer(api(tmp_path)), source, output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert responses[0]['error']['code'] == -32600
    assert responses[1]['result'] == {}


def test_actual_subprocess_handshake_and_query(tmp_path):
    api(tmp_path)
    for course in ('physics', 'history'):
        import sqlite3
        with sqlite3.connect(tmp_path / course / 'course.sqlite3') as db:
            snapshot = db.execute('SELECT id FROM snapshots').fetchone()[0]
        (tmp_path / course / 'current.json').write_text(json.dumps({
            'workspace': 'w', 'course': course, 'snapshot': snapshot, 'allowed_sources': ['doc']}), encoding='utf-8')
    (tmp_path / 'library.json').write_text(json.dumps({'courses': [
        {'slug': c, 'data': c} for c in ('physics', 'history')]}), encoding='utf-8')
    messages = [
        {'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
            'clientInfo': {'name': 'student-simulator', 'version': '1'}}},
        {'method': 'notifications/initialized'},
        {'id': 2, 'method': 'tools/call', 'params': {'name': 'search_evidence',
            'arguments': {'course_id': 'physics', 'query': 'Darcy'}}},
        {'id': 3, 'method': 'tools/call', 'params': {'name': 'search_evidence',
            'arguments': {'course_id': 'history', 'query': 'Darcy'}}},
    ]
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if k in os.environ}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'), PYTHONUTF8='1')
    result = subprocess.run([sys.executable, '-m', 'examsage.mcp_server', '--library', str(tmp_path),
                             '--courses', 'physics'], env=env, input=''.join(json.dumps(
        {'jsonrpc': '2.0', **m}) + '\n' for m in messages), capture_output=True, text=True,
        encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(responses) == 3
    assert responses[1]['result']['structuredContent']['records']
    assert responses[2]['result']['isError'] is True
