import json
from pathlib import Path
import shutil
import subprocess

import pytest

from examsage.model_runtime import safe_environment


@pytest.mark.parametrize('reload_enabled', [False, True])
def test_windows_launcher_selects_existing_server_or_watched_test_server(tmp_path, reload_enabled):
    root = Path(__file__).resolve().parents[1]
    launcher = tmp_path / 'run.ps1'
    launcher.write_bytes((root / 'run.ps1').read_bytes())
    (tmp_path / 'data/grt').mkdir(parents=True)
    (tmp_path / 'data/grt/current.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'src/examsage').mkdir(parents=True)
    output = tmp_path / 'arguments.json'
    probe = tmp_path / 'record-arguments.ps1'
    probe.write_text("$args | ConvertTo-Json -Compress | Set-Content -LiteralPath $env:EXAMSAGE_TEST_ARGS_PATH -Encoding UTF8\nexit 0\n", encoding='utf-8')
    env = safe_environment(); env['EXAMSAGE_TEST_ARGS_PATH'] = str(output)
    command = [shutil.which('powershell.exe'), '-NoProfile', '-ExecutionPolicy', 'Bypass',
               '-File', str(launcher), '-Action', 'serve', '-Port', '8768', '-PythonPath', str(probe)]
    if reload_enabled: command.append('-Reload')
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
    args = [str(value) for value in json.loads(output.read_text(encoding='utf-8-sig'))]
    assert args[:3] == ['-X', 'utf8', '-m']
    assert args[args.index('--port') + 1] == '8768'
    if reload_enabled:
        assert args[3:5] == ['uvicorn', 'examsage.devserver:create_app']
        assert '--factory' in args and '--reload' in args
        assert Path(args[args.index('--reload-dir') + 1]) == tmp_path / 'src/examsage'
        assert args[args.index('--host') + 1] == '127.0.0.1'
    else:
        assert args[3:5] == ['examsage', 'serve'] and '--reload' not in args


def test_reload_factory_uses_existing_five_course_application(monkeypatch):
    from examsage import devserver
    called = []
    sentinel = object()
    monkeypatch.setattr(devserver, 'create_library_app', lambda data: called.append(data) or sentinel)
    assert devserver.create_app() is sentinel
    assert called == [Path(devserver.__file__).resolve().parents[2] / 'data' / 'grt']
