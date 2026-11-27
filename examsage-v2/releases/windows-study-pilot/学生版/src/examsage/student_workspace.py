"""A personal course catalog selected by the host before any model tool call."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .import_receipt import checked_child, read_import
from .domain import Scope
from .ingest import atomic_json
from .plugin_tools import CourseArgs, CourseBinding, PluginTools, Principal
from .storage import Store
from .source_paths import source_path


class StudentWorkspace:
    def __init__(self,root: Path,principal: Principal):
        subject = principal.subject
        if not isinstance(subject,str) or not subject.strip() or len(subject)>200:
            raise ValueError('Trusted student subject required')
        self.principal = Principal(subject,frozenset(principal.course_ids))
        if any(cid.startswith('upload-') for cid in self.principal.course_ids):
            raise ValueError('Private course IDs are assigned by the student import store')
        self.root = Path(root).resolve()
        self._key = hashlib.sha256(('student-workspace-v1\0'+subject).encode()).hexdigest()[:32]

    def _area(self,kind):
        return checked_child(checked_child(self.root,self._key),kind)

    @property
    def imports(self):
        return self._area('imports')

    @property
    def chats(self):
        return self._area('chat')

    def learning_database(self, course_id):
        # Two authorized course offerings may use exactly the same content snapshot.
        course_key = hashlib.sha256(course_id.encode('utf-8')).hexdigest()
        return checked_child(self._area('learning'),course_key+'.sqlite3')

    def remember_public_grants(self):
        """Called by the trusted local launcher under its student process lock."""
        atomic_json(self._area('public-courses.json'),sorted(self.principal.course_ids))

    def effective_public_grants(self):
        try:
            grants = json.loads(self._area('public-courses.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            return self.principal.course_ids
        except (OSError,ValueError):
            return frozenset()
        if not isinstance(grants,list) or not all(isinstance(cid,str) for cid in grants):
            return frozenset()
        return self.principal.course_ids.intersection(grants)

    def public_entries(self,library):
        grants = self.effective_public_grants()
        if not grants or library is None:
            return {}
        try:
            registry = json.loads((library/'library.json').read_bytes())
            rows = registry['courses']
            if not isinstance(rows,list):
                return {}
        except (OSError,ValueError,KeyError,TypeError):
            return {}
        entries = {}
        for row in rows:
            try:
                slug = row['slug']
                if slug not in grants:
                    continue
                CourseArgs(course_id=slug)
                entries[slug] = (checked_child(library,row['data']),row.get('name'))
            except (OSError,ValueError,KeyError,TypeError):
                continue
        return entries

    def _open(self,batch_id):
        result,data,scope = read_import(self.imports,batch_id)
        binding = CourseBinding('upload-'+batch_id,checked_child(data,'course.sqlite3'),scope)
        try:
            store = Store(binding.database,read_only=True)
            if store.manifest(scope) is None:
                raise ValueError('Snapshot unavailable')
        except sqlite3.DatabaseError:
            raise ValueError('Course data unavailable') from None
        return result,binding,store

    def open_import(self,batch_id):
        _,binding,_ = self._open(batch_id)
        return binding.database.parent

    def private_catalog(self):
        root = self.imports
        if not root.exists():
            return []
        catalog = []
        for batch in sorted(root.iterdir()):
            try:
                result,_,_ = self._open(batch.name)
            except (ValueError,OSError,KeyError,TypeError):
                continue
            slug = 'upload-'+batch.name
            catalog.append({'slug':slug,'name':result['name'],'url':f'/courses/{slug}/'})
        return catalog


def recipient_workspace_root():
    """The profile directory belongs to the local host, never to tool arguments."""
    folder = os.environ.get('LOCALAPPDATA', '')
    if not folder and os.name == 'nt':
        # A desktop host may filter environment variables in plugin processes.
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 28, None, 0, buffer) == 0:
            folder = buffer.value
    if not folder or not Path(folder).is_absolute():
        raise ValueError('Windows local application data directory unavailable')
    return source_path(Path(folder)/'ExamSage'/'student-workspaces')


def local_workspace(root,courses):
    """Local pilot identity from the executing OS account. No browser or model override."""
    if os.name == 'nt':
        from ctypes import wintypes
        name = ctypes.create_unicode_buffer(512)
        size = wintypes.ULONG(len(name))
        # NameSamCompatible supplies the domain or local machine as well as the user.
        if not ctypes.windll.secur32.GetUserNameExW(2,name,ctypes.byref(size)) or not name.value:
            raise RuntimeError('Cannot identify the current Windows account')
        subject = 'windows:'+name.value.casefold()
    else:
        subject = 'local-uid:'+str(os.getuid())
    return StudentWorkspace(root,Principal(subject,frozenset(courses)))


class StudentCourseTools(PluginTools):
    def __init__(self,library,workspace):
        super().__init__([],workspace.principal)
        self.library = library
        self.workspace = workspace

    def catalog_courses(self):
        public = self.workspace.public_entries(self.library)
        private = {course['slug'] for course in self.workspace.private_catalog()}
        for slug in sorted(public.keys() | private):
            try:
                if slug in public:
                    yield self.open_public(slug,public[slug][0])
                else:
                    yield self._course(slug)
            except (OSError,ValueError,KeyError,TypeError,sqlite3.DatabaseError):
                continue

    @staticmethod
    def open_public(slug,folder):
        scope = Scope.model_validate_json(checked_child(folder,'current.json').read_bytes())
        binding = CourseBinding(slug,checked_child(folder,'course.sqlite3'),scope)
        store = Store(binding.database,read_only=True)
        if store.manifest(scope) is None:
            raise ValueError('Snapshot unavailable')
        return binding,store

    def _course(self,course_id):
        if not course_id.startswith('upload-'):
            entry = self.workspace.public_entries(self.library).get(course_id)
            if entry is None:
                raise ValueError('Course unavailable in the authorized scope')
            return self.open_public(course_id,entry[0])
        try:
            _,binding,store = self.workspace._open(course_id.removeprefix('upload-'))
        except (ValueError,OSError,KeyError,TypeError):
            raise ValueError('Course unavailable in the authorized scope') from None
        return binding,store


def student_tools(library,workspace):
    return StudentCourseTools(library,workspace)
