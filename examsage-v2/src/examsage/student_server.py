"""Run the loopback personal web app for the current operating-system account."""
import json
from pathlib import Path

import uvicorn

from .chat_runner import ChatRunner
from .chat_store import StudentServerBusy, student_process_lock
from .student_web import create_student_app
from .student_workspace import local_workspace


def serve_student(library: Path, workspace_root: Path, courses: list[str] | None, port: int):
    if not 1 <= port <= 65535:
        raise ValueError('端口应在 1 至 65535 之间。')
    registry = library/'library.json'
    entries = []
    if courses or (courses is None and registry.is_file()):
        entries = json.loads(registry.read_text(encoding='utf-8'))['courses']
    registered = [entry['slug'] for entry in entries]
    grants = registered if courses is None else courses
    if not set(grants).issubset(registered):
        raise ValueError('所选公共课程未在课程库登记。')
    workspace = local_workspace(workspace_root,grants)
    with student_process_lock(workspace.chats):
        if courses is not None:
            workspace.remember_public_grants()
        runner = ChatRunner(workspace.chats)
        try:
            app = create_student_app(registry if grants else None,workspace,chat_runner=runner)
            uvicorn.run(app,host='127.0.0.1',port=port,proxy_headers=False)
        finally:
            runner.close()
