import pytest

from examsage.domain import Scope
from examsage.plugin_tools import CourseBinding, Principal
from test_core import example


def setup(tmp_path, subject='alice', grant=True, sources=('doc',), snapshot=None):
    from examsage.learning_state import LearningStore, StudentLearning
    store, manifest, record = example(tmp_path/'course')
    sid = store.publish('w', manifest, [record], [], {'version': snapshot or 'v1'})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=list(sources))
    binding = CourseBinding('physics', store.path, scope)
    return StudentLearning(LearningStore(tmp_path/'learning.sqlite3'), [binding],
        Principal(subject, frozenset(['physics'] if grant else []))), record.id


def test_students_and_course_versions_have_independent_persistent_progress(tmp_path):
    alice, rid = setup(tmp_path)
    alice.save('physics', rid, 'practising', 'Remember the boundary conditions')
    bob, _ = setup(tmp_path, 'bob')
    assert bob.list('physics') == []
    reopened, _ = setup(tmp_path)
    assert reopened.list('physics')[0]['note'] == 'Remember the boundary conditions'
    new_version, _ = setup(tmp_path, snapshot='v2')
    assert new_version.list('physics') == []


@pytest.mark.parametrize('operation', ['read', 'write'])
def test_revoked_course_cannot_read_or_write(tmp_path, operation):
    alice, rid = setup(tmp_path)
    alice.save('physics', rid, 'review', 'old')
    revoked, _ = setup(tmp_path, grant=False)
    with pytest.raises(ValueError):
        revoked.list('physics') if operation == 'read' else revoked.save('physics', rid, 'confident', 'new')
    assert alice.list('physics')[0]['note'] == 'old'


def test_source_revocation_hides_prior_notes_and_rejects_new_writes(tmp_path):
    alice, rid = setup(tmp_path)
    alice.save('physics', rid, 'review', 'private source note')
    narrowed, _ = setup(tmp_path, sources=())
    assert narrowed.list('physics') == []
    with pytest.raises(ValueError): narrowed.save('physics', rid, 'review', 'more')


@pytest.mark.parametrize('status,note', [('invented', 'x'), ('review', 'x'*10001)], ids=['status', 'long-note'])
def test_learning_input_bounds(tmp_path, status, note):
    alice, rid = setup(tmp_path)
    with pytest.raises(ValueError): alice.save('physics', rid, status, note)
    assert alice.list('physics') == []


def test_simultaneous_recall_and_note_edits_cannot_overwrite_each_other(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from examsage.learning_state import ProgressConflict

    alice, rid = setup(tmp_path)
    token = alice.save('physics', rid, 'review', 'old answer')['revision']
    gate = Barrier(2)
    def write(field):
        gate.wait(timeout=5)
        try:
            if field == 'cue':
                return alice.save_recall('physics', rid, status='review', cue='question?', expected_revision=token)
            return alice.save('physics', rid, 'review', 'new answer', expected_revision=token)
        except ProgressConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ('cue','note')))
    assert len([item for item in results if item is not None]) == 1
    row, = alice.list('physics')
    assert (row['cue'],row['note']) in {('question?', 'old answer'), ('', 'new answer')}
