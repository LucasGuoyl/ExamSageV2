import hashlib
import sqlite3

import pytest

from examsage.domain import Scope
from examsage.storage import Store
from test_core import example


def test_missing_readonly_database_does_not_create_directory(tmp_path):
    path = tmp_path / 'absent' / 'course.sqlite3'
    with pytest.raises((FileNotFoundError, sqlite3.OperationalError)):
        Store(path, read_only=True)
    assert not path.parent.exists()


def test_readonly_query_preserves_database_and_rejects_writes(tmp_path):
    store, manifest, record = example(tmp_path)
    sid = store.publish('w', manifest, [record], [], {})
    before = hashlib.sha256(store.path.read_bytes()).hexdigest()
    readonly = Store(store.path, read_only=True)
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'])
    assert readonly.get(scope, 'b').text == record.text
    with pytest.raises(PermissionError):
        readonly.publish('w', manifest, [record], [], {})
    with readonly.connect() as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute('DELETE FROM snapshots')
    assert hashlib.sha256(store.path.read_bytes()).hexdigest() == before


def test_readonly_filename_with_uri_characters(tmp_path):
    folder = tmp_path / '课程 #1'
    store, manifest, record = example(folder)
    sid = store.publish('w', manifest, [record], [], {})
    readonly = Store(store.path, read_only=True)
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'])
    assert readonly.get(scope, 'b').id == record.id
