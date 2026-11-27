import json
from shutil import copytree

import pytest
from fastapi import HTTPException

from examsage.chat_runner import ChatRunner
from examsage.student_web import create_student_app
from examsage.student_workspace import student_tools
from test_chat_api import endpoint
from test_student_web import local_upload, mount, public_library, read_course_route, student


def test_withdrawn_shared_course_leaves_other_courses_available_on_both_hosts(tmp_path):
    default = public_library(tmp_path)
    workspace = student(tmp_path/'students','A',['common','optional'])
    private_id = 'upload-' + local_upload(workspace,'Example')['id']
    runner = ChatRunner(workspace.chats,runtime=object())
    try:
        app = create_student_app(default,workspace,chat_runner=runner)
        tools = student_tools(tmp_path,workspace)
        old = mount(app,'/courses/common')
        assert read_course_route(old,'/api/documents')
        registry = tmp_path/'library.json'
        registry.write_text(json.dumps({'courses':[{'slug':'optional','data':'optional'}]}))
        rows = endpoint(app,'/api/courses')()
        assert {row['slug']:row['name'] for row in rows} == {'optional':'Course',private_id:'同名私课'}
        assert {row['course_id'] for row in tools.call('list_courses',{})['courses']} == {'optional',private_id}
        assert 'href="/courses/common/"' not in endpoint(app,'/')()
        with pytest.raises(HTTPException) as error:
            read_course_route(old,'/api/documents')
        assert error.value.status_code == 409
        with pytest.raises(ValueError):
            tools.call('get_course_profile',{'course_id':'common'})
    finally:
        runner.close()


def test_relocated_registration_opens_new_folder_and_expires_old_reader(tmp_path):
    default = public_library(tmp_path)
    workspace = student(tmp_path/'students','A',['common'])
    runner = ChatRunner(workspace.chats,runtime=object())
    try:
        app = create_student_app(default,workspace,chat_runner=runner)
        old = mount(app,'/courses/common')
        copytree(default,tmp_path/'edition-two')
        (tmp_path/'library.json').write_text(json.dumps({'courses':[{'slug':'common','data':'edition-two'}]}))
        with pytest.raises(HTTPException) as error:
            read_course_route(old,'/api/documents')
        assert error.value.status_code == 409
        assert read_course_route(mount(app,'/courses/common'),'/api/documents')
        assert endpoint(app,'/api/courses')()[0]['name']=='Course'
    finally:
        runner.close()
