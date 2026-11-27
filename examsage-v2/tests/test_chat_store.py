"""Conversation persistence and authorization using a real independent SQLite file."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from importlib import import_module
import sqlite3
from threading import Barrier

import pytest

from examsage.domain import Scope


@pytest.fixture
def chat():
    return import_module('examsage.chat_store')


@pytest.fixture
def scope():
    return Scope(workspace='local', course='grt', snapshot='snapshot-a',
                 allowed_sources=['lecture', 'exam'])


def test_messages_and_citations_persist_without_writing_the_course_database(tmp_path, chat, scope):
    course = tmp_path / 'course.sqlite3'
    course.write_bytes(b'course snapshot sentinel')
    path = tmp_path / 'chat' / 'chat.sqlite3'
    store = chat.ChatStore(path)
    session = store.create_session(scope, '  Darcy 追问  ')
    assert session['title'] == 'Darcy 追问'
    run = store.begin_run(scope, session['id'], '通量与流速有什么区别？', 'request-1')
    answer = {'text': '孔隙流速需要考虑孔隙度。', 'citations': [{'id': 'E1', 'page': 9}]}
    assert store.finish_run(scope, run['id'], answer)

    reopened = chat.ChatStore(path)
    assert reopened.get_session(scope, session['id'])['title'] == 'Darcy 追问'
    assert [s['id'] for s in reopened.list_sessions(scope)] == [session['id']]
    messages = reopened.messages(scope, session['id'])
    assert [(m['role'], m['content']) for m in messages] == [
        ('user', '通量与流速有什么区别？'), ('assistant', '孔隙流速需要考虑孔隙度。')]
    assert messages[1]['answer'] == answer
    assert all(m['created_at'] for m in messages)
    assert reopened.get_run(scope, run['id'])['answer'] == answer
    assert course.read_bytes() == b'course snapshot sentinel'


def test_course_database_cannot_be_reused_as_chat_storage(tmp_path, chat):
    path = tmp_path / 'course.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE snapshots(id TEXT); CREATE TABLE records(id TEXT);')
    original = path.read_bytes()
    with pytest.raises(ValueError, match='course database'):
        chat.ChatStore(path)
    assert path.read_bytes() == original


@pytest.mark.parametrize('diagnostics', [{'trace': 'x' * 64001}, {'value': float('nan')}])
def test_invalid_or_excessive_diagnostics_do_not_leave_a_failed_run_active(tmp_path, chat, scope, diagnostics):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], 'Darcy', 'diagnostics-boundary')
    assert store.fail_run(scope, run['id'], 'tool_limit', 'Reached limit', diagnostics=diagnostics)
    saved = store.get_run(scope, run['id'])
    assert saved['status'] == 'failed' and saved['answer'] is None
    assert saved['error']['diagnostics'] == {'omitted': 'diagnostic_limit_or_invalid'}
    assert [m['role'] for m in store.messages(scope, session['id'])] == ['user']


def test_reordered_source_allowlist_still_accesses_the_same_session(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    reordered = scope.model_copy(update={'allowed_sources': ['exam', 'lecture']})
    assert store.get_session(reordered, session['id'])['id'] == session['id']


@pytest.mark.parametrize('changed', [
    {'workspace': 'other'}, {'course': 'ses'}, {'snapshot': 'snapshot-b'},
    {'allowed_sources': ['lecture']}, {'allowed_sources': ['lecture', 'exam', 'extra']},
    {'cutoff': date(2024, 1, 1)}, {'cutoff': date(2024, 1, 1), 'strict_history': True},
])
def test_every_operation_rejects_a_different_scope(tmp_path, chat, scope, changed):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], '问题', 'r1')
    different = scope.model_copy(update=changed)
    assert store.list_sessions(different) == []
    operations = [
        lambda: store.get_session(different, session['id']),
        lambda: store.messages(different, session['id']),
        lambda: store.begin_run(different, session['id'], '新问题', 'r2'),
        lambda: store.get_run(different, run['id']),
        lambda: store.finish_run(different, run['id'], {'text': '答案'}),
        lambda: store.fail_run(different, run['id'], 'test', '错误'),
        lambda: store.cancel_run(different, run['id']),
    ]
    for operation in operations:
        with pytest.raises(chat.ChatNotFound):
            operation()
    assert store.get_run(scope, run['id'])['status'] == 'running'
    assert len(store.messages(scope, session['id'])) == 1


def test_concurrent_duplicate_send_creates_one_run_and_one_user_message(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    barrier = Barrier(6)

    def send(_):
        barrier.wait(timeout=10)
        return store.begin_run(scope, session['id'], '重复提交', 'same-request')

    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = list(pool.map(send, range(6)))
    assert len({run['id'] for run in runs}) == 1
    assert [m['content'] for m in store.messages(scope, session['id'])] == ['重复提交']


def test_concurrent_distinct_sends_allow_one_active_run(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    barrier = Barrier(2)

    def send(request):
        barrier.wait(timeout=10)
        try:
            return store.begin_run(scope, session['id'], '问题 ' + request, request)['status']
        except chat.ChatConflict:
            return 'conflict'

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(send, ['a', 'b']))
    assert sorted(result) == ['conflict', 'running']
    assert len(store.messages(scope, session['id'])) == 1


def test_reused_request_id_requires_identical_text_even_after_completion(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], '原问题', 'r1')
    with pytest.raises(chat.ChatConflict):
        store.begin_run(scope, session['id'], '另一个问题', 'r1')
    assert store.finish_run(scope, run['id'], {'text': '回答'})
    retry = store.begin_run(scope, session['id'], '原问题', 'r1')
    assert retry['id'] == run['id'] and retry['status'] == 'completed'
    assert len(store.messages(scope, session['id'])) == 2
    following = store.begin_run(scope, session['id'], '追问', 'r2')
    assert following['id'] != run['id']


def test_cancelled_run_rejects_late_results_and_allows_a_new_turn(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], '问题', 'r1')
    assert store.cancel_run(scope, run['id'])['status'] == 'cancelled'
    assert not store.finish_run(scope, run['id'], {'text': '迟到答案'})
    assert not store.fail_run(scope, run['id'], 'late', '迟到错误')
    assert store.cancel_run(scope, run['id'])['status'] == 'cancelled'
    assert [m['role'] for m in store.messages(scope, session['id'])] == ['user']
    assert store.begin_run(scope, session['id'], '继续', 'r2')['status'] == 'running'


def test_complete_and_failure_are_terminal_and_do_not_duplicate_messages(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    first = store.begin_run(scope, session['id'], '一', 'r1')
    assert store.finish_run(scope, first['id'], {'text': '答案'})
    assert not store.finish_run(scope, first['id'], {'text': '第二份答案'})
    assert store.cancel_run(scope, first['id'])['status'] == 'completed'
    second = store.begin_run(scope, session['id'], '二', 'r2')
    assert store.fail_run(scope, second['id'], 'usage_limit', '套餐额度不足')
    assert not store.finish_run(scope, second['id'], {'text': '错误兜底'})
    assert store.get_run(scope, second['id'])['error'] == {
        'code': 'usage_limit', 'message': '套餐额度不足'}
    assert [m['content'] for m in store.messages(scope, session['id'])] == ['一', '答案', '二']


def test_reopening_does_not_interrupt_live_run_until_explicit_recovery(tmp_path, chat, scope):
    path = tmp_path / 'chat.sqlite3'
    store = chat.ChatStore(path)
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], '未完成', 'r1')
    reopened = chat.ChatStore(path)
    assert reopened.get_run(scope, run['id'])['status'] == 'running'
    assert reopened.recover_interrupted() == 1
    interrupted = reopened.get_run(scope, run['id'])
    assert interrupted['status'] == 'failed'
    assert interrupted['error']['code'] == 'interrupted'
    assert reopened.recover_interrupted() == 0
    assert not reopened.finish_run(scope, run['id'], {'text': '恢复后的迟到答案'})
    assert reopened.begin_run(scope, session['id'], '重新发送', 'r2')['status'] == 'running'


def test_recovery_marks_queued_runs_failed_but_preserves_completed_answers(tmp_path, chat, scope):
    path = tmp_path / 'chat.sqlite3'
    store = chat.ChatStore(path)
    session = store.create_session(scope)
    completed = store.begin_run(scope, session['id'], '已完成', 'r1')
    store.finish_run(scope, completed['id'], {'text': '保留答案'})
    queued = store.begin_run(scope, session['id'], '排队中', 'r2')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE chat_runs SET status='queued' WHERE id=?", (queued['id'],))
    assert store.recover_interrupted() == 1
    assert store.get_run(scope, queued['id'])['status'] == 'failed'
    assert store.get_run(scope, completed['id'])['answer'] == {'text': '保留答案'}


def test_cancel_racing_completion_has_one_terminal_result(tmp_path, chat, scope):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], '问题', 'r1')
    barrier = Barrier(2)

    def finish():
        barrier.wait(timeout=10)
        return store.finish_run(scope, run['id'], {'text': '最终答案'})

    def cancel():
        barrier.wait(timeout=10)
        return store.cancel_run(scope, run['id'])

    with ThreadPoolExecutor(max_workers=2) as pool:
        finished = pool.submit(finish)
        cancelled = pool.submit(cancel)
        completion_won, cancel_result = finished.result(), cancelled.result()
    result = store.get_run(scope, run['id'])
    assert result['status'] == ('completed' if completion_won else 'cancelled')
    assert cancel_result['status'] == result['status']
    answers = [m for m in store.messages(scope, session['id']) if m['role'] == 'assistant']
    assert len(answers) == (1 if completion_won else 0)


@pytest.mark.parametrize('title', ['', '   ', 'x' * 121, None, 123, 'bad\x00title'])
def test_invalid_titles_do_not_create_sessions(tmp_path, chat, scope, title):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    with pytest.raises(ValueError):
        store.create_session(scope, title)
    assert store.list_sessions(scope) == []


@pytest.mark.parametrize('text,request_id', [('', 'r'), ('   ', 'r'), ('x' * 4001, 'r'),
    (None, 'r'), ('question', ''), ('question', 'x' * 129), ('question', None)])
def test_invalid_sends_do_not_insert_partial_messages(tmp_path, chat, scope, text, request_id):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    with pytest.raises(ValueError):
        store.begin_run(scope, session['id'], text, request_id)
    assert store.messages(scope, session['id']) == []


@pytest.mark.parametrize('answer', [{}, {'text': ''}, {'text': 7}, {'text': 'ok', 'bad': float('nan')}])
def test_invalid_answer_keeps_run_active_without_partial_assistant_message(tmp_path, chat, scope, answer):
    store = chat.ChatStore(tmp_path / 'chat.sqlite3')
    session = store.create_session(scope)
    run = store.begin_run(scope, session['id'], '问题', 'r1')
    with pytest.raises(ValueError):
        store.finish_run(scope, run['id'], answer)
    assert store.get_run(scope, run['id'])['status'] == 'running'
    assert len(store.messages(scope, session['id'])) == 1


def test_chat_reopens_under_recipient_path_with_uri_characters(tmp_path, chat, scope):
    from examsage.source_paths import source_path
    path = source_path(tmp_path/'学生 #100%'/'chat.sqlite3')
    session = chat.ChatStore(path).create_session(scope, '弹簧实验')
    assert chat.ChatStore(path).get_session(scope, session['id'])['title'] == '弹簧实验'
