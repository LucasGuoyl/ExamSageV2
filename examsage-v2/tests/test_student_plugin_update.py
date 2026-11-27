"""Student update paths exercise the real entry point against simulated official CLI responses."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_plugin_installation import InstallCli
from test_plugin_registration import Cli, implementation

PREVIOUS='round48-student-release/candidate-0.6.1'
TARGET='round49-groundwater-age/candidate-0.6.2'
OLD='round32-students/candidate-final-0.5.0'
LAST='round43-student-plugin/candidate-0.6.0'


def run_entry(mod, qa, cli, mode, monkeypatch):
    monkeypatch.setattr(mod,'QA',qa)
    monkeypatch.setattr(mod,'registered_cli',lambda:Path('simulated-codex.exe'))
    monkeypatch.setattr(mod,'validate_candidate',lambda folder,expected_version: (
        None if folder==qa/TARGET and expected_version=='0.6.2' else pytest.fail('wrong preflight')))
    def invoke(cmd,**kwargs):
        assert cmd[:2]==['simulated-codex.exe','plugin']
        return SimpleNamespace(returncode=0,stdout=json.dumps(cli(*cmd[2:])),stderr='')
    monkeypatch.setattr(mod.subprocess,'run',invoke)
    monkeypatch.setattr('sys.argv',['register_course_plugin.py','--candidate',TARGET,mode])
    return mod.main()


@pytest.mark.parametrize('start',[OLD,LAST,PREVIOUS,None,TARGET])
def test_student_entry_can_update_directly_from_supported_state(tmp_path,monkeypatch,start):
    mod=implementation()
    root=tmp_path/TARGET
    cli=Cli(tmp_path/start if start else None)
    assert run_entry(mod,tmp_path,cli,'--apply',monkeypatch)==0
    assert cli.current==root
    assert sum(call[:2]==('marketplace','remove') for call in cli.calls)==int(start in {OLD,LAST,PREVIOUS})
    install=InstallCli(root)
    install.target_version='0.6.2'
    for row in install.rows:
        row.update(version='0.5.0',installed=True,enabled=True)
    assert run_entry(mod,tmp_path,install,'--install',monkeypatch)==0
    assert all(row['enabled'] and row['version']=='0.6.2' for row in install.rows)
    assert len(list((root.parent/'desktop-diagnostics').glob('*.json')))>=2


@pytest.mark.parametrize('start',[OLD,LAST,PREVIOUS])
def test_failed_switch_restores_the_exact_previous_registration(tmp_path,monkeypatch,start):
    cli=Cli(tmp_path/start)
    def interrupted(*args):
        if args[:3]==('marketplace','add',str(tmp_path/TARGET)):
            raise RuntimeError('interrupted before registration')
        return cli(*args)
    assert run_entry(implementation(),tmp_path,interrupted,'--apply',monkeypatch)==1
    assert cli.current==tmp_path/start
    assert all(c[0]!='add' for c in cli.calls)


def test_unrecognized_registration_is_preserved(tmp_path,monkeypatch):
    cli=Cli(tmp_path/'unrelated')
    assert run_entry(implementation(),tmp_path,cli,'--apply',monkeypatch)==1
    assert cli.current==tmp_path/'unrelated' and cli.calls==[('marketplace','list','--json')]

@pytest.mark.parametrize('start', [OLD, LAST, PREVIOUS])
@pytest.mark.parametrize('observed', ['absent', 'unchanged', 'different'])
def test_remove_lost_response_preserves_observed_registration(tmp_path, monkeypatch, start, observed):
    previous = tmp_path / start
    cli = Cli(previous)
    other = tmp_path / 'another-marketplace'
    def lost_reply(*args):
        if args[:2] == ('marketplace', 'remove'):
            if observed != 'unchanged':
                cli(*args)
                if observed == 'different':
                    cli.current = other
            raise TimeoutError('Marketplace removal response lost')
        return cli(*args)
    assert run_entry(implementation(), tmp_path, lost_reply, '--apply', monkeypatch) == 1
    assert cli.current == (other if observed == 'different' else previous)
    adds = [cmd[2] for cmd in cli.calls if cmd[:2] == ('marketplace', 'add')]
    assert adds == ([str(previous)] if observed == 'absent' else [])
