import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_plugin_tools import api


@pytest.mark.parametrize('cache_name', ['installed-plugin', '课程 插件 & 100% !'])
@pytest.mark.parametrize('clean_console', [False, True])
def test_built_package_runs_after_move_without_source_pythonpath(tmp_path, cache_name, clean_console):
    from examsage.plugin_package import build_package
    api(tmp_path / 'library')
    import sqlite3
    folder = tmp_path / 'library' / 'physics'
    with sqlite3.connect(folder / 'course.sqlite3') as db:
        sid = db.execute('SELECT id FROM snapshots').fetchone()[0]
    (folder / 'current.json').write_text(json.dumps({'workspace': 'w', 'course': 'physics',
        'snapshot': sid, 'allowed_sources': ['doc']}), encoding='utf-8')
    (folder.parent / 'library.json').write_text(json.dumps({'courses': [{'slug': 'physics', 'data': 'physics'}]}))
    output = tmp_path / 'package'
    build_package(output, folder.parent, ['physics'], Path(sys.executable))
    relocated = tmp_path / 'cache' / cache_name
    relocated.parent.mkdir()
    shutil.move(str(output), str(relocated))
    config = json.loads((relocated / 'mcp.json').read_text(encoding='utf-8'))['mcpServers']['examsage']
    # Agent Plugins 1.0.0 section 7.2.1: absolute executable paths are invalid.
    assert config['command'].startswith('./') or all(c not in config['command'] for c in '/\\:')
    executable = str(relocated / config['command']) if config['command'].startswith('./') else config['command']
    command = [executable, *[arg.replace('${PLUGIN_ROOT}', str(relocated)) for arg in config['args']]]
    env = {k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH') if k in os.environ}
    launch_options = {}
    if clean_console:
        env.pop('PATH', None)
        env['EXAMSAGE_TEST_LAUNCHER'] = executable
        (tmp_path / 'cp437.cmd').write_text(
            '@echo off\n"%SystemRoot%\\System32\\chcp.com" 437 >nul\n'
            '"%EXAMSAGE_TEST_LAUNCHER%"\n', encoding='ascii')
        command = [str(Path(os.environ['SYSTEMROOT']) / 'System32' / 'cmd.exe'), '/d', '/c', 'cp437.cmd']
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        launch_options = {'creationflags': subprocess.CREATE_NEW_CONSOLE, 'startupinfo': startup}
    messages = [{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25',
        'capabilities': {}, 'clientInfo': {'name': 'package-check', 'version': '1'}}},
        {'method': 'notifications/initialized'},
        {'id': 2, 'method': 'tools/call', 'params': {'name': 'search_evidence',
          'arguments': {'course_id': 'physics', 'query': 'Darcy'}}}]
    result = subprocess.run(command, env=env, cwd=tmp_path, input=''.join(json.dumps(
        {'jsonrpc': '2.0', **m})+'\n' for m in messages), text=True, encoding='utf-8',
        capture_output=True, timeout=15, **launch_options)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[-1]['result']['structuredContent']['records']
    assert not list(relocated.rglob('*.sqlite3'))
    with pytest.raises(FileExistsError):
        build_package(relocated, folder.parent, ['physics'], Path(sys.executable))
