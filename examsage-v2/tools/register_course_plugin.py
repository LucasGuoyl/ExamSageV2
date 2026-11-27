"""Diagnose by default. Explicit user modes register or install reviewed plugins.

Run --apply/--install only from the user's entries, never from agent checks.
Uses official CLI commands; does not read config/credentials or uninstall plugins.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from examsage.windows_codex import registered_cli
from examsage.source_paths import source_path

QA = ROOT/'data/qa/plugin-20261116'
MARKETPLACE = 'examsage-local-pilot'
PLUGINS = {'examsage-courses':'plugin-existing-courses', 'examsage-demo-courses':'plugin-demo-courses'}
TARGETS = {'candidate-9':('candidate-7','0.2.0'), 'candidate-10':('candidate-9','0.2.1'),
           'round32-students/candidate-final-0.5.0':('candidate-10','0.5.0'),
           'round43-student-plugin/candidate-0.6.0':('round32-students/candidate-final-0.5.0','0.6.0'),
           'round48-student-release/candidate-0.6.1':(
               ('round32-students/candidate-final-0.5.0','round43-student-plugin/candidate-0.6.0'),'0.6.1'),
           'round49-groundwater-age/candidate-0.6.2':(
               ('round32-students/candidate-final-0.5.0','round43-student-plugin/candidate-0.6.0',
                'round48-student-release/candidate-0.6.1'),'0.6.2')}


def normalized(value):
    value = str(value)
    if value.startswith('\\\\?\\'):
        value = value[4:]
    return os.path.normcase(str(Path(value).resolve()))


def current_root(run):
    value = run('marketplace', 'list', '--json')
    rows = value.get('marketplaces')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError('Malformed marketplace list; no change authorized')
    matches = [row for row in rows if str(row.get('name', '')).casefold() == MARKETPLACE]
    if len(matches) > 1:
        raise RuntimeError('Ambiguous marketplace sources; no change authorized')
    if not matches:
        return None
    root = matches[0].get('root')
    if not isinstance(root, str) or not root.strip():
        raise RuntimeError('Missing marketplace root; no change authorized')
    return normalized(root)


def register(run, old_root, new_root, *, apply=False):
    roots = old_root if isinstance(old_root,tuple) else (old_root,)
    predecessors = {normalized(root):root for root in roots}
    new = normalized(new_root)
    before = current_root(run)
    if before is not None and before != new and before not in predecessors:
        raise RuntimeError('Unexpected marketplace source; leaving registration unchanged')
    if before != new and not apply:
        return {'status':'registration_required', 'current_root':before, 'expected_root':new}
    replacing_known_source = before != new and before in predecessors
    try:
        if replacing_known_source:
            # The CLI may apply removal even when its response is lost.
            run('marketplace', 'remove', MARKETPLACE, '--json')
        if before != new:
            run('marketplace', 'add', str(new_root), '--json')
        if current_root(run) != new:
            raise RuntimeError('Registration root verification failed')
        plugins = run('list', '--marketplace', MARKETPLACE, '--available', '--json')
        if not isinstance(plugins.get('installed'), list) or not isinstance(plugins.get('available'), list):
            raise RuntimeError('Malformed plugin list after registration')
    except Exception as error:
        # Restore only a known source we removed, only while the name is absent.
        # Never remove a new/unexpected registration to force a rollback.
        recovery = 'No automatic rollback performed'
        if replacing_known_source:
            try:
                if current_root(run) is None:
                    run('marketplace', 'add', str(predecessors[before]), '--json')
                    recovery = ('old source restored' if current_root(run) == before
                                else 'Old-source restoration could not be verified')
            except Exception as rollback_error:
                recovery = 'Restoration failed: '+str(rollback_error)
        raise RuntimeError(str(error)+'; '+recovery) from error
    return {'status':'registered_restart_required', 'current_root':new,
            'previous_root':before, 'plugins':plugins,
            'notice':'Registration verified. Actual desktop version/tools still need verification after restart.'}


def validate_candidate(root, expected_version='0.2.0'):
    catalog = json.loads((root/'.agents/plugins/marketplace.json').read_text(encoding='utf-8'))
    expected = {'examsage-courses':'plugin-existing-courses', 'examsage-demo-courses':'plugin-demo-courses'}
    if catalog.get('name') != MARKETPLACE or len(catalog.get('plugins', [])) != 2:
        raise RuntimeError('Candidate marketplace identity mismatch')
    for row in catalog['plugins']:
        name = row.get('name')
        if name not in expected or row.get('source') != {'source':'local','path':'./'+expected[name]}:
            raise RuntimeError('Candidate plugin source mismatch')
        manifest = json.loads((root/expected[name]/'plugin.json').read_text(encoding='utf-8'))
        if manifest.get('name') != name or manifest.get('version') != expected_version:
            raise RuntimeError('Candidate plugin version mismatch')
    if {row['name'] for row in catalog['plugins']} != set(expected):
        raise RuntimeError('Candidate plugin identities are incomplete')
    verification = json.loads((root/'verification.json').read_text(encoding='utf-8'))
    verify_files(root,expected.values(),verification.get('package_hashes'),skip_bytecode=True)
    if expected_version in {'0.6.1','0.6.2'} or 'demo_library_hashes' in verification:
        verify_files(root,['demo-library'],verification.get('demo_library_hashes'))


def verify_files(root, folders, hashes, *, skip_bytecode=False):
    if not isinstance(hashes,dict) or not hashes:
        raise RuntimeError('Candidate integrity manifest missing')
    root = source_path(root)
    actual = set()

    def scan_error(error):
        raise RuntimeError(f"Candidate integrity inspection failed: {error}") from error

    for folder in folders:
        base = root/folder
        if base.resolve() != root.resolve()/folder:
            raise RuntimeError('Candidate integrity requires local package directories')
        for directory, dirs, files in os.walk(base,followlinks=False,onerror=scan_error):
            here = Path(directory)
            if not here.resolve().is_relative_to(root.resolve()) or here.is_symlink():
                raise RuntimeError('Candidate integrity path outside local candidate')
            if skip_bytecode and '__pycache__' in dirs:
                dirs.remove('__pycache__')
            for name in dirs+files:
                path = here/name
                if path.is_symlink() or path.resolve() != here.resolve()/name:
                    raise RuntimeError('Candidate integrity requires ordinary local files')
            for name in files:
                path = here/name
                if not skip_bytecode or path.suffix not in {'.pyc','.pyo'}:
                    actual.add(path.relative_to(root).as_posix())
    if actual != set(hashes):
        raise RuntimeError('Candidate integrity hash coverage mismatch')
    for relative in actual:
        if sha256((root/relative).read_bytes()).hexdigest() != hashes[relative]:
            raise RuntimeError('Candidate package integrity check failed')


def installation_entries(plugins, root):
    rows = []
    for group, installed in [('installed', True), ('available', False)]:
        values = plugins.get(group)
        if not isinstance(values, list) or any(not isinstance(r, dict) for r in values):
            raise RuntimeError('Malformed plugin catalog')
        for row in values:
            if row.get('name') in PLUGINS:
                if row.get('installed') is not installed:
                    raise RuntimeError('Inconsistent plugin installation state')
                rows.append(row)
    entries = {}
    for name, folder in PLUGINS.items():
        matches = [r for r in rows if r.get('name') == name]
        if len(matches) != 1:
            raise RuntimeError('Missing or ambiguous plugin: '+name)
        row = matches[0]
        source, market = row.get('source'), row.get('marketplaceSource')
        if (row.get('pluginId') != name+'@'+MARKETPLACE or row.get('marketplaceName') != MARKETPLACE
                or not isinstance(source, dict) or source.get('source') != 'local'
                or not isinstance(source.get('path'), str) or normalized(source['path']) != normalized(root/folder)
                or not isinstance(market, dict) or market.get('sourceType') != 'local'
                or not isinstance(market.get('source'), str) or normalized(market['source']) != normalized(root)):
            raise RuntimeError('Unexpected plugin identity or source: '+name)
        entries[name] = row
    return entries


def install_plugins(run, root, expected_version='0.2.0'):
    """User-operated serial installation; preserve partial results on failure.

    The official CLI has no expected-source/CAS option. Do not run another
    updater concurrently. Never uninstall or roll back installed plugins here.
    """
    result = {'status':'installation_failed'}
    def ready(entry):
        return (entry.get('version') == expected_version and entry.get('installed') is True
                and entry.get('enabled') is True)

    def catalog():
        value = run('list', '--marketplace', MARKETPLACE, '--available', '--json')
        result['plugins'] = value
        return installation_entries(value, root)
    try:
        if current_root(run) != normalized(root):
            raise RuntimeError('Expected '+root.name+' registration is not active; no installation attempted')
        entries = catalog()
        for name in PLUGINS:
            if current_root(run) != normalized(root):
                raise RuntimeError('Marketplace source changed; installation stopped')
            row = entries[name]
            if ready(row):
                continue
            run('add', name+'@'+MARKETPLACE, '--json')
            entries = catalog()
            row = entries[name]
            if not ready(row):
                raise RuntimeError('Installed version/enablement verification failed: '+name)
        if current_root(run) != normalized(root):
            raise RuntimeError('Marketplace source changed; installation cannot be verified')
        final_entries = catalog()
        if not all(ready(entry) for entry in final_entries.values()):
            raise RuntimeError('Final catalog does not show both reviewed plugins installed and enabled')
        result.update(status='installed_restart_required', current_root=normalized(root),
                      notice='Both plugins are installed and enabled at '+expected_version+'. Desktop tools still need verification after restart.')
    except Exception as error:
        result['error'] = str(error)
        # Even a failing add can have copied files before enablement failed.
        # Observe the actual state without retries, uninstall, or rollback.
        try:
            result['plugins'] = run('list', '--marketplace', MARKETPLACE, '--available', '--json')
        except Exception as diagnostic_error:
            result.pop('plugins', None)
            result['diagnostic_error'] = str(diagnostic_error)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--apply', action='store_true', help='User-operated switch of the known local marketplace source')
    modes.add_argument('--install', action='store_true', help='User-operated install/enable of both reviewed plugins')
    parser.add_argument('--candidate', choices=TARGETS, default='candidate-9', help='Fixed reviewed local update target')
    args = parser.parse_args()
    previous, version = TARGETS[args.candidate]
    predecessors = (previous,) if isinstance(previous,str) else previous
    target = QA/args.candidate
    report = {'mode':'install' if args.install else 'apply' if args.apply else 'read_only',
              'candidate':args.candidate, 'expected_version':version, 'commands':[], 'status':'not_started'}
    def run(*arguments):
        completed = subprocess.run([str(cli), 'plugin', *arguments], cwd=ROOT,
                                   capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        report['commands'].append({'arguments':list(arguments), 'exit':completed.returncode})
        if completed.returncode:
            raise RuntimeError((completed.stderr or completed.stdout).strip()[:4000])
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise RuntimeError('Unexpected CLI JSON response')
        return value
    try:
        cli = registered_cli()
        if cli is None:
            raise RuntimeError('Verified Codex executable unavailable; do not change permissions')
        validate_candidate(target, expected_version=version)
        if args.apply:
            print('Use one updater at a time; the official CLI has no atomic source-compare operation.', flush=True)
            print('Selecting the reviewed local marketplace '+args.candidate+'.', flush=True)
        if args.install:
            print('Installing/enabling both reviewed '+version+' plugins with the official CLI. Use one updater at a time.', flush=True)
            report.update(install_plugins(run, target, expected_version=version))
            code = 0 if report['status'] == 'installed_restart_required' else 1
        else:
            report.update(register(run,tuple(QA/p for p in predecessors),target,apply=args.apply))
            code = 0 if report['status'] == 'registered_restart_required' else 2
    except Exception as error:
        report.update(status='failed', error=str(error))
        code = 1
    if target.parent != QA:
        output = target.parent/'desktop-diagnostics'
    else:
        output = QA/('namespace-fix' if args.candidate == 'candidate-10' else 'installation-fix' if args.install else 'registration-fix')
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest = output/('registration-'+stamp+'.json')
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print('Diagnostic report: '+str(dest))
    if code == 0 and args.install:
        print('Both plugins verified at '+version+' and enabled. Completely close and reopen Codex; then ask the assistant to verify the tools.')
    elif code == 0:
        print('Registration root verified; this does NOT verify plugin installation or loaded tools. Share the installed/available entries with the assistant.')
    else:
        print('Desktop upgrade is NOT verified. Keep this window open and share the diagnostic report path.')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
