"""Import files selected by the student, from either a local picker or the web form."""
from hashlib import sha256
import json
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from .course_draft import MaterialLabel, create_course_draft
from .course_library_import import import_course_library
from .course_pack import _publish_directory
from .course_profile import CURRICULUM_LABELS
from .source_paths import source_path


MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_FILES = 24


def _validate_filename(name):
    path = PureWindowsPath(name)
    if (not name or name != path.name or path.is_reserved()
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
            or name.endswith(('.', ' ')) or path.suffix.lower() not in {'.pdf', '.pptx', '.txt', '.md'}):
        raise ValueError('请选择文件名有效的 PDF、PPTX、TXT 或 MD 文件。')


def import_selection(root, name, discipline, files, *, materials=None, curriculum=None, record_receipt=False):
    if not all(isinstance(s, str) and 0 < len(s.strip()) <= 200 for s in (name, discipline)):
        raise ValueError('请填写课程名称和学科，各限 200 字。')
    if not 1 <= len(files) <= MAX_FILES:
        raise ValueError('每次请选择 1 至 24 个课件。')
    registration = {}
    if curriculum is not None:
        if not isinstance(curriculum, dict) or set(curriculum).difference(CURRICULUM_LABELS):
            raise ValueError('课程体系登记字段无效。')
        for key, value in curriculum.items():
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError('课程体系登记每项限 200 字。')
            if value.strip():
                registration[key] = value.strip()
    labels = None
    if materials is not None:
        if not isinstance(materials,list) or len(materials) != len(files):
            raise ValueError('每份文件须对应一条资料类别记录。')
        labels = [MaterialLabel.model_validate(item) for item in materials]
        if [label.filename for label in labels] != [filename for filename, _ in files]:
            raise ValueError('请核对资料类别所对应的文件。')
    batch_id = str(uuid4())
    course_id = 'upload-' + batch_id
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=source_path(root), prefix='.up-') as work:
        work = Path(work)
        selected = work/'selected'
        combined = work/'result'
        combined.mkdir()
        paths = []
        remaining = MAX_REQUEST_BYTES
        for index, (filename, stream) in enumerate(files):
            _validate_filename(filename)
            raw = stream.read(remaining + 1)
            if not raw or len(raw) > remaining:
                raise ValueError('课件为空或超过本次导入大小限制。')
            remaining -= len(raw)
            relative = Path(str(index + 1))/filename
            destination = selected/relative
            destination.parent.mkdir(parents=True)
            destination.write_bytes(raw)
            if destination.suffix.lower() == '.pptx':
                try:
                    with ZipFile(destination) as archive:
                        members = archive.infolist()
                        if len(members) > 20000 or sum(m.file_size for m in members) > 256 * 1024 * 1024:
                            raise ValueError('此演示文稿超过网页导入的解压大小限制。')
                except BadZipFile as exc:
                    raise ValueError('无法读取演示文稿。') from exc
            paths.append(relative.as_posix())
        draft = combined/'draft'
        create_course_draft(selected, paths, draft, course_id=course_id,
                            name=name.strip(), disciplines=[discipline.strip()], materials=labels, **registration)
        # Publish the draft, library and receipt together from this same temporary directory.
        library = root.resolve()/work.name/'result'/'library'
        report = import_course_library(draft, ['pack.json'], library, record_receipt=record_receipt)
        registry = json.loads((library/'library.json').read_text(encoding='utf-8'))
        course_path = registry['courses'][0]['data']
        scope_hash = sha256((library/course_path/'current.json').read_bytes()).hexdigest()
        receipt = {'id': batch_id, 'name': name.strip(), 'documents': len(files),
                   'pages': report['totals']['pages'], 'semantic_review': 'pending',
                   'extraction': report['totals']['extraction'],
                   'snapshot': report['courses'][0]['snapshot'],
                   'reader_url': f'/import/{batch_id}/reader', 'study_url': f'/courses/{course_id}/'}
        if record_receipt:
            receipt['received_on_utc'] = report['courses'][0]['received_on_utc']
        (combined/'import.json').write_text(json.dumps({'result': receipt, 'scope_sha256': scope_hash,
            'course_path': course_path}, ensure_ascii=False), encoding='utf-8')
        _publish_directory(combined, root/batch_id)
    return receipt
