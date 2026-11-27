"""Daily review through the same Studio commands the downloaded student kit sends."""
import base64
from contextlib import closing
import sqlite3

import pytest

from examsage.student_workspace import Principal, StudentWorkspace
from examsage.study_host import StaleView, Studio
from examsage.study_window import StudyDesk
from test_study_host import command
from test_study_reader import ref, save_turn


def import_lesson(studio, state, text, name):
    return command(studio, state, 'import', name=name, subject='Physics', files=[
        {'name':'lesson.txt', 'data':base64.b64encode(text.encode()).decode()}])


def test_save_read_and_resume_exact_page_after_relaunch(tmp_path):
    workspace = StudentWorkspace(tmp_path, Principal('reviewer', frozenset()))
    with closing(StudyDesk(workspace)) as desk:
        studio = Studio(desk)
        state = import_lesson(studio, studio.request({'action':'state'}), 'Force\fEnergy', 'Course A')
        desk.session_id = desk.runner.store.create_session(desk._current())['id']
        run_id = save_turn(desk, [ref(desk, 1)])
        state = studio.request({'action':'state'})
        page = command(studio, state, 'citation', run_id=run_id, evidence_id='E1', page=2)
        identity = {k:page[k] for k in ('document_id', 'page')}
        saved = command(studio, state, 'review_save', **identity, status='review', version=None)
        assert saved == {**identity, 'filename':'lesson.txt', 'cue':'', 'status':'review',
                         'version':saved['version']}
        assert isinstance(saved['version'], str) and saved['version']
        assert command(studio, state, 'review_list') == {'items':[saved]}
        state = command(studio, state, 'session', id=None)
        assert command(studio, state, 'review_page', **identity)['text'] == 'Energy'

    with closing(StudyDesk(workspace)) as reopened:
        studio = Studio(reopened)
        state = studio.request({'action':'state'})
        assert command(studio, state, 'review_list')['items'] == [saved]
        updated = command(studio, state, 'review_save', **identity, status='confident',
                          cue='Which units?', version=saved['version'])
        assert updated['version'] != saved['version']
        assert command(studio, state, 'review_save', **identity, status='confident',
                       cue='Which units?', version=saved['version']) == updated
        with pytest.raises(ValueError, match='已变更'):
            command(studio, state, 'review_save', **identity, status='review',
                    cue='Old tab', version=saved['version'])
        with pytest.raises(ValueError):
            command(studio, state, 'review_save', **identity, status='review')
        assert command(studio, state, 'review_list') == {'items':[updated]}
        rescheduled = command(studio, state, 'review_save', **identity,
                              status='practising', version=updated['version'])
        assert rescheduled['cue'] == updated['cue']


def test_review_isolated_to_authorized_course_and_snapshot(tmp_path):
    workspace = StudentWorkspace(tmp_path, Principal('two courses', frozenset()))
    with closing(StudyDesk(workspace)) as desk:
        studio = Studio(desk)
        first = import_lesson(studio, studio.request({'action':'state'}), 'First', 'Course A')
        identity = {'document_id': ref(desk, 1)['document_id'], 'page':1}
        command(studio, first, 'review_save', **identity, status='review', cue='A only', version=None)
        second = import_lesson(studio, first, 'Other', 'Course B')
        assert command(studio, second, 'review_list') == {'items':[]}
        with pytest.raises(StaleView):
            command(studio, first, 'review_page', **identity)
        for fields in ({**identity,'document_id':'unavailable'}, {**identity,'page':2},
                       {**identity,'page':True}):
            with pytest.raises(ValueError):
                command(studio, second, 'review_page', **fields)
            with pytest.raises(ValueError):
                command(studio, second, 'review_save', **fields, status='review', version=None)
        first = command(studio, second, 'course', id=first['course_id'])
        assert command(studio, first, 'review_page', **identity)['text'] == 'First'
        receipt = workspace.imports / first['course_id'].removeprefix('upload-') / 'import.json'
        receipt.rename(receipt.with_suffix('.withdrawn'))
        for action in ('review_list', 'review_page', 'review_save'):
            with pytest.raises(StaleView):
                command(studio, first, action, **identity, status='review', version=None)


def test_hidden_slide_cannot_be_saved_or_opened_as_review(tmp_path):
    from test_course_draft import ordered_pptx

    slides = tmp_path / 'slides.pptx'
    ordered_pptx(slides)
    workspace = StudentWorkspace(tmp_path/'student', Principal('slides', frozenset()))
    with closing(StudyDesk(workspace)) as desk:
        studio = Studio(desk)
        state = command(studio, studio.request({'action':'state'}), 'import', name='Slides',
                        subject='Figures', files=[{'name':slides.name,
                        'data':base64.b64encode(slides.read_bytes()).decode()}])
        doc = ref(desk, 1)['document_id']
        visible = command(studio, state, 'review_page', document_id=doc, page=1)
        assert 'Example formula' in visible['text'] and not visible['can_next']
        with pytest.raises(ValueError):
            command(studio, state, 'review_page', document_id=doc, page=2, image=True)
        with pytest.raises(ValueError):
            command(studio, state, 'review_save', document_id=doc, page=2, status='review', version=None)
        assert command(studio, state, 'review_list') == {'items':[]}


def test_legacy_free_notes_survive_cue_edits_and_are_never_shown_in_the_recall_queue(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from examsage.domain import digest
    from examsage.learning_state import LearningStore, ProgressConflict, StudentLearning

    owner = Principal('legacy student', frozenset())
    workspace = StudentWorkspace(tmp_path, owner)
    with closing(StudyDesk(workspace)) as desk:
        studio = Studio(desk)
        state = import_lesson(studio, studio.request({'action':'state'}), 'First', 'Course A')
        course = state['course_id']
        scope = desk._current()
        identity = {'document_id':ref(desk, 1)['document_id'], 'page':1}
        record_id = identity['document_id'] + ':p1'
        path = workspace.learning_database(course)
        path.parent.mkdir(parents=True, exist_ok=True)
        answer = 'F = kx and the elongation is 0.05 m.'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('''CREATE TABLE learning_progress(
                subject TEXT, workspace TEXT, course TEXT, snapshot TEXT, record_id TEXT,
                status TEXT NOT NULL, note TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(subject,workspace,course,snapshot,record_id))''')
            db.execute('''INSERT INTO learning_progress(subject,workspace,course,snapshot,record_id,status,note)
                          VALUES(?,?,?,?,?,?,?)''',
                       (owner.subject, scope.workspace, scope.course, scope.snapshot, record_id,'review',answer))

        gate = Barrier(2)
        def reopen():
            gate.wait(timeout=5)
            return LearningStore(path)
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(reopen), pool.submit(reopen)
            stores = [a.result(), b.result()]
        web = StudentLearning(stores[0], [desk.binding], Principal(owner.subject, frozenset([course])))
        old_revision = digest(['review',answer])
        assert web.get(course, record_id) == {'status':'review','note':answer,'revision':old_revision}
        legacy, = command(studio, state, 'review_list')['items']
        assert legacy['cue'] == '' and 'note' not in legacy and answer not in legacy.values()
        saved = command(studio, state, 'review_save', **identity, status='review',
                        cue='What is the equation?', version=legacy['version'])
        assert saved['cue'] == 'What is the equation?' and 'note' not in saved
        current = web.get(course, record_id)
        assert current['note'] == answer
        with pytest.raises(ProgressConflict):
            web.save(course, record_id, 'confident', 'New answer', expected_revision=old_revision)
        new_note = web.save(course, record_id, 'confident', 'New answer', expected_revision=current['revision'])
        with pytest.raises(ProgressConflict):
            command(studio, state, 'review_save', **identity, status='review', cue='Stale', version=saved['version'])
        updated, = command(studio, state, 'review_list')['items']
        assert updated['cue'] == saved['cue'] and updated['version'] == new_note['revision']
        cleared = command(studio, state, 'review_save', **identity, status='review', cue='', version=updated['version'])
        assert cleared['cue'] == '' and web.get(course, record_id)['note'] == 'New answer'
