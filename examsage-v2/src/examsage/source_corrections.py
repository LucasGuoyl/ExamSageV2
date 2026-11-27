"""Apply an explicitly adopted review to matching, unmodified source records."""
from copy import deepcopy

from .adjudication import validate_adjudication
from .domain import digest


def apply_review_to_records(manifest, records, correction, *, rebuilt_hashes=None):
    if (correction.get('schema') != 'frozen-source-correction-v1'
            or correction.get('course') != manifest.course_key):
        raise ValueError('Source review does not match the course')
    by_id = {r.id:r for r in records}
    targets = correction.get('target_payload_hashes', {})
    if not targets:
        raise ValueError('Correction targets required')
    rebuilt_hashes = rebuilt_hashes or {}
    if set(rebuilt_hashes) - set(targets):
        raise ValueError('Unexpected target in rebuilt review')
    for rid, expected in targets.items():
        accepted = {expected, rebuilt_hashes.get(rid)}
        if rid not in by_id or digest(by_id[rid].model_dump(mode='json')) not in accepted:
            raise ValueError('Correction target unavailable or changed')
    docs = {d.id:d for d in manifest.documents}
    visible = {(ref.document_id, ref.page) for r in records if r.kind == 'block' and r.visibility == 'visible' for ref in r.refs}
    adjudication = correction['adjudication']
    validate_adjudication(adjudication, docs, visible, {d.id:d.sha256 for d in docs.values()})
    evidence = {(row['document_id'], row['page']) for row in adjudication['evidence']}
    for rid in targets:
        record = by_id[rid]
        if record.visibility != 'visible' or not evidence <= {(ref.document_id, ref.page) for ref in record.refs}:
            raise ValueError('Correction evidence outside target references')
        # This one-time patch only annotates untouched records. Never discard
        # a competing/prior adjudication when the recipe is reused.
        if record.details.get('audit'):
            raise ValueError('Existing audit requires an explicit review merge')
    for rid in targets:
        record = by_id[rid]
        record.details['audit'] = {'adjudication':deepcopy(adjudication)}
        record.limitations = list(dict.fromkeys([*record.limitations, adjudication['summary']]))
