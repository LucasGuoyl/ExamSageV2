"""Apply an explicit offline review request to a new portable course draft."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .course_pack import CoursePack, _publish_directory
from .domain import digest
from .plugin_tools import load_library
from .source_reviews import SourceReviewRequest
from .source_paths import source_path


def apply_source_reviews(draft: Path, library: Path, course_id: str, request: dict, output: Path) -> dict:
    request = SourceReviewRequest.model_validate(request)
    if output.exists() or output.is_symlink():
        raise FileExistsError('Choose a new review draft directory')
    tools = load_library(library, [course_id])
    binding, store = tools._course(course_id)
    permitted = store.permitted_documents(binding.scope)
    if not {d.id for d in store.manifest(binding.scope).documents} <= permitted:
        raise ValueError('Review draft requires all sources in the current scope')
    context = tools.call('get_course_profile', {'course_id': course_id}).get('review_context')
    if (request.course_id != course_id or not context
            or any(getattr(request, key) != value for key, value in context.items())):
        raise ValueError('Review request does not match the current course, snapshot and scope')
    draft = source_path(draft)
    pack_path = (draft / 'pack.json').resolve()
    if not pack_path.is_relative_to(draft):
        raise ValueError('Draft pack outside approved root')
    pack = CoursePack.model_validate_json(pack_path.read_text(encoding='utf-8'))
    if (digest(pack.model_dump(mode='json')) != request.pack_digest
            or pack.workspace != binding.scope.workspace or pack.profile.course_id != course_id):
        raise ValueError('Draft no longer matches the imported source pack')
    if not {d.id for d in pack.manifest.documents} <= permitted:
        raise ValueError('Review draft requires all sources in the current scope')
    # Read and hash each explicit source once; copy the validated bytes, never a
    # whole directory that might contain unrelated files or linked content.
    payloads = []
    for doc in pack.manifest.documents:
        path = (draft / doc.relative_path).resolve()
        if not path.is_relative_to(draft) or not path.is_file():
            raise ValueError('Draft source outside approved root or unavailable')
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != doc.sha256:
            raise ValueError('Draft source hash mismatch')
        payloads.append((doc.relative_path, raw))
    for note in request.reviews:
        for ref in note.evidence:
            record = store.get(binding.scope, f'{ref.document_id}:p{ref.page}')
            if (record is None or record.kind != 'block' or len(record.refs) != 1
                    or record.refs[0].document_id != ref.document_id or record.refs[0].page != ref.page):
                raise ValueError('Review evidence is hidden or unavailable in the current scope')
    data = pack.model_dump(mode='json')
    data['source_reviews'].extend(note.model_dump(mode='json') for note in request.reviews)
    updated = CoursePack.model_validate(data)  # Validates hashes, page bounds and append-only IDs.
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.cr-', dir=source_path(output.parent)) as temporary:
        folder = Path(temporary) / 'draft'
        folder.mkdir()
        for relative, raw in payloads:
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (folder / 'pack.json').write_text(updated.model_dump_json(indent=2), encoding='utf-8')
        receipt = {'status': 'review_draft_saved', 'course_id': course_id, 'model_called': False,
                   'previous_snapshot': request.snapshot, 'request_digest': digest(request.model_dump(mode='json')),
                   'appended_reviews': [n.id for n in request.reviews],
                   'notice': '学习注记已写入新草稿；须导入新课程库后才在新阅读器显示，未作专家核查。'}
        (folder / 'review-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        _publish_directory(folder, output)
    return receipt
