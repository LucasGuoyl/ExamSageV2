"""Create the Windows student ZIP from a closed list of first-party inputs."""
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from examsage.plugin_package import MODULES

KIT_MODULES = ['course_draft.py','course_pack.py','course_reader.py','course_library_import.py',
               'paper_topics.py','student_import.py','plugin_package.py','windows_codex.py',
               'study_links.py','study_host.py','study_window.py','study_view.py','study_reader.py','chat_store.py','chat_runner.py','chat_service.py',
               'chat_models.py','model_runtime.py','learning_state.py','study_review.py']


def build(output):
    files = {f'src/examsage/{name}':(ROOT/'src/examsage'/name).read_bytes()
             for name in MODULES + KIT_MODULES}
    for name in ('plugin/skills/course-study/SKILL.md','src/examsage/web/course-reader.html'):
        files[name] = (ROOT/name).read_bytes()
    web = ROOT/'src/examsage/web'
    assets = [web/'studio'/name for name in ('index.html','studio.css','studio.js','studio-locale.js')]
    katex = web/'vendor/katex'
    assets.extend(katex/name for name in ('katex.min.css','katex.min.js','contrib/auto-render.min.js','LICENSE','PROVENANCE.json'))
    assets.extend(sorted((katex/'fonts').glob('KaTeX_*.woff2')))
    for path in assets:
        files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    files['src/examsage/paper_topics.json'] = b'{}\n'
    for subject in ('physics','mathematics','literature','history'):
        docs = ['pack.json','lesson.txt']
        if subject == 'history':
            docs.append('declaration-excerpt.txt')
        for collection in ('course-packs', 'course-packs-en'):
            for doc in docs:
                name = f'examples/{collection}/{subject}/{doc}'
                files[name] = (ROOT/name).read_bytes()
    for name in ('kit.py','学生使用说明.txt','STUDENT-GUIDE.txt'):
        files[name] = (ROOT/'student_kit'/name).read_bytes()
    for name, action in [('开始学习.bat','study'),('1-登记学生插件.bat','register'),('2-导入自己的课件.bat','picker'),
                         ('Start ExamSage.bat','study --language en'),
                         ('Register Student Plugins.bat','register --language en'),
                         ('Import Course Files.bat','picker --language en')]:
        # Only fixed commands run on double-click. Student paths come from the file picker.
        lines = ['@echo off','setlocal DisableDelayedExpansion',
                 'set "runtime=%USERPROFILE%\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe"',
                 'if exist "%runtime%" goto ready','echo Codex desktop Python runtime was not found.',
                 'echo Open the included student guide for requirements.','pause','exit /b 1',':ready',
                 f'"%runtime%" -I -B -X utf8 "%~dp0kit.py" {action}','set "result=%errorlevel%"','pause','exit /b %result%']
        files[name] = ('\r\n'.join(lines)+'\r\n').encode('ascii')
    files['kit-files.json'] = json.dumps({n:sha256(d).hexdigest() for n,d in sorted(files.items())},
                                         indent=2,ensure_ascii=False).encode('utf-8')
    output = Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise FileExistsError('Choose a new ZIP filename')
    with TemporaryDirectory(dir=output.parent) as folder:
        temp = Path(folder)/'kit.zip'
        with ZipFile(temp,'x',compression=ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                item = ZipInfo(name,(2026,1,1,0,0,0))
                item.compress_type = ZIP_DEFLATED
                archive.writestr(item,data)
        temp.rename(output)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    build(parser.parse_args().output)
