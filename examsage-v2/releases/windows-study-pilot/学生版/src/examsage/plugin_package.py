"""Build a machine-local plugin candidate, without installing or publishing it."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys

from .plugin_tools import load_library
from .source_paths import source_path
from . import PLUGIN_VERSION

STUDENT_PLUGIN_VERSION = '0.6.4'

MODULES = ['__init__.py', 'domain.py', 'storage.py', 'lexical.py', 'search.py',
           'numeric_audit.py', 'course_profile.py', 'plugin_tools.py', 'mcp_server.py',
           'page_image.py', 'source_paths.py', 'ingest.py', 'source_reviews.py', 'knowledge_map.py', 'exam_outlook.py', 'exam_topic_review.py', 'topic_evidence.py', 'numbered_pages.py',
           'import_receipt.py','student_workspace.py']


def _build_student_demos(folder: Path, courses: list[str]):
    from .course_pack import CoursePack, import_pack

    catalog = {f'demo-{subject}': subject for subject in ('physics','mathematics','literature','history')}
    if len(courses) != len(set(courses)) or set(courses).difference(catalog):
        raise ValueError('Student demos must be selected from the four authored examples')
    examples = Path(__file__).resolve().parents[2]/'examples'/'course-packs'
    folder.mkdir()
    entries = []
    for course_id in courses:
        source = examples/catalog[course_id]
        pack = CoursePack.model_validate_json((source/'pack.json').read_bytes())
        if pack.profile.course_id != course_id:
            raise ValueError('Demo course identity mismatch')
        import_pack(pack,source,folder/course_id)
        entries.append({'slug':course_id,'data':course_id})
    (folder/'library.json').write_text(json.dumps({'courses':entries}),encoding='utf-8')


def build_package(output: Path, library: Path | None, courses: list[str], python: Path, *,
                  plugin_name: str = 'examsage-courses',
                  display_name: str = '押题宝课程学习（本机验证）', student_root: Path | None = None,
                  recipient: bool = False):
    if not isinstance(plugin_name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', plugin_name):
        raise ValueError('Plugin name must be a lowercase identifier of at most 64 characters')
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 120:
        raise ValueError('A short plugin display name is required')
    # Codex merges installed plugin servers by this key, keeping the first one.
    # Preserve the established real-course namespace; other identities are unique.
    version = STUDENT_PLUGIN_VERSION if recipient else PLUGIN_VERSION
    server_name = 'examsage' if plugin_name == 'examsage-courses' else 'plugin_'+plugin_name.replace('-', '_')
    output, python = output.resolve(), python.resolve()
    if recipient != (library is None):
        raise ValueError('Student packages accept only bundled examples. Local packages require a course library.')
    if library is not None:
        library = library.resolve()
    if output.exists():
        raise FileExistsError('Choose a new package directory')
    if not python.is_file():
        raise ValueError('Existing Python runtime required')
    if recipient and student_root is not None:
        raise ValueError('Recipient packages resolve the student location on the receiving machine')
    if not recipient and (courses or student_root is None):
        load_library(library, courses).call('list_courses', {})
    source = Path(__file__).resolve().parent
    template = source.parents[1] / 'plugin'
    if not (template / 'skills' / 'course-study' / 'SKILL.md').is_file():
        raise FileNotFoundError('Course skill template unavailable')
    output.mkdir(parents=True)
    vendor = output / 'vendor' / 'examsage'
    vendor.mkdir(parents=True)
    for name in MODULES:
        shutil.copyfile(source / name, vendor / name)
    shutil.copytree(template / 'skills', output / 'skills')
    skill = output/'skills/course-study/SKILL.md'
    skill.write_text(skill.read_text(encoding='utf-8').replace('`examsage` MCP', f'`{server_name}` MCP'), encoding='utf-8')
    (output / 'server.py').write_text(
        'from pathlib import Path\nimport sys, json\n'
        'sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))\n'
        'from examsage.mcp_server import main\n'
        'settings = json.loads(Path(__file__).with_name("local-settings.json").read_text(encoding="utf-8"))\n'
        'library = Path(__file__).resolve().parent / settings["library"]\n'
        'args = ["--library", str(library), "--courses", settings["courses"]]\n'
        'if settings.get("personal"):\n'
        '    from examsage.student_workspace import recipient_workspace_root\n'
        '    args.extend(["--student-root", str(recipient_workspace_root())])\n'
        'if "student_root" in settings:\n    args.extend(["--student-root", settings["student_root"]])\n'
        f'raise SystemExit(main(args, version={version!r}))\n', encoding='utf-8')
    if recipient and courses:
        _build_student_demos(output/'library', courses)
    manifest = {'$schema': 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
                'name': plugin_name, 'version': version,
                'description': '押题宝授权课程查证与学习；本机只读验证候选。',
                'extensions': {'com.openai': {'requires_local_executor': True,
                    'interface': {'displayName': display_name,
                                  'shortDescription': '基于课程原文查证，保留条件与来源。'}}}}
    # A portable command must be a bare executable or a plugin-relative path.
    # Windows hosts may use their native command interpreter for a .cmd entry.
    # Library paths remain data in JSON, never shell expressions.
    settings = {'python':str(python),'library':str(library),'courses':','.join(courses)}
    if recipient:
        settings['library'] = 'library' if courses else '.'
        if not courses:
            settings['personal'] = True
    if student_root is not None:
        settings['student_root'] = str(student_root.resolve())
    (output / 'local-settings.json').write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8')
    flags = ['-I','-B'] if recipient else ['-B']
    server_entry = str(Path('${PLUGIN_ROOT}')/'server.py') if recipient else '${PLUGIN_ROOT}/server.py'
    executable = str(python).replace('%', '%%')
    if any(c in executable for c in ('"', '\r', '\n')):
        raise ValueError('Unsupported executable path')
    (output / 'launch.cmd').write_text(
        '@echo off\nsetlocal DisableDelayedExpansion\n'
        '"%SystemRoot%\\System32\\chcp.com" 65001 >nul\nif errorlevel 1 exit /b 1\n'
        f'"{executable}" {" ".join(flags)} "%~dp0server.py"\nexit /b %errorlevel%\n', encoding='utf-8')
    connection = {'type': 'stdio', 'command': './launch.cmd', 'args': []}
    files = {'plugin.json': manifest,
             'mcp.json': {'$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
                          'mcpServers': {server_name: connection}},
             '.codex-plugin/plugin.json': {'name': plugin_name, 'version': version,
                 'description': manifest['description'], 'skills': './skills/',
                 'mcpServers': './.mcp.json', 'requires_local_executor': True,
                 'interface': {'displayName': display_name}},
             '.mcp.json': {'mcpServers': {server_name: {'command': str(python),
                 'args': [*flags, server_entry]}}}}
    for name, data in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    if recipient:
        (output/'使用说明.txt').write_text('请保留安装目录。学生私课按 Windows 用户保存；演示课随插件提供。\n', encoding='utf-8')
    else:
        (output / 'LOCAL-ONLY.txt').write_text(
            '本机验证候选，未安装、未发布、未通过真实宿主验收。\n'
            '需要 Windows、本机现有 Python/Pydantic/Pillow/pypdfium2 和授权课程目录；路径已由构建器填写。\n'
            '包中没有课件、数据库或凭据，不能直接发给其他学生当成通用安装包。\n'
            '支持 MCP 2025-11-25 stdio 课程文字与原页图片工具；图像不是语义验收证明。\n'
            '不支持云端身份、HTTP、模型调用或后台任务。\n', encoding='utf-8')
    hash_root = source_path(output)
    hashes = {p.relative_to(hash_root).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in sorted(hash_root.rglob('*')) if p.is_file()}
    (output / 'package-hashes.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    return {'files': len(hashes), 'plugin_name': plugin_name, 'server_name':server_name, 'courses': courses,
            'output': str(output), 'host_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--library', required=True, type=Path)
    parser.add_argument('--courses', required=True)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--student-root', type=Path)
    parser.add_argument('--plugin-name', default='examsage-courses')
    parser.add_argument('--display-name', default='押题宝课程学习（本机验证）')
    args = parser.parse_args()
    courses = args.courses.split(',') if args.courses else []
    print(json.dumps(build_package(args.output, args.library, courses, args.python,
        plugin_name=args.plugin_name, display_name=args.display_name,student_root=args.student_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
