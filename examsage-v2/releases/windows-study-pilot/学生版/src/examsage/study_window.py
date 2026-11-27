"""Daily study window for the downloadable Windows kit."""
from contextlib import closing
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .chat_runner import ChatRunner
from .chat_store import student_process_lock
from .import_receipt import checked_child
from .model_runtime import SubscriptionRuntime
from .student_import import import_selection
from .student_workspace import local_workspace, recipient_workspace_root, student_tools


class StudyDesk:
    def __init__(self, workspace, *, runtime_factory=SubscriptionRuntime):
        self.workspace = workspace
        self.tools = student_tools(None, workspace)
        self.folder = checked_child(workspace.chats, 'study-window')
        self.runtime_factory = runtime_factory
        self.runner = None
        self.course_id = self.session_id = self.run_id = None
        self.lock = student_process_lock(self.folder)
        self.lock.__enter__()

    def courses(self):
        return self.workspace.private_catalog()

    def spring_example(self, language='zh'):
        """Open the bundled two-page lecture under the current student's identity."""
        kit = Path(__file__).resolve().parents[2]
        if language not in ('zh', 'en'):
            raise ValueError('Unsupported study language.')
        base = checked_child(kit, 'examples/course-packs-en/physics' if language == 'en' else 'examples/course-packs/physics')
        pack = json.loads(checked_child(base, 'pack.json').read_bytes())['manifest']
        name = 'Physics example · Linear spring' if language == 'en' else '物理示例 · 线性弹簧'
        filename = 'lesson.txt'
        content = checked_child(base, filename).read_bytes()
        digest = sha256(content).hexdigest()
        if not any(doc['relative_path'] == filename and doc['sha256'] == digest
                   for doc in pack['documents']):
            raise ValueError('弹簧课件与随包清单不符，请重新解压学生包。')
        for course in self.courses():
            if course['name'] == name:
                binding, store = self.tools._course(course['slug'])
                docs = store.manifest(binding.scope).documents
                if (len(docs) == 1 and docs[0].sha256 == digest and docs[0].kind == 'lecture'
                        and Path(docs[0].relative_path).name == filename):
                    return course['slug']
        result = import_selection(self.workspace.imports, name, 'Physics' if language == 'en' else '物理', [(filename, BytesIO(content))],
                                  materials=[{'filename': filename, 'kind': 'lecture'}], record_receipt=True)
        return 'upload-' + result['id']

    def select(self, course_id):
        if self.run_id:
            raise ValueError('请先结束当前回答再切换课程。')
        self.clear_selection()
        binding, store = self.tools._course(course_id)
        folder = checked_child(self.folder, course_id)
        runner = ChatRunner(folder, runtime=self.runtime_factory(folder))
        self.binding, self.store, self.runner = binding, store, runner
        self.course_id = course_id
        sessions = self.sessions()
        self.session_id = sessions[0]['id'] if sessions else None

    def _current(self):
        if not self.runner or self.tools._course(self.course_id)[0] != self.binding:
            raise ValueError('课程已变更，请重新打开这门课。')
        return self.binding.scope

    def sessions(self):
        return self.runner.store.list_sessions(self._current()) if self.runner else []

    def messages(self):
        if self.session_id is None:
            return []
        return self.runner.store.messages(self._current(), self.session_id)

    def send(self, question):
        scope = self._current()
        if self.run_id:
            raise ValueError('请等当前回答结束。')
        if not question.strip() or len(question) > 4000:
            raise ValueError('请输入 1 至 4000 个字符的问题。')
        if not self.session_id:
            self.session_id = self.runner.store.create_session(scope, question.strip()[:60])['id']
        run = self.runner.submit(self.store, scope, self.session_id, question.strip(), uuid4().hex,
                                 scope_guard=self._current, course_id=self.course_id)
        self.run_id = run['id']
        return self.run_id

    def result(self, run_id):
        try:
            run = self.runner.get_run(self._current(), run_id)
        except (OSError, ValueError, LookupError, sqlite3.Error):
            self.clear_selection()
            raise
        if run_id == self.run_id and run['status'] != 'running':
            self.run_id = None
        return run

    def stop(self):
        if self.run_id:
            self.runner.cancel(self.binding.scope, self.run_id)

    def clear_selection(self):
        try:
            if self.runner:
                try:
                    self.stop()
                finally:
                    self.runner.close()
        finally:
            self.runner = self.session_id = self.course_id = self.run_id = None

    def close(self):
        try:
            self.clear_selection()
        finally:
            self.lock.__exit__(None, None, None)


def readable_math(text):
    """Tk renders plain text; keep unsupported TeX expressions intact for copying."""
    def render(match):
        expr = match.group(1) if match.group(1) is not None else match.group(2)
        expr = re.sub(r'\\mathrm\{([A-Za-z0-9 /°µΩ.-]+)\}', r'\1', expr)
        expr = re.sub(r'\\mathrm[ \t]+([A-Za-z])', r'\1', expr)
        expr = re.sub(r'\\[,;: ]', ' ', expr)
        if '\\' in expr:
            return match.group()
        def script(token):
            chars = token.group(2) or token.group(3)
            if token.group(1) == '^':
                keys, values = '0123456789+-', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻'
            else:
                keys, values = '0123456789+-aeijknorstux', '₀₁₂₃₄₅₆₇₈₉₊₋ₐₑᵢⱼₖₙₒᵣₛₜᵤₓ'
            return chars.translate(str.maketrans(keys, values)) if all(c in keys for c in chars) else token.group()
        return re.sub(r'([_^])(?:\{([A-Za-z0-9+-]+)\}|([A-Za-z0-9]))', script, expr)
    return re.sub(r'\\\((.*?)\\\)|\\\[(.*?)\\\]', render, text, flags=re.DOTALL)


def history_lines(messages):
    for msg in messages:
        if msg['role'] == 'user':
            yield 'user', '你'
            yield 'body', msg['content']
            continue
        answer = msg.get('answer') or {}
        yield 'assistant', '押题宝'
        if answer.get('subscription_verified') is True:
            yield 'meta', '本轮已使用 ChatGPT 套餐'
        for para in answer.get('paragraphs', []):
            citations = ' '.join('['+key+']' for key in para['citations'])
            yield 'body', (readable_math(para['text'])+' '+citations).strip()
        if not answer.get('paragraphs'):
            yield 'body', msg['content']
        outlook = answer.get('exam_outlook') or {}
        for item in outlook.get('ranking', []):
            yield 'body', item['topic']+' · '+ '、'.join(map(str,item['years']))
        if answer.get('evidence'):
            yield 'heading', '课件出处'
        for evidence in answer.get('evidence', []):
            refs = '；'.join(f"{ref['filename']} 第 {ref['page']} 页" for ref in evidence['refs'])
            yield 'source', f"[{evidence['id']}] {refs}"
        for limitation in answer.get('limitations', []):
            yield 'meta', limitation


def format_history(messages):
    return '\n'.join(text for _, text in history_lines(messages))


def open_window(picker):
    import tkinter as tk
    from tkinter import messagebox
    from .study_view import StudyView

    root=tk.Tk()
    root.title('押题宝 · 学习问答')
    width=min(1160,root.winfo_screenwidth()-60)
    height=min(760,root.winfo_screenheight()-90)
    root.geometry(f'{width}x{height}')
    root.minsize(480,440)
    try:
        workspace=local_workspace(recipient_workspace_root(), [])
        with closing(StudyDesk(workspace)) as desk:
            StudyView(root,desk,picker)
            root.protocol('WM_DELETE_WINDOW',root.quit)
            root.mainloop()
    except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
        messagebox.showerror('无法打开学习窗口',str(exc),parent=root)
    finally:
        root.destroy()
