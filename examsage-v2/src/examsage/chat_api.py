"""Local-only chat endpoints mounted within a server-selected course."""
from pathlib import Path
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from .chat_runner import get_runner
from .chat_store import ChatConflict, ChatNotFound
from .domain import Model, Scope, digest


SCOPE_CHANGED = '课程资料或可访问范围已更新，请重启押题宝后重新打开课程。'


def chat_storage_root():
    """Optional local test instance; browser input cannot select this location."""
    root = (Path(__file__).resolve().parents[2] / 'data').resolve()
    instance = os.environ.get('EXAMSAGE_CHAT_INSTANCE', '')
    if instance and not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', instance):
        raise ValueError('Invalid local chat instance name')
    target = (root / 'chat-instances' / instance if instance else root / 'chat').resolve()
    if not target.is_relative_to(root):
        raise ValueError('Chat storage must remain inside project data')
    return target


class NewSession(Model):
    title: str = Field(default='新对话', min_length=1, max_length=120)


class SendMessage(Model):
    text: str = Field(min_length=1, max_length=4000)
    client_request_id: str = Field(min_length=1, max_length=128)


def install_chat(app, data, store, scope, runner=None, *, course_id=None, is_authorized=None):
    data = Path(data)
    # Published course packages stay immutable, including when served in place.
    manager = runner or get_runner(chat_storage_root())
    initial = digest(scope.model_dump(mode='json'))
    router = APIRouter(prefix='/api/chat')

    def current_scope():
        if is_authorized is not None:
            try:
                granted = is_authorized()
            except (OSError, ValueError, KeyError, TypeError):
                granted = False
            if not granted:
                raise HTTPException(409, SCOPE_CHANGED)
        try:
            current = Scope.model_validate_json((data / 'current.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            notice = '课程范围暂时无法读取，请重新打开课程。' if is_authorized else '课程范围无法读取，已停止访问聊天记录。'
            raise HTTPException(503, notice) from None
        if digest(current.model_dump(mode='json')) != initial:
            notice = SCOPE_CHANGED if is_authorized else '课程资料或可访问范围已更新，请重启押题宝后新建对话。'
            raise HTTPException(409, notice)
        return scope

    async def write_boundary(request: Request):
        if request.method == 'POST':
            content_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
            if content_type != 'application/json' or request.headers.get('sec-fetch-site') == 'cross-site':
                raise HTTPException(403, '请从押题宝本机页面提交请求。')

    router.dependencies = [Depends(write_boundary)]

    def invoke(fn, *args):
        try: return fn(*args)
        except ChatNotFound: raise HTTPException(404, '当前课程和资料范围内没有这个对话或回答。') from None
        except ChatConflict as exc: raise HTTPException(409, str(exc)) from None
        except ValueError: raise HTTPException(422, '输入内容无效，请检查文字长度。') from None

    @router.get('/status')
    def status(s=Depends(current_scope)):
        return manager.status()

    @router.post('/connect')
    def connect(s=Depends(current_scope)):
        return invoke(manager.check_connection)

    @router.get('/sessions')
    def sessions(s=Depends(current_scope)):
        return invoke(manager.store.list_sessions, s)

    @router.post('/sessions')
    def create(body: NewSession, s=Depends(current_scope)):
        return invoke(manager.store.create_session, s, body.title)

    @router.get('/sessions/{session_id}/messages')
    def messages(session_id: str, s=Depends(current_scope)):
        return invoke(manager.store.messages, s, session_id)

    @router.post('/sessions/{session_id}/messages')
    def send(session_id: str, body: SendMessage, s=Depends(current_scope)):
        return invoke(manager.submit, store, s, session_id, body.text, body.client_request_id, current_scope, course_id)

    @router.get('/runs/{run_id}')
    def run(run_id: str, s=Depends(current_scope)):
        return invoke(manager.get_run, s, run_id)

    @router.post('/runs/{run_id}/cancel')
    def cancel(run_id: str, s=Depends(current_scope)):
        return invoke(manager.cancel, s, run_id)

    app.include_router(router)
    app.state.chat_runner = manager
    return current_scope
