import json

import pytest
from fastapi import HTTPException

from examsage.api import create_app
from examsage.chat_runner import ChatRunner
from examsage.domain import digest
from test_chat_service import setup


def make_app(tmp_path):
    store, scope = setup(tmp_path)
    (tmp_path / 'current.json').write_text(scope.model_dump_json(), encoding='utf-8')
    runner = ChatRunner(tmp_path / 'private-chat')
    return create_app(tmp_path, chat_runner=runner), scope, runner


def routes(app):
    # Current FastAPI retains lazy IncludedRouter wrappers until dispatch.
    for route in app.routes:
        if hasattr(route, 'original_router'):
            yield from routes(route.original_router)
        else:
            yield route


def endpoint(app, path, method='GET'):
    return next(r.endpoint for r in routes(app) if getattr(r, 'path', None) == path and method in r.methods)


def test_create_app_does_not_enable_optional_paid_embeddings(tmp_path, monkeypatch):
    import examsage.api as module
    def forbidden(*args): raise AssertionError('external embedding branch must not run')
    monkeypatch.setattr(module, 'service_for', forbidden, raising=False)
    app, scope, manager = make_app(tmp_path)
    assert endpoint(app, '/api/search')('Darcy').records
    assert endpoint(app, '/api/chat/status')(scope)['status'] == 'unchecked'
    manager.close()


def test_changed_scope_blocks_old_history_before_store_access(tmp_path):
    app, scope, manager = make_app(tmp_path)
    route = next(r for r in routes(app) if getattr(r, 'path', None) == '/api/chat/sessions')
    get_scope = next(d.call for d in route.dependant.dependencies if d.call.__name__ == 'current_scope')
    assert get_scope() == scope
    narrowed = scope.model_copy(update={'allowed_sources': []})
    (tmp_path / 'current.json').write_text(narrowed.model_dump_json(), encoding='utf-8')
    with pytest.raises(HTTPException) as error: get_scope()
    assert error.value.status_code == 409
    manager.close()


def test_chat_routes_return_not_found_for_wrong_course(tmp_path):
    app, scope, manager = make_app(tmp_path)
    session = manager.store.create_session(scope)
    read = endpoint(app, '/api/chat/sessions/{session_id}/messages')
    assert read(session['id'], scope) == []
    with pytest.raises(HTTPException) as error:
        read(session['id'], scope.model_copy(update={'course': 'other'}))
    assert error.value.status_code == 404
    manager.close()


def test_verification_instance_does_not_recover_or_expose_main_instance_runs(tmp_path, monkeypatch):
    import examsage.chat_api as module
    store, scope = setup(tmp_path / 'course')
    (tmp_path / 'course/current.json').write_text(scope.model_dump_json(), encoding='utf-8')
    managers = []
    # Map every requested storage path to this test's temp tree, including RED.
    def isolated_runner(path):
        manager = ChatRunner(tmp_path / 'private' / digest(str(path)))
        managers.append(manager); return manager
    monkeypatch.setattr(module, 'get_runner', isolated_runner)
    monkeypatch.delenv('EXAMSAGE_CHAT_INSTANCE', raising=False)
    main = create_app(tmp_path / 'course').state.chat_runner
    session = main.store.create_session(scope)
    run = main.store.begin_run(scope, session['id'], 'Darcy', 'active-main')
    try:
        monkeypatch.setenv('EXAMSAGE_CHAT_INSTANCE', 'verification-8768')
        verification = create_app(tmp_path / 'course').state.chat_runner
        assert main.store.get_run(scope, run['id'])['status'] == 'running'
        assert verification.data != main.data
        assert verification.store.list_sessions(scope) == []
    finally:
        for manager in managers: manager.close()


@pytest.mark.parametrize('name', ['../outside', 'C:\\outside', 'a/b', '.', 'x'*49])
def test_instance_name_cannot_select_arbitrary_storage(tmp_path, monkeypatch, name):
    from examsage.chat_api import chat_storage_root
    monkeypatch.setenv('EXAMSAGE_CHAT_INSTANCE', name)
    with pytest.raises(ValueError): chat_storage_root()
