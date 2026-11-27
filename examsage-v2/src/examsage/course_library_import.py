"""Owner-operated import of explicit course packs into a new local library.

No model, authentication change, installed-plugin mutation or academic approval.
All artifacts are prepared together before publishing the new directory.
"""
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory

from .course_pack import CoursePack, _import_into_staging, _publish_directory
from .plugin_tools import load_library


def import_course_library(source_root: Path, packs: list[str], output: Path, *, record_receipt=False) -> dict:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ValueError('Selected source root is not a directory')
    if output.exists() or output.is_symlink():
        raise FileExistsError('Choose a new library output directory')
    output = output.resolve()
    if not packs:
        raise ValueError('Select at least one relative course pack path')
    selected, seen_paths, seen_ids = [], set(), set()
    for selection in packs:
        relative = PurePosixPath(selection.replace('\\', '/'))
        if (not selection or relative.is_absolute() or PureWindowsPath(selection).drive
                or '..' in relative.parts or ':' in selection):
            raise ValueError('Course pack must be a relative path within the selected root')
        path = (source_root / relative).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError('Course pack outside selected root or unavailable')
        if path in seen_paths:
            raise ValueError('Duplicate course pack path')
        raw = path.read_bytes()
        pack = CoursePack.model_validate_json(raw)
        cid = pack.profile.course_id
        if cid in seen_ids:
            raise ValueError('Duplicate course ID in selected packs')
        seen_paths.add(path)
        seen_ids.add(cid)
        selected.append((path, pack, sha256(raw).hexdigest()))

    output.parent.mkdir(parents=True, exist_ok=True)
    # One staging tree for the whole batch. Nesting single-course staging here
    # can exceed Windows path limits even when every final asset path is valid.
    with TemporaryDirectory(prefix='.cl-', dir=output.parent) as temporary:
        folder = Path(temporary)
        registry, courses = [], []
        for index, (path, pack, pack_hash) in enumerate(selected, 1):
            # Generated folder names also support valid IDs such as Windows "con".
            data = f'courses/course-{index:04d}'
            imported = _import_into_staging(pack, path.parent, folder / data, record_receipt=record_receipt)
            cid = pack.profile.course_id
            registry.append({'slug': cid, 'data': data})
            courses.append({'course_id': cid, 'snapshot': imported.scope.snapshot,
                'pack': path.relative_to(source_root).as_posix(), 'pack_sha256': pack_hash,
                'data': data, 'report': imported.report})
        report = {'schema_version': 'course-library-import-v1',
            'status': 'imported_pending_review', 'semantic_review': 'pending',
            'model_called': False, 'courses': courses,
            'totals': {'courses': len(courses),
                **{key: sum(c['report'][key] for c in courses)
                   for key in ('pages', 'records', 'generated_records', 'notes_records')},
                'unpaired_questions': sum(len(c['report']['unpaired_questions']) for c in courses),
                'extraction': {key: sum(c['report']['extraction'][key] for c in courses)
                    for key in ('failed_pages', 'partial_pages', 'native_text_pages',
                                'hidden_pages', 'low_text_pages')}},
            'limitations': ['课程包元数据需预先编写；导入成功不代表学术、图像或题答对应已审核。',
                '离线阅读器展示提取文字与待审信息，不是模型对话或公开课程发布。',
                '新库未自动加入已安装插件；宿主课程授权与学生登录仍需单独接入。']}
        for name, value in [('library.json', {'courses': registry}), ('review.json', report)]:
            (folder / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        # Exercise the actual registered scopes and reader before publishing.
        from .course_reader import render_reader
        tools = load_library(folder, [c['course_id'] for c in courses])
        render_reader(tools, folder / 'course-reader.html')
        _publish_directory(folder, output)
    return {'status': report['status'], 'model_called': False, 'output': str(output),
        'courses': [{'course_id': c['course_id'], 'snapshot': c['snapshot'],
                     **({'received_on_utc':c['report']['received_on_utc']} if record_receipt else {})} for c in courses],
        'totals': report['totals'], 'review': str(output / 'review.json'),
        'reader': str(output / 'course-reader.html'), 'limitations': report['limitations']}
