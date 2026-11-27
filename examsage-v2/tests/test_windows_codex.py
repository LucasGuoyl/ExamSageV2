from pathlib import Path

from test_plugin_registration import implementation


def test_newest_registered_desktop_with_cli_is_selected(tmp_path,monkeypatch):
    from examsage import windows_codex
    installs = {}
    for version, has_cli in [('26.9.1.0',True),('26.11.2.0',True),('26.12.0.0',False)]:
        name = f'OpenAI.Codex_{version}_x64__2p2nqsd0c76g0'
        root = tmp_path/name
        if has_cli:
            path = root/'app'/'resources'/'codex.exe'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'fixture; never executed')
        installs[name] = root
    monkeypatch.setattr(windows_codex,'_package_names',lambda:list(installs))
    monkeypatch.setattr(windows_codex,'_install_path',installs.get)
    expected = installs['OpenAI.Codex_26.11.2.0_x64__2p2nqsd0c76g0']/'app'/'resources'/'codex.exe'
    assert windows_codex.registered_cli() == expected
    assert implementation().registered_cli() == expected


def test_web_runtime_with_stale_hint_uses_registered_desktop(tmp_path,monkeypatch):
    from examsage import model_runtime
    import json
    (tmp_path/'codex-program.json').write_text(json.dumps({'executable':str(tmp_path/'old'/'codex.exe')}))
    current = tmp_path/'current'/'codex.exe'
    current.parent.mkdir()
    current.touch()
    monkeypatch.setattr(model_runtime.shutil,'which',lambda _:None)
    monkeypatch.setattr(model_runtime,'registered_cli',lambda:current)
    assert Path(model_runtime.resolve_program(tmp_path))==current
