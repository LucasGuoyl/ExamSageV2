"""Independent, scope-bound conversation storage."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .domain import Scope, digest
from .source_paths import sqlite_readonly_uri


class ChatNotFound(LookupError):
    """The requested object is absent from the current scope."""


class ChatConflict(ValueError):
    """The request conflicts with an existing conversation run."""


class StudentServerBusy(RuntimeError):
    pass


@contextmanager
def student_process_lock(chat_dir: Path):
    """Keep one runner per chat database, including across host processes."""
    chat_dir.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(chat_dir/'server-lock.sqlite3',timeout=0)) as lock:
        try:
            lock.execute('BEGIN EXCLUSIVE')
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                raise StudentServerBusy('当前学生的学习服务已经打开，请使用已打开的窗口。') from None
            raise
        yield


class ChatStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.exists():
            # Check before opening a writable connection: course snapshots are never chat storage.
            existing = sqlite3.connect(sqlite_readonly_uri(self.path), uri=True)
            try:
                names = {row[0] for row in existing.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if {'snapshots', 'records'} <= names:
                    raise ValueError('A course database cannot be used as conversation storage')
            finally:
                existing.close()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY, scope_key TEXT NOT NULL, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chat_sessions_scope ON chat_sessions(scope_key, updated_at);
                CREATE TABLE IF NOT EXISTS chat_runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
                    client_request_id TEXT NOT NULL, question TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed','cancelled')),
                    answer TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(session_id, client_request_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS chat_one_active_run
                    ON chat_runs(session_id) WHERE status IN ('queued','running');
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES chat_sessions(id),
                    run_id TEXT NOT NULL REFERENCES chat_runs(id),
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL, answer TEXT, created_at TEXT NOT NULL,
                    UNIQUE(run_id, role)
                );
                CREATE INDEX IF NOT EXISTS chat_messages_session ON chat_messages(session_id, id);
            ''')

    @contextmanager
    def _connect(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _scope_key(scope: Scope) -> str:
        data = scope.model_dump(mode='json')
        data['allowed_sources'] = sorted(data['allowed_sources'])
        return digest(data)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec='microseconds')

    @staticmethod
    def _text(value, label: str, limit: int, *, strip: bool = False) -> str:
        if not isinstance(value, str):
            raise ValueError(f'{label} must be text')
        if strip:
            value = value.strip()
        if not value.strip() or len(value) > limit or '\x00' in value:
            raise ValueError(f'{label} must contain 1 to {limit} characters without NUL')
        return value

    def _session(self, db, scope: Scope, session_id: str):
        row = db.execute('SELECT * FROM chat_sessions WHERE id=? AND scope_key=?',
                         (session_id, self._scope_key(scope))).fetchone()
        if row is None:
            raise ChatNotFound('Conversation not available in the current scope')
        return row

    def _run(self, db, scope: Scope, run_id: str):
        row = db.execute('''SELECT r.* FROM chat_runs r JOIN chat_sessions s ON r.session_id=s.id
                            WHERE r.id=? AND s.scope_key=?''',
                         (run_id, self._scope_key(scope))).fetchone()
        if row is None:
            raise ChatNotFound('Run not available in the current scope')
        return row

    @staticmethod
    def _session_view(row) -> dict:
        return {key: row[key] for key in ('id', 'title', 'created_at', 'updated_at')}

    @staticmethod
    def _run_view(row) -> dict:
        result = {key: row[key] for key in ('id', 'session_id', 'status', 'question', 'created_at', 'updated_at')}
        result['answer'] = json.loads(row['answer']) if row['answer'] else None
        result['error'] = json.loads(row['error']) if row['error'] else None
        return result

    def create_session(self, scope: Scope, title: str = '新对话') -> dict:
        title = self._text(title, 'Title', 120, strip=True)
        session_id, now = 'session_' + uuid4().hex, self._now()
        with self._connect(write=True) as db:
            db.execute('INSERT INTO chat_sessions VALUES(?,?,?,?,?)',
                       (session_id, self._scope_key(scope), title, now, now))
            return self._session_view(self._session(db, scope, session_id))

    def list_sessions(self, scope: Scope) -> list:
        with self._connect() as db:
            rows = db.execute('SELECT * FROM chat_sessions WHERE scope_key=? ORDER BY updated_at DESC, id',
                              (self._scope_key(scope),)).fetchall()
            return [self._session_view(row) for row in rows]

    def get_session(self, scope: Scope, session_id: str) -> dict:
        with self._connect() as db:
            return self._session_view(self._session(db, scope, session_id))

    def messages(self, scope: Scope, session_id: str) -> list:
        with self._connect() as db:
            self._session(db, scope, session_id)
            rows = db.execute('SELECT * FROM chat_messages WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
            result = []
            for row in rows:
                message = {key: row[key] for key in ('role', 'content', 'created_at', 'run_id')}
                if row['answer'] is not None:
                    message['answer'] = json.loads(row['answer'])
                result.append(message)
            return result

    def begin_run(self, scope: Scope, session_id: str, text: str, client_request_id: str) -> dict:
        text = self._text(text, 'Message', 4000)
        client_request_id = self._text(client_request_id, 'Request ID', 128)
        with self._connect(write=True) as db:
            self._session(db, scope, session_id)
            existing = db.execute('SELECT * FROM chat_runs WHERE session_id=? AND client_request_id=?',
                                  (session_id, client_request_id)).fetchone()
            if existing is not None:
                if existing['question'] != text:
                    raise ChatConflict('Request ID already belongs to a different message')
                return self._run_view(existing)
            if db.execute("SELECT 1 FROM chat_runs WHERE session_id=? AND status IN ('queued','running')",
                          (session_id,)).fetchone():
                raise ChatConflict('This conversation already has an active run')
            run_id, now = 'run_' + uuid4().hex, self._now()
            db.execute('''INSERT INTO chat_runs
                          (id,session_id,client_request_id,question,status,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?)''',
                       (run_id, session_id, client_request_id, text, 'running', now, now))
            db.execute('''INSERT INTO chat_messages(session_id,run_id,role,content,created_at)
                          VALUES(?,?,?,?,?)''', (session_id, run_id, 'user', text, now))
            db.execute('UPDATE chat_sessions SET updated_at=? WHERE id=?', (now, session_id))
            return self._run_view(self._run(db, scope, run_id))

    def get_run(self, scope: Scope, run_id: str) -> dict:
        with self._connect() as db:
            return self._run_view(self._run(db, scope, run_id))

    def finish_run(self, scope: Scope, run_id: str, answer: dict) -> bool:
        with self._connect(write=True) as db:
            run = self._run(db, scope, run_id)
            if run['status'] != 'running':
                return False
            if not isinstance(answer, dict):
                raise ValueError('Answer must be an object')
            content = self._text(answer.get('text'), 'Answer text', 64000)
            try:
                encoded = json.dumps(answer, ensure_ascii=False, allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                raise ValueError('Answer must be finite JSON data') from None
            if len(encoded.encode('utf-8')) > 512000:
                raise ValueError('Answer exceeds conversation storage limit')
            now = self._now()
            db.execute("UPDATE chat_runs SET status='completed',answer=?,updated_at=? WHERE id=?",
                       (encoded, now, run_id))
            db.execute('''INSERT INTO chat_messages(session_id,run_id,role,content,answer,created_at)
                          VALUES(?,?,?,?,?,?)''', (run['session_id'], run_id, 'assistant', content, encoded, now))
            db.execute('UPDATE chat_sessions SET updated_at=? WHERE id=?', (now, run['session_id']))
            return True

    def fail_run(self, scope: Scope, run_id: str, code: str, message: str, *, diagnostics=None) -> bool:
        with self._connect(write=True) as db:
            run = self._run(db, scope, run_id)
            if run['status'] != 'running':
                return False
            error_data = {'code': self._text(code, 'Error code', 80),
                          'message': self._text(message, 'Error message', 2000)}
            if diagnostics is not None:
                # Store application tool activity only, never raw provider logs.
                # Failed diagnostics must not turn a failed run back into running.
                try:
                    encoded = json.dumps(diagnostics, ensure_ascii=False, allow_nan=False)
                    if not isinstance(diagnostics, dict) or len(encoded.encode('utf-8')) > 64000:
                        raise ValueError('Diagnostic size/type limit')
                    error_data['diagnostics'] = json.loads(encoded)
                except (TypeError, ValueError, RecursionError):
                    error_data['diagnostics'] = {'omitted': 'diagnostic_limit_or_invalid'}
            error = json.dumps(error_data, ensure_ascii=False)
            now = self._now()
            db.execute("UPDATE chat_runs SET status='failed',error=?,updated_at=? WHERE id=?", (error, now, run_id))
            db.execute('UPDATE chat_sessions SET updated_at=? WHERE id=?', (now, run['session_id']))
            return True

    def cancel_run(self, scope: Scope, run_id: str) -> dict:
        with self._connect(write=True) as db:
            run = self._run(db, scope, run_id)
            if run['status'] in ('queued', 'running'):
                now = self._now()
                db.execute("UPDATE chat_runs SET status='cancelled',updated_at=? WHERE id=?", (now, run_id))
                db.execute('UPDATE chat_sessions SET updated_at=? WHERE id=?', (now, run['session_id']))
            return self._run_view(self._run(db, scope, run_id))

    def recover_interrupted(self) -> int:
        """Call once at service startup, before accepting work, never on ordinary opens."""
        error = json.dumps({'code': 'interrupted', 'message': '服务重启，上一轮未完成；请明确重试。'}, ensure_ascii=False)
        now = self._now()
        with self._connect(write=True) as db:
            db.execute('''UPDATE chat_sessions SET updated_at=? WHERE id IN
                          (SELECT session_id FROM chat_runs WHERE status IN ('queued','running'))''', (now,))
            cursor = db.execute("""UPDATE chat_runs SET status='failed',error=?,updated_at=?
                                   WHERE status IN ('queued','running')""", (error, now))
            return cursor.rowcount
