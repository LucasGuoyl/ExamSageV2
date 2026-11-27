"""Exercise the updater without writing personal Codex configuration."""
import copy
import json
from pathlib import Path

import pytest

from test_plugin_registration import implementation


class InstallCli:
    """Official CLI boundary: add copies a version, enables it, and list observes it."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.error_on = None
        self.unchanged_on = None
        self.disabled_on = None
        self.target_version = '0.2.0'
        self.rows = []
        for name, folder, installed in [
            ('examsage-courses', 'plugin-existing-courses', True),
            ('examsage-demo-courses', 'plugin-demo-courses', False),
        ]:
            self.rows.append({
                'pluginId': name+'@examsage-local-pilot', 'name': name,
                'marketplaceName': 'examsage-local-pilot',
                'version': '0.1.0' if installed else '0.2.0',
                'installed': installed, 'enabled': installed,
                'source': {'source': 'local', 'path': str(root/folder)},
                'marketplaceSource': {'sourceType': 'local', 'source': str(root)},
                'installPolicy': 'AVAILABLE', 'authPolicy': 'ON_INSTALL',
            })

    def __call__(self, *args):
        self.calls.append(args)
        if args == ('marketplace', 'list', '--json'):
            return {'marketplaces': [{'name': 'examsage-local-pilot', 'root': str(self.root)}]}
        if args == ('list', '--marketplace', 'examsage-local-pilot', '--available', '--json'):
            return copy.deepcopy({'installed': [r for r in self.rows if r['installed']],
                                  'available': [r for r in self.rows if not r['installed']]})
        if len(args) == 3 and args[0] == 'add' and args[2] == '--json':
            row = next(r for r in self.rows if r['pluginId'] == args[1])
            if row['name'] == self.error_on:
                raise RuntimeError('installation interrupted')
            if row['name'] != self.unchanged_on:
                row.update(version=self.target_version, installed=True,
                           enabled=row['name'] != self.disabled_on)
            return {key: row[key] for key in ('pluginId', 'name', 'marketplaceName', 'version', 'authPolicy')} | {
                'installedPath': str(Path('cache')/row['name']/row['version'])}
        raise AssertionError('Unapproved command: '+repr(args))


def test_install_upgrades_existing_and_installs_demo_without_unregistering(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    result = mod.install_plugins(cli, cli.root)
    assert result['status'] == 'installed_restart_required'
    assert [(r['name'], r['version'], r['installed'], r['enabled'])
            for r in result['plugins']['installed']] == [
        ('examsage-courses', '0.2.0', True, True),
        ('examsage-demo-courses', '0.2.0', True, True)]
    assert [c for c in cli.calls if c[0] == 'add'] == [
        ('add', 'examsage-courses@examsage-local-pilot', '--json'),
        ('add', 'examsage-demo-courses@examsage-local-pilot', '--json')]


def test_already_installed_enabled_versions_do_not_reinstall(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    for row in cli.rows:
        row.update(version='0.2.0', installed=True, enabled=True)
    result = mod.install_plugins(cli, cli.root)
    assert result['status'] == 'installed_restart_required'
    assert not any(c[0] == 'add' for c in cli.calls)


def test_first_install_failure_stops_before_demo_and_preserves_observed_state(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    cli.error_on = 'examsage-courses'
    result = mod.install_plugins(cli, cli.root)
    assert result['status'] == 'installation_failed'
    assert 'interrupted' in result['error']
    assert result['plugins']['installed'][0]['version'] == '0.1.0'
    assert len([c for c in cli.calls if c[0] == 'add']) == 1


def test_second_failure_reports_partial_installation_without_rollback(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    cli.error_on = 'examsage-demo-courses'
    result = mod.install_plugins(cli, cli.root)
    assert result['status'] == 'installation_failed'
    assert result['plugins']['installed'][0]['version'] == '0.2.0'
    assert result['plugins']['available'][0]['installed'] is False


@pytest.mark.parametrize('bad_result', ['unchanged_on', 'disabled_on'])
def test_zero_exit_does_not_hide_old_version_or_disabled_state(tmp_path, bad_result):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    setattr(cli, bad_result, 'examsage-courses')
    result = mod.install_plugins(cli, cli.root)
    assert result['status'] == 'installation_failed'
    assert len([c for c in cli.calls if c[0] == 'add']) == 1


def test_wrong_registered_root_is_refused_without_installation(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-7')
    result = mod.install_plugins(cli, tmp_path/'candidate-9')
    assert result['status'] == 'installation_failed'
    assert not any(c[0] == 'add' for c in cli.calls)


@pytest.mark.parametrize('problem', ['source', 'duplicate', 'missing', 'identity'])
def test_bad_catalog_is_refused_before_any_installation(tmp_path, problem):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    if problem == 'source':
        cli.rows[1]['source']['path'] = str(tmp_path/'unreviewed')
    elif problem == 'duplicate':
        cli.rows.append(copy.deepcopy(cli.rows[0]))
    elif problem == 'missing':
        cli.rows.pop()
    else:
        cli.rows[1]['pluginId'] = 'examsage-demo-courses@another-market'
    result = mod.install_plugins(cli, cli.root)
    assert result['status'] == 'installation_failed'
    assert not any(c[0] == 'add' for c in cli.calls)


def test_changed_root_between_installs_stops_without_removal(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-9')
    expected = cli.root
    def run(*args):
        value = cli(*args)
        if args[:2] == ('add', 'examsage-courses@examsage-local-pilot'):
            cli.root = tmp_path/'another-source'
        return value
    result = mod.install_plugins(run, expected)
    assert result['status'] == 'installation_failed'
    assert len([c for c in cli.calls if c[0] == 'add']) == 1


def test_readonly_main_does_not_claim_plugin_installation(tmp_path, monkeypatch, capsys):
    mod = implementation()
    monkeypatch.setattr(mod, 'registered_cli', lambda: tmp_path/'codex.exe')
    monkeypatch.setattr(mod, 'QA', tmp_path)
    monkeypatch.setattr(mod, 'validate_candidate', lambda _, **kwargs: None)
    cli = InstallCli(tmp_path/'candidate-9')
    monkeypatch.setattr(mod.subprocess, 'run', lambda cmd, **kwargs: type('Result', (), {
        'returncode': 0, 'stdout': json.dumps(cli(*cmd[2:])), 'stderr': ''})())
    monkeypatch.setattr('sys.argv', ['register_course_plugin.py'])
    assert mod.main() == 0
    assert not any(c[0] == 'add' for c in cli.calls)
    assert '0.1.0' in capsys.readouterr().out


def test_install_main_records_failure_and_returns_nonzero(tmp_path, monkeypatch):
    mod = implementation()
    monkeypatch.setattr(mod, 'registered_cli', lambda: tmp_path/'codex.exe')
    monkeypatch.setattr(mod, 'QA', tmp_path)
    monkeypatch.setattr(mod, 'validate_candidate', lambda _, **kwargs: None)
    cli = InstallCli(tmp_path/'candidate-9')
    cli.error_on = 'examsage-demo-courses'
    def run(cmd, **kwargs):
        try:
            value, error, code = cli(*cmd[2:]), '', 0
        except RuntimeError as exc:
            value, error, code = {}, str(exc), 1
        return type('Result', (), {'returncode': code, 'stdout': json.dumps(value), 'stderr': error})()
    monkeypatch.setattr(mod.subprocess, 'run', run)
    monkeypatch.setattr('sys.argv', ['register_course_plugin.py', '--install'])
    assert mod.main() == 1
    reports = list((tmp_path/'installation-fix').glob('*.json'))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding='utf-8'))
    assert report['status'] == 'installation_failed'
    assert report['plugins']['installed'][0]['version'] == '0.2.0'


def test_namespace_patch_version_is_actually_installed_and_verified(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'candidate-10')
    cli.target_version = '0.2.1'
    for row in cli.rows:
        row.update(version='0.2.0', installed=True, enabled=True)
    result = mod.install_plugins(cli, cli.root, expected_version='0.2.1')
    assert result['status'] == 'installed_restart_required'
    assert [r['version'] for r in result['plugins']['installed']] == ['0.2.1','0.2.1']
    assert len([c for c in cli.calls if c[0] == 'add']) == 2


def test_candidate10_preflight_accepts_only_its_reviewed_version(tmp_path):
    from hashlib import sha256
    from test_plugin_registration import candidate_fixture
    mod = implementation()
    root = candidate_fixture(tmp_path)
    with pytest.raises(RuntimeError, match='version'):
        mod.validate_candidate(root, expected_version='0.2.1')
    hashes = {}
    for folder in ['plugin-existing-courses','plugin-demo-courses']:
        p = root/folder/'plugin.json'
        manifest = json.loads(p.read_text(encoding='utf-8'))
        manifest['version'] = '0.2.1'
        p.write_text(json.dumps(manifest),encoding='utf-8')
        hashes[p.relative_to(root).as_posix()] = sha256(p.read_bytes()).hexdigest()
    (root/'verification.json').write_text(json.dumps({'package_hashes':hashes}),encoding='utf-8')
    mod.validate_candidate(root, expected_version='0.2.1')


def test_candidate10_install_entry_uses_new_root_and_version(tmp_path, monkeypatch):
    mod = implementation()
    monkeypatch.setattr(mod, 'registered_cli', lambda: tmp_path/'codex.exe')
    monkeypatch.setattr(mod, 'QA', tmp_path)
    preflights = []
    def preflight(root, expected_version='0.2.0'):
        preflights.append((root.name,expected_version))
    monkeypatch.setattr(mod, 'validate_candidate', preflight)
    cli = InstallCli(tmp_path/'candidate-10')
    cli.target_version = '0.2.1'
    monkeypatch.setattr(mod.subprocess, 'run', lambda cmd, **kwargs: type('Result', (), {
        'returncode':0,'stdout':json.dumps(cli(*cmd[2:])), 'stderr':''})())
    monkeypatch.setattr('sys.argv',['register_course_plugin.py','--candidate','candidate-10','--install'])
    assert mod.main() == 0
    assert preflights == [('candidate-10','0.2.1')]
    assert all(r['version']=='0.2.1' and r['enabled'] for r in cli.rows)


def test_student_update_accepts_the_pilot_upgrade_and_preserves_unexpected_marketplace(tmp_path):
    from test_plugin_registration import Cli
    mod = implementation()
    target = 'round32-students/candidate-final-0.5.0'
    previous, version = mod.TARGETS[target]
    assert version == '0.5.0'
    old = tmp_path/'candidate-10'
    new = tmp_path/target
    new.mkdir(parents=True)
    cli = Cli(old)
    assert mod.register(cli,tmp_path/previous,new,apply=True)['current_root']==mod.normalized(new)
    other = Cli(tmp_path/'different-marketplace')
    with pytest.raises(RuntimeError,match='Unexpected marketplace'):
        mod.register(other,tmp_path/previous,new,apply=True)
    assert other.calls==[('marketplace','list','--json')]


def test_both_plugins_must_be_enabled_together_at_end_of_update(tmp_path):
    mod = implementation()
    cli = InstallCli(tmp_path/'student-candidate')
    cli.target_version = '0.5.0'
    for row in cli.rows:
        row.update(version='0.2.1',installed=True,enabled=True)
    def refresh(*args):
        result = cli(*args)
        if args[:2] == ('add','examsage-demo-courses@examsage-local-pilot'):
            cli.rows[0]['enabled'] = False
        return result
    result = mod.install_plugins(refresh,cli.root,'0.5.0')
    assert result['status']=='installation_failed'
    assert [row['enabled'] for row in result['plugins']['installed']]==[False,True]


def test_student_review_upgrade_selects_new_candidate_and_refreshes_both_plugins(tmp_path):
    from test_plugin_registration import Cli
    mod = implementation()
    target = 'round43-student-plugin/candidate-0.6.0'
    previous, version = mod.TARGETS[target]
    assert previous == 'round32-students/candidate-final-0.5.0'
    old, new = tmp_path / previous, tmp_path / target
    catalog = Cli(old)
    mod.register(catalog, old, new, apply=True)
    assert catalog.current == new
    cli = InstallCli(new)
    cli.target_version = version
    for row in cli.rows:
        row.update(version='0.5.0', installed=True, enabled=True)
    report = mod.install_plugins(cli, new, expected_version=version)
    assert report['status'] == 'installed_restart_required'
    assert [(row['version'], row['enabled']) for row in cli.rows] == [('0.6.0', True)] * 2
    calls_before = cli.calls.count(('add', 'examsage-courses@examsage-local-pilot', '--json'))
    mod.install_plugins(cli, new, expected_version=version)
    assert calls_before == cli.calls.count(('add', 'examsage-courses@examsage-local-pilot', '--json')) == 1
