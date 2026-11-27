"""Local browser window for the student kit. Course and model operations belong to StudyDesk."""
import base64
import binascii
from contextlib import closing
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import threading
import time
import webbrowser

from .chat_store import StudentServerBusy
from .import_receipt import checked_child
from .ingest import atomic_json
from .learning_state import ProgressConflict
from .student_import import MAX_FILES, MAX_REQUEST_BYTES, import_selection
from .student_workspace import local_workspace, recipient_workspace_root
from .study_reader import read_citation
from .study_review import list_reviews, review_page, save_review
from .study_links import answer_sources, linked_page, paragraph_sources
from .study_window import StudyDesk


WEB = Path(__file__).resolve().parent / 'web'
MAX_JSON = 4 * ((MAX_REQUEST_BYTES + 2) // 3) + 64 * 1024
IDLE_SECONDS = 600
SCOPE_ERRORS = (LookupError, ValueError, OSError, sqlite3.Error)


class StaleView(ValueError):
    """A concurrently opened tab has already changed the conversation."""


def _import_files(desk, args):
    files = args.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('每次请选择 1 至 24 个课件。')
    streams, labels = [], []
    remaining = MAX_REQUEST_BYTES
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('课件名称无效。')
        data = item.get('data')
        if not isinstance(data, str) or len(data) > 4 * ((remaining + 2) // 3):
            raise ValueError('所选课件超过 64 MiB 或内容无效。')
        try:
            content = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('课件传输未完成，请重新选择文件。') from None
        if not content or len(content) > remaining:
            raise ValueError('课件为空或总大小超过 64 MiB。')
        remaining -= len(content)
        streams.append((item['name'], BytesIO(content)))
        labels.append({'filename':item['name'], 'kind':item.get('role', 'lecture'),
                       'exam_year':item.get('exam_year')})
    result = import_selection(desk.workspace.imports, args.get('name'), args.get('subject'),
                              streams, materials=labels, record_receipt=True)
    return 'upload-' + result['id']


def _history(messages):
    """Send the student-facing transcript, leaving tool traces and diagnostics in storage."""
    result = []
    for message in messages:
        row = {k:message[k] for k in ('role', 'content', 'run_id', 'created_at')}
        answer = message.get('answer') or {}
        if answer:
            visible = {key:answer[key] for key in ('paragraphs', 'exam_outlook', 'limitations',
                                                   'subscription_verified') if key in answer}
            visible['evidence'] = []
            for ev in answer.get('evidence', []):
                summary = {key:ev[key] for key in ('id', 'kind', 'text') if key in ev}
                summary['refs'] = [{k:ref[k] for k in ('filename', 'page', 'document_id') if k in ref}
                                   for ref in ev.get('refs', [])]
                visible['evidence'].append(summary)
            row['answer'] = visible
        result.append(row)
    return result


class Studio:
    def __init__(self, desk):
        self.desk = desk
        self.position = checked_child(desk.folder, 'last-study.json')
        if not desk.course_id:
            self._resume()
        self.revision = 0
        self.lock = threading.Lock()
        self.last_seen = time.monotonic()

    def _resume(self):
        courses = self.desk.courses()
        if not courses:
            return
        try:
            saved = json.loads(self.position.read_text('utf8'))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        course = next((c for c in courses if c['slug'] == saved.get('course')), courses[0])
        self.desk.select(course['slug'])
        if (saved.get('course') == self.desk.course_id
                and saved.get('snapshot') == self.desk.binding.scope.snapshot and 'session' in saved):
            session = saved['session']
            if session is None or any(s['id'] == session for s in self.desk.sessions()):
                self.desk.session_id = session

    def _remember(self):
        try:
            atomic_json(self.position, {'course':self.desk.course_id,
                        'snapshot':self.desk.binding.scope.snapshot, 'session':self.desk.session_id})
        except OSError:
            # A preference write must not turn a submitted model request into a retry.
            pass

    def _scope(self):
        if self.desk.course_id:
            try:
                self.desk._current()
            except SCOPE_ERRORS:
                self.desk.clear_selection()
                self.revision += 1

    def _state(self):
        desk = self.desk
        return {'course_id':desk.course_id, 'session_id':desk.session_id,
                'run_id':desk.run_id, 'revision':self.revision,
                'courses':[{k:c[k] for k in ('slug','name')} for c in desk.courses()],
                'sessions':desk.sessions(), 'messages':_history(desk.messages())}

    def request(self, args):
        if not isinstance(args, dict) or not isinstance(args.get('action'), str):
            raise ValueError('无法识别此操作。')
        action = args['action']
        with self.lock:
            self.last_seen = time.monotonic()
            if action == 'heartbeat':
                return {'ok':True}
            self._scope()
            if action == 'state':
                return self._state()
            desk = self.desk
            if (type(args.get('revision')) is not int or args['revision'] != self.revision
                    or 'course_id' not in args or args['course_id'] != desk.course_id
                    or 'session_id' not in args or args['session_id'] != desk.session_id):
                raise StaleView('学习窗口已变化，请刷新后继续。')
            if action == 'answer_sources':
                return answer_sources(desk,args.get('run_id'))
            if action == 'paragraph_sources':
                return paragraph_sources(desk,args.get('run_id'),args.get('paragraph_index'))
            if action == 'review_list':
                return list_reviews(desk)
            if action == 'review_save':
                return save_review(desk, args)
            if action in ('review_page', 'linked_page', 'citation'):
                image = args.get('image') is True
                if action == 'review_page':
                    result = review_page(desk, args.get('document_id'), args.get('page'), image=image)
                elif action == 'linked_page':
                    result = linked_page(desk,args.get('run_id'),args.get('paragraph_index'),args.get('key'),
                                         page=args.get('page'),image=image)
                else:
                    rid, eid = args.get('run_id'), args.get('evidence_id')
                    if not all(isinstance(value, str) for value in (rid, eid)) or not desk.session_id:
                        raise ValueError('请选择当前对话中的引用。')
                    result = read_citation(desk, rid, eid, args.get('ref_index',0),
                                           page=args.get('page'), image=image)
                if result.get('png') is not None:
                    result['png'] = base64.b64encode(result['png']).decode('ascii')
                return result
            if action in ('poll', 'stop'):
                rid = args.get('run_id')
                if not isinstance(rid, str) or rid != desk.run_id:
                    raise StaleView('此回答已结束或已切换，请刷新对话。')
                if action == 'stop':
                    desk.stop()
                run = desk.result(rid)
                if not desk.run_id:
                    self.revision += 1
                public = {k:run[k] for k in ('id','status','phase')}
                if run.get('error'):
                    public['error'] = {k:run['error'][k] for k in ('code','message') if k in run['error']}
                return {**self._state(), 'run':public}
            if desk.run_id:
                raise ValueError('请等回答完成，或先停止当前回答。')
            if action == 'course':
                course_id = args.get('id')
                if not any(c['slug'] == course_id for c in desk.courses()):
                    raise ValueError('所选课程不可用。')
                desk.select(course_id)
            elif action == 'example':
                desk.select(desk.spring_example())
            elif action == 'session':
                session_id = args.get('id')
                if not desk.course_id or 'id' not in args or (session_id is not None and
                        not any(s['id'] == session_id for s in desk.sessions())):
                    raise ValueError('所选对话不可用。')
                desk.session_id = session_id
            elif action == 'import':
                desk.select(_import_files(desk, args))
            elif action == 'send':
                question = args.get('question')
                if not isinstance(question, str) or not desk.course_id:
                    raise ValueError('请选择课程并输入问题。')
                desk.send(question)
            else:
                raise ValueError('无法识别此操作。')
            self._remember()
            self.revision += 1
            return self._state()


def local_browser(headers, authority, capability):
    expected = {'Host':authority, 'Origin':'http://' + authority}
    for name, value in expected.items():
        if headers.get_all(name) != [value]:
            return False
    if headers.get_all('Sec-Fetch-Site') not in (None, ['same-origin']):
        return False
    values = headers.get_all('X-ExamSage-Local') or []
    return len(values) == 1 and values[0].isascii() and secrets.compare_digest(values[0], capability)


def _asset(path):
    files = {'/':('studio/index.html','text/html; charset=utf-8'),
             '/studio.css':('studio/studio.css','text/css'),
             '/studio.js':('studio/studio.js','text/javascript'),
             '/vendor/katex/katex.min.js':('vendor/katex/katex.min.js','text/javascript'),
             '/vendor/katex/katex.min.css':('vendor/katex/katex.min.css','text/css'),
             '/vendor/katex/contrib/auto-render.min.js':('vendor/katex/contrib/auto-render.min.js','text/javascript')}
    entry = files.get(path)
    if re.fullmatch(r'/vendor/katex/fonts/KaTeX_[A-Za-z0-9_-]+\.woff2', path):
        entry = (path[1:], 'font/woff2')
    if entry:
        name, mime = entry
        file = checked_child(WEB, name)
        if file.is_file():
            return mime, file.read_bytes()
    return None


def _studio_version():
    # Bind this entry to the assets under the downloaded kit and the Python
    # endpoints they call. Identical extractions may reuse the same workspace.
    version = sha256()
    manifest = WEB.parents[2]/'kit-files.json'
    if manifest.is_file():
        version.update(sha256(manifest.read_bytes()).digest())
    for source in ('study_host.py','study_reader.py','study_links.py','study_review.py','learning_state.py',
                   'chat_runner.py','chat_service.py',
                   'web/studio/index.html','web/studio/studio.css','web/studio/studio.js'):
        version.update(sha256((WEB.parent/source).read_bytes()).digest())
    return version.hexdigest()


class StudioHTTP(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, studio):
        self.studio = studio
        self.capability = secrets.token_urlsafe(32)
        self.instance = secrets.token_hex(16)
        self.version = _studio_version()
        self.intake = threading.BoundedSemaphore(2)
        super().__init__(('127.0.0.1', 0), StudioHandler)
        self.authority = '127.0.0.1:' + str(self.server_port)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(15)
        return sock, address


class StudioHandler(BaseHTTPRequestHandler):
    server_version = 'ExamSage'
    sys_version = ''

    def log_message(self, format, *args):
        pass  # Never log questions, paths or request headers.

    def reply(self, status, payload, mime='application/json; charset=utf-8'):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, TimeoutError):
            pass

    def do_GET(self):
        if self.headers.get_all('Host') != [self.server.authority]:
            return self.reply(403, {'error':'此地址不可用。'})
        if self.path == '/instance':
            return self.reply(200, {'instance':self.server.instance, 'version':self.server.version})
        asset = _asset(self.path)
        if asset:
            mime, body = asset
            return self.reply(200, body, mime)
        self.reply(404, {'error':'找不到此页面。'})

    def do_POST(self):
        if self.path != '/api/studio':
            return self.reply(404, {'error':'找不到此操作。'})
        if not local_browser(self.headers, self.server.authority, self.server.capability):
            return self.reply(403, {'error':'请从学生包中的「开始学习」打开学习窗口。'})
        if (self.headers.get_content_type() != 'application/json' or
                self.headers.get_all('Transfer-Encoding') or len(self.headers.get_all('Content-Length') or []) != 1):
            return self.reply(400, {'error':'请求格式无效。'})
        try:
            count = int(self.headers['Content-Length'])
        except ValueError:
            count = 0
        if not 0 < count <= MAX_JSON:
            return self.reply(413, {'error':'单次导入课件上限为 64 MiB。'})
        if not self.server.intake.acquire(blocking=False):
            return self.reply(429, {'error':'其他操作进行中，请稍后重试。'})
        try:
            raw = self.rfile.read(count)
            if len(raw) != count:
                return self.reply(400, {'error':'请求传输不完整。'})
            try:
                args = json.loads(raw)
            except (ValueError, RecursionError):
                return self.reply(400, {'error':'请求格式无效。'})
            try:
                result = self.server.studio.request(args)
            except StaleView as exc:
                return self.reply(409, {'code':'stale_view','error':str(exc)})
            except ProgressConflict as exc:
                return self.reply(409, {'code':'review_conflict','error':str(exc)})
            except ValueError as exc:
                # Model validation may echo a full user input; return plain messages only.
                message = str(exc) if type(exc) is ValueError else '所选资料或操作参数无效。'
                return self.reply(400, {'error':message})
            except (LookupError, OSError, sqlite3.Error, RuntimeError):
                return self.reply(400, {'error':'当前课程或会话不可用，请刷新学习窗口。'})
            self.reply(200, result)
        finally:
            self.server.intake.release()


def _launch(url):
    if os.name == 'nt':
        for var in ('ProgramFiles(x86)', 'ProgramFiles'):
            folder = os.environ.get(var)
            if folder:
                edge = Path(folder) / 'Microsoft/Edge/Application/msedge.exe'
                if edge.is_file():
                    subprocess.Popen([str(edge), '--app=' + url])
                    return
    if not webbrowser.open_new_tab(url):
        raise RuntimeError('无法打开浏览器。请设置默认浏览器后再运行「开始学习」。')


def _reopen(marker, launch):
    # Check the non-private instance id before handing this process's temporary link to a browser.
    try:
        record = json.loads(marker.read_bytes())
        port, token, expected = record['port'], record['capability'], record['instance']
        if (type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str)
                or not re.fullmatch('[A-Za-z0-9_-]{43}', token)
                or not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{32}', expected)):
            return False
        with closing(HTTPConnection('127.0.0.1', port, timeout=1)) as conn:
            conn.request('GET', '/instance')
            response = conn.getresponse()
            running = json.loads(response.read(256))
            if response.status != 200 or not isinstance(running, dict) or running.get('instance') != expected:
                return False
            version = _studio_version()
            if record.get('version') != version or running.get('version') != version:
                raise StudentServerBusy('旧版学习窗口仍占用此工作区。请先关闭旧版窗口，等其本机服务退出后，再双击新版“开始学习”。旧服务关闭窗口后可能需要十分钟退出。')
    except (OSError, ValueError, KeyError, TypeError, HTTPException):
        return False
    launch(f'http://127.0.0.1:{port}/#{token}')
    return True


def open_studio(*, workspace=None, launch=None):
    """Open the current student's isolated studio, reusing a running instance when available."""
    if workspace is None:
        workspace = local_workspace(recipient_workspace_root(), [])
    launch = _launch if launch is None else launch
    marker = checked_child(checked_child(workspace.chats, 'study-window'), 'studio-active.json')
    try:
        desk = StudyDesk(workspace)
    except StudentServerBusy:
        if _reopen(marker, launch):
            return
        raise
    with closing(desk), StudioHTTP(Studio(desk)) as server:
        record = {'port':server.server_port, 'instance':server.instance, 'capability':server.capability,
                  'version':server.version}
        # The OS account owns this directory. Do not store or print model credentials.
        temp = marker.with_name('studio-' + secrets.token_hex(12) + '.tmp')
        try:
            with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                           'w', encoding='utf-8') as f:
                json.dump(record, f)
            temp.replace(marker)
            launch('http://' + server.authority + '/#' + server.capability)
            server.timeout = 1
            try:
                while time.monotonic() - server.studio.last_seen < IDLE_SECONDS:
                    server.handle_request()
            except KeyboardInterrupt:
                pass
        finally:
            temp.unlink(missing_ok=True)
            marker.unlink(missing_ok=True)
