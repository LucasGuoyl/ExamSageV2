"""Exercise local catalog selection and the packages it actually launches."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from examsage.domain import Scope
from examsage.plugin_package import build_package
from test_core import example


ROOT = Path(__file__).resolve().parents[1]
REAL_IDS = ['grt', 'geodynamics', 'planetary_science', 'sea_level', 'ses']
DEMO_IDS = ['demo-physics', 'demo-mathematics', 'demo-literature', 'demo-history']


def candidate_source(tmp_path):
    root = tmp_path/'source'
    data = root/'data'
    for cid in REAL_IDS:
        store, manifest, record = example(data/cid)
        manifest.course_key = cid
        snapshot = store.publish('fixture', manifest, [record], [], {})
        scope = Scope(workspace='fixture', course=cid, snapshot=snapshot, allowed_sources=['doc'])
        (data/cid/'current.json').write_text(scope.model_dump_json(), encoding='utf-8')
    (data/'library.json').write_text(json.dumps({'courses':[{'slug':c,'data':c} for c in REAL_IDS]}),encoding='utf-8')
    shutil.copytree(ROOT/'examples/course-packs', root/'examples/course-packs')
    return root


def list_packaged_courses(folder, connection=None):
    if connection is None:
        connection = next(iter(json.loads((folder/'mcp.json').read_text(encoding='utf-8'))['mcpServers'].values()))
    command = [str(folder/connection['command']),
               *[a.replace('${PLUGIN_ROOT}', str(folder)) for a in connection['args']]]
    messages = [{'id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},
        'clientInfo':{'name':'catalog-selection-test','version':'1'}}},
        {'method':'notifications/initialized'},
        {'id':2,'method':'tools/call','params':{'name':'list_courses','arguments':{}}}]
    env = {k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','TEMP','TMP') if k in os.environ}
    run = subprocess.run(command, input=''.join(json.dumps({'jsonrpc':'2.0',**m})+'\n' for m in messages),
        cwd=folder.parent,env=env,text=True,encoding='utf-8',capture_output=True,timeout=15)
    assert run.returncode == 0, run.stderr
    manifest = json.loads((folder/'plugin.json').read_text(encoding='utf-8'))
    assert json.loads(run.stdout.splitlines()[0])['result']['serverInfo']['version'] == manifest['version']
    result = json.loads(run.stdout.splitlines()[-1])['result']
    assert not result.get('isError')
    return result['structuredContent']['courses']


def test_catalog_can_select_real_and_demo_plugins_without_identity_collision(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('prepare_course_plugin_candidate', ROOT/'tools/prepare_course_plugin_candidate.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    monkeypatch.setattr(prepare, 'ROOT', candidate_source(tmp_path))
    output = tmp_path/'candidate'
    prepare.prepare(output)
    catalog = json.loads((output/'.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
    entries = {entry['name']:entry for entry in catalog['plugins']}
    assert len(entries) == len(catalog['plugins']) == 2
    assert set(entries) == {'examsage-courses','examsage-demo-courses'}
    for name, expected in [('examsage-courses', REAL_IDS), ('examsage-demo-courses', DEMO_IDS)]:
        folder = (output/entries[name]['source']['path']).resolve()
        assert folder.is_relative_to(output.resolve())
        for manifest_path in ['plugin.json','.codex-plugin/plugin.json']:
            assert json.loads((folder/manifest_path).read_text(encoding='utf-8'))['name'] == name
        # Resolve the catalog entry and run its launcher, not a substitute server.
        courses = list_packaged_courses(folder)
        assert {c['course_id'] for c in courses} == set(expected)
        if name == 'examsage-demo-courses':
            assert all(c['profile']['material_status']=='demonstration' for c in courses)


@pytest.mark.parametrize('name', ['../escape', 'With Space', 'UPPERCASE', '', 'a'*65])
def test_invalid_package_identity_is_rejected_before_output_is_written(tmp_path, name):
    root = candidate_source(tmp_path)
    output = tmp_path/'output'
    with pytest.raises(ValueError):
        build_package(output, root/'data', REAL_IDS, Path(sys.executable), plugin_name=name)
    assert not output.exists()


@pytest.mark.parametrize('config_file', ['mcp.json', '.mcp.json'])
def test_both_plugins_remain_reachable_when_host_merges_servers_by_name(tmp_path, monkeypatch, config_file):
    # Codex load_outcome::effective_mcp_servers keeps the first server per name.
    # Run both emitted launchers after this documented merge, not separately.
    spec = importlib.util.spec_from_file_location('prepare_combined', ROOT/'tools/prepare_course_plugin_candidate.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    monkeypatch.setattr(prepare, 'ROOT', candidate_source(tmp_path))
    output = tmp_path/'candidate'
    prepare.prepare(output)
    catalog = json.loads((output/'.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
    merged = {}
    for entry in sorted(catalog['plugins'], key=lambda e:e['name']):
        folder = (output/entry['source']['path']).resolve()
        for server, connection in json.loads((folder/config_file).read_text(encoding='utf-8'))['mcpServers'].items():
            merged.setdefault(server, (folder, connection))
    found = [set(c['course_id'] for c in list_packaged_courses(folder, connection))
             for folder, connection in merged.values()]
    assert len(found) == 2, 'A duplicate server name hid one installed plugin'
    assert set(REAL_IDS) in found
    assert set(DEMO_IDS) in found


def test_student_release_is_ready_for_integrity_preflight_on_both_packages(tmp_path, monkeypatch, capsys):
    from test_plugin_registration import implementation
    spec = importlib.util.spec_from_file_location('prepare_student', ROOT/'tools/prepare_course_plugin_candidate.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    monkeypatch.setattr(prepare, 'ROOT', candidate_source(tmp_path))
    target = tmp_path / 'student-release'
    prepare.prepare(target)
    summary = json.loads(capsys.readouterr().out)
    assert summary['courses'] == len(DEMO_IDS)
    installer = implementation()
    installer.validate_candidate(target, '0.6.2')
    for folder in ('plugin-existing-courses', 'plugin-demo-courses'):
        package = target / folder
        manifest = json.loads((package / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        assert manifest['version'] == '0.6.2'
    module = target / 'plugin-demo-courses/vendor/examsage/exam_outlook.py'
    with module.open('ab') as changed:
        changed.write(b'\n# modified after packaging\n')
    with pytest.raises(RuntimeError, match='integrity'):
        installer.validate_candidate(target, '0.6.2')


def test_new_candidate_preflight_includes_the_demo_library(tmp_path, monkeypatch):
    from test_plugin_registration import implementation
    spec = importlib.util.spec_from_file_location('prepare_demo_assets',ROOT/'tools/prepare_course_plugin_candidate.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    monkeypatch.setattr(prepare,'ROOT',candidate_source(tmp_path))
    output = tmp_path/'candidate'
    prepare.prepare(output)
    version=json.loads((output/'plugin-demo-courses/plugin.json').read_text(encoding='utf8'))['version']
    file=next((output/'demo-library/demo-physics/assets/sources').glob('*.txt'))
    file.write_bytes(file.read_bytes()+b'changed')
    with pytest.raises(RuntimeError,match='integrity'):
        implementation().validate_candidate(output,version)

def test_deep_candidate_preserves_all_demo_originals(tmp_path, monkeypatch):
    from examsage.source_paths import source_path
    from test_plugin_registration import implementation
    spec = importlib.util.spec_from_file_location('deep_candidate', ROOT/'tools/prepare_course_plugin_candidate.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, 'ROOT', candidate_source(tmp_path))
    target = tmp_path / ('d' * max(1, 156 - len(str(tmp_path)))) / 'candidate'
    builder.prepare(target)
    inventory = json.loads((target/'verification.json').read_text(encoding='utf8'))['demo_library_hashes']
    extended = source_path(target)
    originals = [p for p in extended.glob('demo-library/*/assets/sources/*') if p.is_file()]
    assert originals and max(len(str(target/p.relative_to(extended))) for p in originals) >= 260
    assert all(p.relative_to(extended).as_posix() in inventory for p in originals)
    implementation().validate_candidate(target, '0.6.2')
