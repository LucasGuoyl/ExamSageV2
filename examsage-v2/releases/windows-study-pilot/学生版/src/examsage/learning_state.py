"""Local learning-state core; callers must inject authenticated principals.

Not exposed through the read-only MCP server. Cloud login and HTTP sessions
are deliberately not inferred from a student name supplied by a model.
"""
from contextlib import closing
from pathlib import Path
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .domain import digest
from .plugin_tools import CourseBinding, PluginTools, Principal


class _StatusUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['new', 'practising', 'review', 'confident']


class ProgressUpdate(_StatusUpdate):
    note: str = Field(max_length=10000)


class _RecallUpdate(_StatusUpdate):
    cue: str = Field(default='', max_length=10000)


class ProgressConflict(ValueError):
    """The student changed this note in another view."""


_UNCONDITIONAL = object()


def revision(row):
    if row is None:
        return None
    fields = [row['status'], row['note']]
    # An untouched legacy row keeps its existing optimistic-lock token.
    if row['cue']:
        fields.append(row['cue'])
    return digest(fields)


class LearningStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS learning_progress(
                subject TEXT, workspace TEXT, course TEXT, snapshot TEXT, record_id TEXT,
                status TEXT NOT NULL, note TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                cue TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(subject,workspace,course,snapshot,record_id))''')
            def has_cue():
                return any(row[1] == 'cue' for row in db.execute('PRAGMA table_info(learning_progress)'))
            if not has_cue():
                db.execute('BEGIN IMMEDIATE')
                if not has_cue():
                    db.execute("ALTER TABLE learning_progress ADD COLUMN cue TEXT NOT NULL DEFAULT ''")


class StudentLearning:
    def __init__(self, store: LearningStore, bindings: list[CourseBinding], principal: Principal):
        if not isinstance(principal.subject, str) or not principal.subject.strip() or len(principal.subject) > 200:
            raise ValueError('Trusted subject required')
        self._store = store
        self._subject = principal.subject
        self._courses = PluginTools(bindings, principal)

    def _scope(self, course_id):
        binding, store = self._courses._course(course_id)
        scope = binding.scope
        return scope, store, (self._subject, scope.workspace, scope.course, scope.snapshot)

    def get(self, course_id: str, record_id: str):
        scope, course, key = self._scope(course_id)
        if course.get(scope, record_id) is None:
            raise ValueError('Learning record unavailable in authorized scope')
        with closing(sqlite3.connect(self._store.path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("""SELECT status,note,cue FROM learning_progress
                WHERE subject=? AND workspace=? AND course=? AND snapshot=? AND record_id=?""",
                (*key,record_id)).fetchone()
        return {'status':row['status'] if row else 'new', 'note':row['note'] if row else '',
                'revision':revision(row)}

    def save(self, course_id: str, record_id: str, status: str, note: str, *, expected_revision=_UNCONDITIONAL):
        update = ProgressUpdate(status=status, note=note)
        return self._save(course_id, record_id, update, expected_revision)

    def save_recall(self, course_id, record_id, *, expected_revision, **fields):
        return self._save(course_id, record_id, _RecallUpdate(**fields), expected_revision)

    def _save(self, course_id, record_id, update, expected_revision):
        scope, course, key = self._scope(course_id)
        if course.get(scope, record_id) is None:
            raise ValueError('Learning record unavailable in authorized scope')
        column = 'note' if isinstance(update, ProgressUpdate) else 'cue'
        with closing(sqlite3.connect(self._store.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.row_factory = sqlite3.Row
            key = (*key,record_id)
            row = db.execute("""SELECT status,note,cue FROM learning_progress
                WHERE subject=? AND workspace=? AND course=? AND snapshot=? AND record_id=?""", key).fetchone()
            saved = dict(row) if row else {'note':'', 'cue':''}
            saved.update(update.model_dump(exclude_unset=True))
            changed = row is None or dict(row) != saved
            if changed and expected_revision is not _UNCONDITIONAL and revision(row) != expected_revision:
                raise ProgressConflict('复习记录已变更，请重新读取后保存。')
            if row is None:
                db.execute('''INSERT INTO learning_progress(subject,workspace,course,snapshot,record_id,status,note,cue)
                    VALUES(?,?,?,?,?,?,?,?)''', (*key, saved['status'], saved['note'], saved['cue']))
            elif changed:
                # Only the owning editor may write this column. Both editors share status and revision.
                db.execute(f'''UPDATE learning_progress SET status=?,{column}=?,updated_at=CURRENT_TIMESTAMP
                    WHERE subject=? AND workspace=? AND course=? AND snapshot=? AND record_id=?''',
                    (saved['status'], saved[column], *key))
        result = {'record_id':record_id, 'snapshot':scope.snapshot, 'status':update.status,
                  'revision':revision(saved), 'validation':'student_self_report_not_assessment'}
        if column == 'cue':
            result['cue'] = saved['cue']
        return result

    def entries(self, course_id: str):
        scope, course, key = self._scope(course_id)
        with closing(sqlite3.connect(self._store.path)) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('''SELECT record_id,status,note,cue,updated_at FROM learning_progress
                WHERE subject=? AND workspace=? AND course=? AND snapshot=? ORDER BY record_id''', key).fetchall()
        for row in rows:
            record = course.get(scope,row['record_id'])
            if record is not None:
                yield dict(row),record

    def list(self, course_id: str):
        return [row for row, _ in self.entries(course_id)]
