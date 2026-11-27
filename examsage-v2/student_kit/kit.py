"""Student entry point. The recipient prepares a local marketplace with their own runtime."""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT/'src'))

from examsage.course_pack import _publish_directory
from examsage.plugin_package import build_package
from examsage.source_paths import source_path
from examsage.student_import import MAX_FILES, import_selection
from examsage.student_workspace import local_workspace, recipient_workspace_root
from examsage.windows_codex import registered_cli

SUBJECTS = ('physics', 'mathematics', 'literature', 'history')
PLUGINS = {'examsage-student-courses':'押题宝 · 我的课程', 'examsage-student-demos':'押题宝 · 四科演示'}
MARKET = 'examsage-student'


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def inventory(folder):
    root = source_path(folder)
    return {p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p != root/'prepared.json'}


def prepare():
    target = KIT/'marketplace'
    source_manifest = (KIT/'kit-files.json').read_bytes()
    for name, digest in json.loads(source_manifest).items():
        if sha256((KIT/name).read_bytes()).hexdigest() != digest:
            raise ValueError('学生包文件不完整，请从原 ZIP 重新解压。')
    identity = {'kit':sha256(source_manifest).hexdigest(), 'python':sys.executable}
    if target.exists():
        receipt = json.loads((target/'prepared.json').read_bytes())
        if receipt != {**identity, 'files':inventory(target)}:
            raise ValueError('已准备的插件发生变化，请保留个人课件并将 ZIP 解压到新的目录。')
        return target
    with TemporaryDirectory(dir=KIT, prefix='.prep-') as work:
        stage = Path(work)/'market'
        courses = ['demo-'+subject for subject in SUBJECTS]
        entries = []
        for plugin, title in PLUGINS.items():
            selected = courses if plugin == 'examsage-student-demos' else []
            build_package(stage/plugin,None,selected,Path(sys.executable),plugin_name=plugin,
                          display_name=title,recipient=True)
            entries.append({'name':plugin,'source':{'source':'local','path':'./'+plugin},
                            'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},
                            'category':'Productivity'})
        write_json(stage/'.agents/plugins/marketplace.json',
                   {'name':MARKET,'interface':{'displayName':'押题宝学生版'},'plugins':entries})
        write_json(stage/'prepared.json', {**identity,'files':inventory(stage)})
        _publish_directory(stage,target)
    return target


def register():
    target = prepare()
    cli = registered_cli()
    if cli is None:
        raise ValueError('未找到 Windows Codex 桌面应用，请确认已安装并登录。')
    def current():
        raw = subprocess.check_output([str(cli),'plugin','marketplace','list','--json'],timeout=45)
        rows = json.loads(raw)['marketplaces']
        if not isinstance(rows,list):
            raise ValueError('无法核实 Codex 插件目录。')
        return [source_path(Path(row['root'])) for row in rows if row['name'].casefold() == MARKET]
    registered = current()
    if not registered:
        subprocess.run([str(cli),'plugin','marketplace','add',str(target)],check=True,timeout=45)
        registered = current()
    if registered != [source_path(target)]:
        raise ValueError('同名目录指向其他位置。请保留原目录，在 Codex 中核对来源。')
    print('登记成功。请在 Codex 插件目录打开“押题宝学生版”，安装并启用“我的课程”和“四科演示”。')


def import_files(name, subject, files, materials=None):
    if not 1 <= len(files) <= MAX_FILES:
        raise ValueError('请选择 1 至 24 个文件。')
    workspace = local_workspace(recipient_workspace_root(), [])
    with ExitStack() as stack:
        streams = [(path.name, stack.enter_context(path.open('rb'))) for path in files]
        result = import_selection(workspace.imports,name,subject,streams,materials=materials,record_receipt=True)
    result.pop('study_url')
    result.pop('reader_url')
    result['offline_reader'] = str(workspace.imports/result['id']/'library'/'course-reader.html')
    return result


def picker(parent=None):
    from tkinter import Tk, filedialog, messagebox, simpledialog
    root = parent if parent is not None else Tk()
    if parent is None:
        root.withdraw()
    try:
        files = filedialog.askopenfilenames(parent=root,title='选择本门课程的资料',
                    filetypes=[('课程资料','*.pdf *.pptx *.txt *.md')])
        if not files:
            return
        name = simpledialog.askstring('我的课程','课程名称',parent=root)
        if not name:
            return
        subject = simpledialog.askstring('我的课程','学科，例如地球物理或历史',parent=root)
        if not subject:
            return
        paths = list(map(Path,files))
        labels = []
        for path in paths:
            role = simpledialog.askstring('资料类别', path.name+'\n课件 / 真题 / 答案 / 模拟卷 / 其他',
                                          initialvalue='课件',parent=root)
            if role is None:
                return
            roles = {'课件':'lecture','真题':'exam','答案':'exam_solution','模拟卷':'mock_exam','其他':'unknown'}
            if role.strip() not in roles:
                raise ValueError('请选择课件、真题、答案、模拟卷或其他。')
            label = {'filename':path.name,'kind':roles[role.strip()]}
            if label['kind'] in {'exam','exam_solution','mock_exam'}:
                year = simpledialog.askstring('资料年份','输入年份，未知可留空',parent=root)
                if year is None:
                    return
                if year.strip():
                    label['exam_year'] = int(year)
            labels.append(label)
        result = import_files(name,subject,paths,labels)
        if parent is not None:
            return result
        messagebox.showinfo('已导入',f"{result['name']}，共 {result['pages']} 页。\n请在 Codex 对话中打开“押题宝 · 我的课程”，询问并要求引用页码。\n离线阅读页：{result['offline_reader']}",parent=root)
    finally:
        if parent is None:
            root.destroy()


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(dest='action', required=True)
    for cmd in ('prepare','register','picker','study'):
        actions.add_parser(cmd)
    intake = actions.add_parser('import')
    intake.add_argument('--name',required=True)
    intake.add_argument('--subject',required=True)
    intake.add_argument('files',nargs='+',type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        print(prepare())
    elif args.action == 'register':
        register()
    elif args.action == 'study':
        from examsage.study_host import open_studio
        open_studio()
    elif args.action == 'picker':
        picker()
    else:
        print(json.dumps(import_files(args.name,args.subject,args.files)))


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        sys.exit('操作未完成。'+str(exc))
