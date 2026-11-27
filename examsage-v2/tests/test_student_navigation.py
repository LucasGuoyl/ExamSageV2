"""Navigation on the student host and portable standalone readers."""
from html.parser import HTMLParser
from uuid import UUID

import pytest

from examsage.chat_runner import ChatRunner
from examsage.library import create_library_app
from examsage.student_web import create_student_app
from test_chat_api import endpoint
from test_student_web import local_upload, mount, public_library, student


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.href = None
        self.items = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.items.append((''.join(self.label).strip(), self.href))
            self.href = None


@pytest.mark.parametrize('view', ['shared course', 'uploaded reader'])
def test_my_courses_link_on_student_pages(tmp_path, view):
    data = public_library(tmp_path)
    workspace = student(tmp_path/'students', 'one', ['common'])
    runner = ChatRunner(workspace.chats, runtime=object())
    try:
        app = create_student_app(data, workspace, chat_runner=runner)
        if view == 'shared course':
            html = endpoint(mount(app, '/courses/common'), '/')()
        else:
            item = local_upload(workspace, '多页复习资料')
            reader = endpoint(mount(app, '/import'), '/{batch_id:uuid}/reader')(UUID(item['id']))
            file = workspace.imports/item['id']/'library/course-reader.html'
            original = file.read_bytes()
            assert ('我的课程', '/') not in Links(original.decode()).items
            body = b''.join(reader.chunks())
            assert file.read_bytes() == original
            assert body[body.index(b'<main>'):] == original[original.index(b'<main>'):]
            html = body.decode()
        assert ('我的课程', '/') in Links(html).items
    finally:
        runner.close()


def test_ordinary_course_home_keeps_existing_navigation(tmp_path):
    app = create_library_app(public_library(tmp_path), import_root=tmp_path/'uploads', chat_runner=object())
    html = endpoint(mount(app, ''), '/')()
    links = Links(html).items
    assert ('我的课程', '/') not in links
    assert ('导入课件', '/import/') in links
