"""Local registration orchestration; fake CLI prevents personal config writes."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def implementation():
    spec = importlib.util.spec_from_file_location('registration', ROOT/'tools/register_course_plugin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Cli:
    """Model the documented same-name conflict and observable source state."""
    def __init__(self, current, fail=None):
        self.current = current
        self.fail = fail
        self.calls = []
        self.enabled_plugins = {'examsage-courses': True}

    def __call__(self, *args):
        self.calls.append(args)
        if args == ('marketplace','list','--json'):
            return {'marketplaces':[] if self.current is None else [
                {'name':'examsage-local-pilot','root':str(self.current)}]}
        if args[0] == 'list':
            if self.fail == 'catalog':
                raise RuntimeError('catalog unavailable')
            return {'installed':[{'name':'examsage-courses','version':'0.1.0','enabled':True}],
                    'available':[{'name':'examsage-demo-courses','version':'0.2.0'}]}
        if args[:2] == ('marketplace','remove'):
            assert args == ('marketplace','remove','examsage-local-pilot','--json')
            if self.fail == 'remove':
                raise RuntimeError('configured in another layer')
            self.current = None
            return {'removed':True}
        if args[:2] == ('marketplace','add'):
            target = Path(args[2])
            if self.current is not None and self.current != target:
                raise RuntimeError('already added from a different source; remove it before adding this source')
            if self.fail == 'add' and target.name == 'candidate-9':
                raise RuntimeError('new registration failed')
            if self.fail != 'no_change':
                self.current = target
            return {}
        raise AssertionError('Unexpected command: '+repr(args))


def test_existing_same_name_is_replaced_without_changing_plugin_enablement(tmp_path):
    mod = implementation()
    old, new = tmp_path/'candidate-7', tmp_path/'candidate-9'
    cli = Cli(old)
    result = mod.register(cli, old, new, apply=True)
    assert cli.current == new
    assert cli.enabled_plugins == {'examsage-courses':True}
    assert result['status'] == 'registered_restart_required'
    assert result['plugins']['installed'][0]['version'] == '0.1.0'


def test_default_diagnostic_does_not_write_registration(tmp_path):
    mod = implementation()
    cli = Cli(tmp_path/'candidate-7')
    result = mod.register(cli, tmp_path/'candidate-7', tmp_path/'candidate-9', apply=False)
    assert result['status'] == 'registration_required'
    assert all(call[:2] == ('marketplace','list') for call in cli.calls)


@pytest.mark.parametrize('initial', ['new','absent'])
def test_new_source_or_absent_source_needs_no_removal(tmp_path, initial):
    mod = implementation()
    new = tmp_path/'candidate-9'
    cli = Cli(new if initial == 'new' else None)
    assert mod.register(cli,tmp_path/'candidate-7',new,apply=True)['status'] == 'registered_restart_required'
    assert not any(call[:2] == ('marketplace','remove') for call in cli.calls)


def test_unknown_source_is_refused_before_mutation(tmp_path):
    mod = implementation()
    cli = Cli(tmp_path/'another-source')
    with pytest.raises(RuntimeError, match='Unexpected marketplace source'):
        mod.register(cli,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)
    assert len(cli.calls) == 1


def test_remove_failure_does_not_attempt_add(tmp_path):
    mod = implementation()
    cli = Cli(tmp_path/'candidate-7','remove')
    with pytest.raises(RuntimeError, match='another layer'):
        mod.register(cli,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)
    assert cli.current == tmp_path/'candidate-7'
    assert not any(call[:2] == ('marketplace','add') for call in cli.calls)


def test_failed_new_registration_restores_known_old_source(tmp_path):
    mod = implementation()
    cli = Cli(tmp_path/'candidate-7','add')
    with pytest.raises(RuntimeError, match='old source restored'):
        mod.register(cli,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)
    assert cli.current == tmp_path/'candidate-7'


def test_zero_exit_without_expected_root_is_not_success(tmp_path):
    mod = implementation()
    cli = Cli(None,'no_change')
    with pytest.raises(RuntimeError, match='root verification failed'):
        mod.register(cli,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)


def test_catalog_failure_does_not_remove_newly_registered_source(tmp_path):
    mod = implementation()
    cli = Cli(tmp_path/'candidate-7','catalog')
    with pytest.raises(RuntimeError, match='catalog unavailable'):
        mod.register(cli,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)
    assert cli.current == tmp_path/'candidate-9'
    assert sum(c[:2] == ('marketplace','remove') for c in cli.calls) == 1


@pytest.mark.parametrize('rows', [None, ['bad'], [{'name':'examsage-local-pilot'}],
                                    [{'name':'examsage-local-pilot','root':'one'},
                                     {'name':'examsage-local-pilot','root':'two'}]])
def test_malformed_or_ambiguous_discovery_never_changes_configuration(tmp_path, rows):
    mod = implementation()
    calls = []
    def run(*args):
        calls.append(args)
        return {'marketplaces':rows}
    with pytest.raises(RuntimeError):
        mod.register(run,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)
    assert calls == [('marketplace','list','--json')]


def test_concurrent_unexpected_source_is_not_removed_or_overwritten(tmp_path):
    mod = implementation()
    cli = Cli(tmp_path/'candidate-7')
    def run(*args):
        value = cli(*args)
        if args[:2] == ('marketplace','remove'):
            cli.current = tmp_path/'concurrent-source'
        return value
    with pytest.raises(RuntimeError, match='No automatic rollback'):
        mod.register(run,tmp_path/'candidate-7',tmp_path/'candidate-9',apply=True)
    assert cli.current == tmp_path/'concurrent-source'
    assert sum(c[:2] == ('marketplace','remove') for c in cli.calls) == 1


def candidate_fixture(tmp_path):
    import json
    from hashlib import sha256
    root = tmp_path/'candidate'
    catalog = root/'.agents/plugins/marketplace.json'
    catalog.parent.mkdir(parents=True)
    pairs = [('examsage-courses','plugin-existing-courses'),('examsage-demo-courses','plugin-demo-courses')]
    rows, hashes = [], {}
    for name, folder in pairs:
        p = root/folder/'plugin.json'
        p.parent.mkdir()
        p.write_text(json.dumps({'name':name,'version':'0.2.0'}),encoding='utf-8')
        hashes[p.relative_to(root).as_posix()] = sha256(p.read_bytes()).hexdigest()
        rows.append({'name':name,'source':{'source':'local','path':'./'+folder}})
    catalog.write_text(json.dumps({'name':'examsage-local-pilot','plugins':rows}),encoding='utf-8')
    (root/'verification.json').write_text(json.dumps({'package_hashes':hashes}),encoding='utf-8')
    return root


def test_candidate_preflight_accepts_intact_manifests_and_rejects_changed_bytes(tmp_path):
    mod = implementation()
    root = candidate_fixture(tmp_path)
    mod.validate_candidate(root)
    p = root/'plugin-existing-courses/plugin.json'
    p.write_text(p.read_text(encoding='utf-8')+' ',encoding='utf-8')
    with pytest.raises(RuntimeError, match='integrity'):
        mod.validate_candidate(root)


def test_candidate_preflight_rejects_duplicate_identity(tmp_path):
    import json
    mod = implementation()
    root = candidate_fixture(tmp_path)
    p = root/'.agents/plugins/marketplace.json'
    value = json.loads(p.read_text(encoding='utf-8'))
    value['plugins'][1] = value['plugins'][0]
    p.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(RuntimeError, match='incomplete'):
        mod.validate_candidate(root)


def test_candidate_preflight_rejects_incomplete_hash_coverage(tmp_path):
    import json
    mod = implementation()
    root = candidate_fixture(tmp_path)
    p = root/'verification.json'
    value = json.loads(p.read_text(encoding='utf-8'))
    value['package_hashes'].pop('plugin-demo-courses/plugin.json')
    p.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(RuntimeError, match='coverage'):
        mod.validate_candidate(root)
