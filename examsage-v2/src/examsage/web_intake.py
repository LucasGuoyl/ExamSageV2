"""Browser-selected materials for the local course owner."""
from functools import lru_cache
import ipaddress
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from .course_draft import MaterialConflict
from .course_profile import CURRICULUM_LABELS
from .import_receipt import imported_course
from .student_import import MAX_FILES, MAX_REQUEST_BYTES, import_selection

WEB = Path(__file__).with_name('web')
STUDENT_HOME_LINK = '<a href="/">我的课程</a>'


class StudentReaderResponse(StreamingResponse):
    """Add navigation to the online copy while streaming the saved reader unchanged from disk."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(self.chunks(), media_type='text/html')

    def chunks(self):
        with self.path.open('rb') as source:
            # Generated readers, including previous exports, have a header before the course JSON.
            for line in source:
                if b'<header>' in line:
                    yield line.replace(b'<header>', b'<header>' + STUDENT_HOME_LINK.encode(), 1)
                    break
                yield line
            while chunk := source.read(64 * 1024):
                yield chunk


def local_request(request):
    if not request.client:
        return False
    try:
        peer = ipaddress.ip_address(request.client.host)
        host = urlsplit('http://' + request.headers.get('host', '')).hostname
        return peer.is_loopback and host in {'127.0.0.1','localhost','::1'}
    except ValueError:
        return False


def install_intake(app, root, catalog, *, chat_runner=None, open_import=None, private_preview_root=None,
                   student_navigation=False, open_learning=None):
    gate = threading.Lock()
    intake = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    def open_course(batch_id):
        return open_import(batch_id) if open_import is not None else imported_course(root, batch_id)

    def unavailable(exc):
        if open_import is not None and isinstance(exc, (ValueError, KeyError, TypeError)):
            from .chat_api import SCOPE_CHANGED
            return HTTPException(409, SCOPE_CHANGED)
        return HTTPException(404, '此课程或来源范围已变更。')

    @intake.middleware('http')
    async def boundary(request, call_next):
        if not local_request(request):
            return JSONResponse({'detail':'仅可在本机导入课件。'}, status_code=403)
        if request.method == 'POST' and (request.headers.get('origin') != str(request.url).split('/import/')[0]
                or request.headers.get('sec-fetch-site') == 'cross-site'):
            return JSONResponse({'detail':'请从押题宝导入页提交课件。'}, status_code=403)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                                 'Referrer-Policy':'no-referrer', 'X-Frame-Options':'DENY'})
        return response

    @intake.get('/')
    def form():
        return FileResponse(WEB/'course-intake.html', media_type='text/html')

    @intake.post('/')
    async def submit(request: Request):
        if request.headers.get('content-type', '').split(';', 1)[0].lower() != 'multipart/form-data':
            raise HTTPException(415, '请使用课件选择表单。')
        if not gate.acquire(blocking=False):
            raise HTTPException(409, '已有课程正在导入，请稍后再试。')
        async def limited_stream():
            size = 0
            try:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_REQUEST_BYTES:
                        raise MultiPartException('课件总量超过 64 MiB。')
                    yield chunk
            except ClientDisconnect as exc:
                raise MultiPartException('上传已中断。') from exc
        try:
            parser = MultiPartParser(request.headers, limited_stream(), max_files=MAX_FILES,
                                     max_fields=3 + len(CURRICULUM_LABELS), max_part_size=32768)
            form_data = await parser.parse()
            try:
                files = form_data.getlist('files')
                expected = {'name','discipline','files'}
                if (not expected <= set(form_data) <= expected.union({'materials'}, CURRICULUM_LABELS)
                        or any(len(form_data.getlist(k)) != 1 or not isinstance(form_data[k],str)
                               for k in set(form_data)-{'files'})
                        or not all(isinstance(f, UploadFile) for f in files)):
                    raise HTTPException(422, '请填写课程名称、学科，并选择课件。')
                materials = None
                if 'materials' in form_data:
                    materials = json.loads(form_data['materials'])
                    if not isinstance(materials,list):
                        raise ValueError('Expected material declarations')
                curriculum = {key: form_data[key] for key in CURRICULUM_LABELS if key in form_data}
                if any(len(value) > 200 for value in curriculum.values()):
                    raise HTTPException(422, '课程体系登记每项限 200 字。')
                return await run_in_threadpool(import_selection, root, form_data['name'], form_data['discipline'],
                        [(f.filename or '', f.file) for f in files], materials=materials, curriculum=curriculum,
                        record_receipt=True)
            finally:
                await form_data.close()
        except MaterialConflict as exc:
            raise HTTPException(422, str(exc)) from exc
        except (ValueError, MultiPartException, OSError) as exc:
            raise HTTPException(422, '导入失败。请检查文件格式、文件名和大小。') from exc
        finally:
            gate.release()

    @intake.get('/{batch_id:uuid}/reader')
    def reader(batch_id: UUID):
        try:
            open_course(str(batch_id))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise unavailable(exc) from None
        path = root/str(batch_id)/'library/course-reader.html'
        if student_navigation:
            return StudentReaderResponse(path)
        return FileResponse(path, media_type='text/html')

    @lru_cache(maxsize=8)
    def study_app(data, slug, _scope_bytes):
        from .api import create_app
        course_catalog = catalog
        if not callable(catalog):
            receipt = json.loads((root/slug/'import.json').read_text(encoding='utf-8'))['result']
            course_catalog = [*catalog, {'slug':'upload-' + slug, 'name':receipt['name'], 'url':receipt['study_url']}]
        return create_app(data, course_catalog, chat_runner=chat_runner, course_id='upload-' + slug,
                          student_navigation=student_navigation,open_learning=open_learning,
                          private_preview_root=private_preview_root,
                          is_authorized=(lambda: open_import(slug) == data) if open_import is not None else None)

    async def study(scope, receive, send):
        if scope['type'] != 'http':
            return
        if not local_request(Request(scope)):
            return await JSONResponse({'detail':'仅可在本机访问。'}, 403)(scope, receive, send)
        slug = str(scope['path_params']['batch_id'])
        try:
            data = open_course(slug)
            scope_bytes = (data/'current.json').read_bytes()
        except (ValueError, OSError, KeyError, TypeError) as exc:
            error = unavailable(exc)
            return await JSONResponse({'detail': error.detail},error.status_code)(scope, receive, send)
        await study_app(data, slug, scope_bytes)(scope, receive, send)

    app.mount('/import', intake)
    app.mount('/courses/upload-{batch_id:uuid}', study)
