"""Resolve a completed browser import under the storage root selected by its host."""
import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from .domain import Scope


def checked_child(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or relative.drive or '..' in relative.parts:
        raise ValueError('Expected a relative storage path')
    root = root.resolve()
    expected = root / relative
    actual = expected.resolve()
    if actual != expected or not actual.is_relative_to(root):
        raise ValueError('Course storage unavailable')
    return actual


def read_import(root, batch_id):
    if not isinstance(batch_id, str) or str(UUID(batch_id)) != batch_id:
        raise ValueError('Invalid course import')
    folder = checked_child(root,batch_id)
    receipt = json.loads(checked_child(folder,'import.json').read_text(encoding='utf-8'))
    if not isinstance(receipt, dict) or not isinstance(receipt.get('result'), dict):
        raise ValueError('Invalid course receipt')
    result = receipt['result']
    course = 'upload-'+batch_id
    if (result.get('id') != batch_id or not isinstance(result.get('name'),str)
            or not result['name'].strip()):
        raise ValueError('Course receipt does not match batch')
    library = checked_child(folder,'library')
    data = checked_child(library,receipt['course_path'])
    current = checked_child(data,'current.json').read_bytes()
    if sha256(current).hexdigest() != receipt['scope_sha256']:
        raise ValueError('Course scope changed')
    scope = Scope.model_validate_json(current)
    if scope.course != course or scope.snapshot != result.get('snapshot'):
        raise ValueError('Course receipt does not match scope')
    return result, data, scope


def imported_course(root,batch_id):
    return read_import(root,batch_id)[1]
