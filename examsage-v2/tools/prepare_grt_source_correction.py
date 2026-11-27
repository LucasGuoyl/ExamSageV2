"""Prepare a frozen, local-only data correction; never change the active library.

Use a new output below data/qa/plugin-20261116. The supplied correction is
bound to the old snapshot and exact record hashes: a later rebuild needs a
fresh review, not a silent best-effort merge. No plugin registration occurs.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from examsage.source_corrections import apply_review_to_records
from examsage.domain import Scope, digest
from examsage.ingest import atomic_json
from examsage.plugin_package import build_package
from examsage.release import publish_release
from examsage.storage import Store

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT/'data/qa/plugin-20261116'
RECIPE = ROOT/'courses/grt_source_correction_20261116.json'


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def annotated_records(store, scope, correction):
    if (correction.get('schema') != 'frozen-source-correction-v1'
            or correction.get('course') != scope.course
            or correction.get('source_snapshot') != scope.snapshot):
        raise ValueError('Correction does not match the frozen course snapshot')
    records = store.list_records(scope)
    apply_review_to_records(store.manifest(scope), records, correction)
    return records


def prepare(output):
    output = output.resolve()
    if output == QA.resolve() or not output.is_relative_to(QA.resolve()):
        raise ValueError('Output must be a new child of the project QA directory')
    if output.exists():
        raise FileExistsError('Choose a new correction output directory')
    source = ROOT/'data/grt'
    scope = Scope.model_validate_json((source/'current.json').read_text(encoding='utf-8'))
    store = Store(source/'course.sqlite3', read_only=True)
    correction = json.loads(RECIPE.read_text(encoding='utf-8'))
    records = annotated_records(store, scope, correction)
    manifest = store.manifest(scope)
    # Validate the actual source bytes before creating any output.
    for row in correction['adjudication']['evidence']:
        doc = next(d for d in manifest.documents if d.id == row['document_id'])
        asset = (source/'assets'/doc.asset).resolve()
        if not asset.is_relative_to((source/'assets').resolve()) or file_hash(asset) != row['source_sha256']:
            raise ValueError('Correction source bytes do not match the reviewed evidence')
    before = {c:file_hash(ROOT/'data'/c/'course.sqlite3')
              for c in ['grt','geodynamics','ses','sea_level','planetary_science']}
    original_records = store.list_records(scope)
    edges = {edge.id:edge for record in original_records for edge in store.related(scope, record.id)}
    output.mkdir(parents=True)
    working = Store(output/'revision/course.sqlite3')
    metadata = {**(store.metadata(scope) or {}), 'correction_base_snapshot':scope.snapshot,
                'source_correction':correction, 'source_correction_hash':digest(correction)}
    sid = working.publish(scope.workspace, manifest, records, list(edges.values()), metadata)
    revised_scope = scope.model_copy(update={'snapshot':sid})
    atomic_json(output/'revision/current.json', revised_scope.model_dump(mode='json'))
    release = publish_release(working, revised_scope, source/'assets', output/'library/grt',
                              extras={'source_correction':correction, 'installed':False})
    atomic_json(output/'library/library.json', {'courses':[{'slug':'grt','data':'grt'}]})
    package = build_package(output/'plugin-data-preview', output/'library', ['grt'], Path(sys.executable))
    after = {c:file_hash(ROOT/'data'/c/'course.sqlite3') for c in before}
    if before != after:
        raise RuntimeError('Original course database changed during correction preparation')
    report = {'kind':'local_data_correction_not_installed', 'source_snapshot':scope.snapshot,
              'revision_snapshot':sid, 'release_snapshot':release['snapshot'],
              'changed_records':sorted(correction['target_payload_hashes']),
              'source_database_hashes_before':before, 'source_database_hashes_after':after,
              'correction_recipe_sha256':file_hash(RECIPE), 'package':package,
              'release_manifest':'library/grt/release_manifest.json',
              'limitations':['Not registered or loaded by the native host.',
                             'Only the specified derivative relation was reviewed.',
                             'Independent subject-expert acceptance remains pending.',
                             'A changed base snapshot needs a new reviewed correction recipe.']}
    atomic_json(output/'correction.json', report)
    print(json.dumps({'output':str(output), 'snapshot':release['snapshot'],
                      'changed_records':len(correction['target_payload_hashes']), 'installed':False}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
