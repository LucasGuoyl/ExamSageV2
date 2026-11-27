"""Prepare local-only review artifacts. Does not install, publish or call a model."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from examsage.course_pack import CoursePack, import_pack
from examsage.course_reader import render_reader
from examsage.plugin_package import build_package
from examsage.plugin_tools import load_library
from examsage.source_paths import source_path

ROOT = Path(__file__).resolve().parents[1]


def prepare(output):
    if output.exists():
        raise FileExistsError('Choose a new candidate directory')
    output.mkdir(parents=True)
    library = output/'demo-library'
    library.mkdir()
    entries, reports = [], []
    for discipline in ['physics', 'mathematics', 'literature', 'history']:
        source = ROOT/'examples/course-packs'/discipline
        pack = CoursePack.model_validate_json((source/'pack.json').read_text(encoding='utf-8'))
        cid = pack.profile.course_id
        result = import_pack(pack, source, library/cid)
        entries.append({'slug': cid, 'data': cid})
        reports.append(result.report)
    (library/'library.json').write_text(json.dumps({'courses':entries},indent=2),encoding='utf-8')
    demo_courses = [e['slug'] for e in entries]
    render_reader(load_library(library,demo_courses),output/'course-reader.html')
    builds = [build_package(output/'plugin-existing-courses', ROOT/'data',
                           ['grt','geodynamics','planetary_science','sea_level','ses'],Path(sys.executable),
                           student_root=ROOT/'data'/'student-workspaces'),
              build_package(output/'plugin-demo-courses', library, demo_courses,Path(sys.executable),
                            plugin_name='examsage-demo-courses', display_name='押题宝跨学科演示（开发样例）')]
    # Inert local marketplace source. Registering it with a host is a separate
    # user action; this does not touch the active repo or personal plugin config.
    marketplace = output/'.agents/plugins/marketplace.json'
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(json.dumps({'name':'examsage-local-pilot',
        'interface':{'displayName':'押题宝本机试点'},
        'plugins':[{'name':'examsage-courses','source':{'source':'local','path':'./plugin-existing-courses'},
                    'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Productivity'},
                   {'name':'examsage-demo-courses','source':{'source':'local','path':'./plugin-demo-courses'},
                    'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Productivity'}]},
        ensure_ascii=False,indent=2),encoding='utf-8')
    report = {'kind':'local_candidate_not_installed', 'imports':reports, 'packages':builds,
        'source_hashes':{p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest()
                        for p in sorted((ROOT/'src/examsage').rglob('*')) if p.suffix in {'.py','.html','.js','.css','.json'}}}
    (output/'candidate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    hashes = {}
    for package in builds:
        folder = Path(package['output'])
        manifest = folder / 'package-hashes.json'
        package_files = json.loads(manifest.read_text(encoding='utf-8'))
        package_files[manifest.name] = sha256(manifest.read_bytes()).hexdigest()
        hashes.update({f'{folder.name}/{name}': digest for name, digest in package_files.items()})
    demo_hashes = {}
    extended_root = source_path(output)

    def scan_error(error):
        raise error

    for directory, _, files in os.walk(extended_root/'demo-library', onerror=scan_error):
        for name in sorted(files):
            path = Path(directory)/name
            demo_hashes[path.relative_to(extended_root).as_posix()] = sha256(path.read_bytes()).hexdigest()
    verification = {'purpose':'local package and demonstration library integrity',
                    'package_hashes':hashes,'demo_library_hashes':demo_hashes}
    (output/'verification.json').write_text(json.dumps(verification, indent=2), encoding='utf-8')
    print(json.dumps({'output':str(output),'courses':len(entries),'installed':False},ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args().output.resolve())
