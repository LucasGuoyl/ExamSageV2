"""Loopback web app bound by its trusted host to one student's workspace."""
from collections import Counter
from functools import lru_cache
from html import escape
from pathlib import Path
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .api import create_app
from .course_profile import CURRICULUM_LABELS, course_registration
from .learning_state import LearningStore, StudentLearning
from .plugin_tools import Principal
from .student_workspace import student_tools
from .web_intake import WEB, install_intake, local_request


class PublicCourseMount:
    def __init__(self,lookup,build):
        self.lookup = lookup
        self.build = lru_cache(maxsize=1)(build)

    def current_app(self):
        folder = self.lookup()
        if folder is None:
            raise ValueError('Course no longer registered')
        return self.build(folder, (folder/'current.json').read_bytes())

    async def __call__(self,scope,receive,send):
        try:
            app = await run_in_threadpool(self.current_app)
        except (ValueError,OSError,sqlite3.DatabaseError):
            app = JSONResponse({'detail':'课程暂不可用，请返回我的课程。'},status_code=404)
        await app(scope,receive,send)


def create_student_app(default_data, workspace, *, chat_runner):
    """The host owns this runner's model connection and lifecycle."""
    path = getattr(getattr(chat_runner, 'store', None), 'path', None)
    if not chat_runner or path is None or Path(path).resolve() != (workspace.chats/'chat.sqlite3').resolve():
        raise ValueError('A chat runner bound to this student workspace is required')
    library = Path(default_data).resolve().parent if default_data is not None else None
    tools = student_tools(library,workspace)

    def open_learning(slug, expected_scope):
        binding, _ = tools._course(slug)
        if binding.scope != expected_scope:
            raise ValueError('Course scope changed')
        principal = Principal(workspace.principal.subject, frozenset([slug]))
        return StudentLearning(LearningStore(workspace.learning_database(slug)), [binding], principal)

    def catalog():
        entries = workspace.public_entries(library)
        available = []
        for binding,store in tools.catalog_courses():
            slug = binding.course_id
            name = entries.get(slug,(None,None))[1] or store.manifest(binding.scope).course_name
            available.append((slug, name, binding.scope, store))
        counts = Counter(name for _, name, _, _ in available)
        courses = []
        for slug, name, scope, store in available:
            if counts[name] > 1:
                registration = course_registration(store, scope)
                labels = [f'{CURRICULUM_LABELS[key]} {value}' for key, value in registration.items()]
                name += ' · ' + (' · '.join(labels) if labels else '课程体系待补充')
            courses.append({'slug':slug,'name':name,'url':f'/courses/{slug}/'})
        counts = Counter(course['name'] for course in courses)
        return [{**course, 'name':f"{course['name']} · {course['slug'][-8:]}"}
                if counts[course['name']]>1 else course for course in courses]

    app = FastAPI(title='押题宝 · 我的课程', docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def student_boundary(request: Request, call_next):
        if not local_request(request):
            return JSONResponse({'detail':'请从本机学生入口访问。'},status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/api/courses')
    def courses():
        return catalog()

    @app.get('/api/chat/status')
    def status():
        return {**chat_runner.status(), 'workspace_mode':'personal_student'}

    @app.get('/',response_class=HTMLResponse)
    def home():
        groups = {'授权课程': [], '我导入的课程': []}
        for course in catalog():
            entry = f'<a class="enter" href="{escape(course["url"],quote=True)}">{escape(course["name"])}</a>'
            if not course['slug'].startswith('upload-'):
                groups['授权课程'].append(f'<li>{entry}</li>')
            else:
                batch_id = escape(course['slug'].removeprefix('upload-'),quote=True)
                reader = f'<a class="reader" href="/import/{batch_id}/reader">查看导入资料</a>'
                groups['我导入的课程'].append(f'<li>{entry}{reader}</li>')
        sections = [f'<section><h2>{heading}</h2><ul>{"".join(rows)}</ul></section>'
                    for heading, rows in groups.items() if rows]
        menu = ''.join(sections) or '<p class="empty">课程列表为空，导入课件后即可开始学习。</p>'
        return (WEB/'student-home.html').read_text(encoding='utf-8').replace('{{student_courses}}',menu)

    app.mount('/static',StaticFiles(directory=WEB),name='static')
    previews=workspace.chats/'previews'
    install_intake(app,workspace.imports,catalog,chat_runner=chat_runner,open_import=workspace.open_import,
                   private_preview_root=previews,student_navigation=True,open_learning=open_learning)
    def shared_mount(slug):
        def folder():
            entry = workspace.public_entries(library).get(slug)
            return entry[0] if entry else None

        def build(data, _scope_bytes):
            return create_app(data,catalog,chat_runner=chat_runner,course_id=slug,
                              private_preview_root=previews,student_navigation=True,open_learning=open_learning,
                              is_authorized=lambda: folder() == data)

        return PublicCourseMount(folder,build)

    for slug in sorted(workspace.principal.course_ids):
        app.mount('/courses/' + slug,shared_mount(slug))
    return app
