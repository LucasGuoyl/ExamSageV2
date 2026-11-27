import io
import json
from pathlib import Path

import pytest


def make_import(root, files=None):
    from examsage.web_intake import import_selection
    sources = files if files is not None else [
        ('讲义.txt', io.BytesIO('条件一。\f条件二。'.encode())),
        ('讲义.txt', io.BytesIO('补充材料。'.encode()))]
    return import_selection(root, '数学导论', '数学', sources)


def test_selection_yields_reviewable_library_and_study_route(tmp_path):
    from examsage.plugin_tools import load_library
    result = make_import(tmp_path)
    folder = tmp_path / result['id']
    assert (folder/'draft/pack.json').is_file()
    assert (folder/'library/course-reader.html').is_file()
    assert result['documents'] == 2 and result['pages'] == 3
    assert result['semantic_review'] == 'pending'
    assert result['study_url'] == '/courses/upload-' + result['id'] + '/'
    assert result['reader_url'] == '/import/' + result['id'] + '/reader'
    catalog = json.loads((folder/'library/library.json').read_text(encoding='utf-8'))
    course = catalog['courses'][0]['slug']
    tools = load_library(folder/'library', [course])
    binding, store = tools._course(course)
    docs = store.manifest(binding.scope).documents
    assert len(docs) == 2 and docs[0].relative_path != docs[1].relative_path
    page = tools.call('get_source_page', dict(course_id=course, document_id=docs[0].id, page=2))
    assert page['records'][0]['text'] == '条件二。'
    assert page['sources'][0]['refs'][0]['filename'] == '讲义.txt'


@pytest.mark.parametrize('name,data', [('a.pdf', b'broken'), ('../test.txt', b'x'),
    ('C:bad.txt', b'x'), ('CON.txt', b'x'), ('a.html', b'x'), ('empty.txt', b'')])
def test_bad_selection_does_not_publish(tmp_path, name, data):
    with pytest.raises(ValueError):
        make_import(tmp_path, [('valid.txt', io.BytesIO(b'valid')), (name, io.BytesIO(data))])
    assert not list(tmp_path.iterdir())


def test_study_receipt_detects_changed_authorization(tmp_path):
    from examsage.web_intake import imported_course
    result = make_import(tmp_path)
    data = imported_course(tmp_path, result['id'])
    scope = json.loads((data/'current.json').read_text())
    scope['allowed_sources'].pop()
    (data/'current.json').write_text(json.dumps(scope))
    with pytest.raises(ValueError):
        imported_course(tmp_path, result['id'])


def test_new_course_study_distinguishes_pages_from_curated_exam_answers(tmp_path):
    from examsage.web_intake import imported_course
    from examsage.api import create_app
    from test_chat_api import endpoint
    result = make_import(tmp_path)
    app = create_app(imported_course(tmp_path, result['id']), chat_runner=object())
    status = endpoint(app, '/api/status')()
    assert status['structure_mode'] == 'source_pages' and not status['whole_questions']
    found = endpoint(app, '/api/search')('2024 年真题')
    assert not found.records
    assert any('逐题结构尚未验证' in warning for warning in found.limitations)


def test_normal_home_to_new_course_http(tmp_path):
    from fastapi.testclient import TestClient
    from examsage.library import create_library_app
    from examsage.web_intake import imported_course
    root = tmp_path/'uploads'
    existing = make_import(tmp_path/'seed')
    app = create_library_app(imported_course(tmp_path/'seed', existing['id']),
                             import_root=root, chat_runner=object())
    client = TestClient(app, base_url='http://localhost', client=('127.0.0.1', 52146))
    assert 'href="/import/"' in client.get('/').text
    assert '课程文件' in client.get('/import/').text
    form = {'name':'地球科学', 'discipline':'地球物理'}
    files = [('files', ('课程.txt', '春季资料：岩石'.encode(), 'text/plain'))]
    assert client.post('/import/', data=form, files=files, headers={'Origin':'http://other.test'}).status_code == 403
    response = client.post('/import/', data=form, files=files, headers={'Origin':'http://localhost'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert client.get(result['reader_url']).status_code == 200
    assert '学习对话' in client.get(result['study_url']).text
    status = client.get(result['study_url']+'api/status').json()
    assert status['course'] == form['name'] and status['structure_mode'] == 'source_pages'
    records = client.get(result['study_url']+'api/search', params={'q':'岩石'}).json()['records']
    assert any('春季资料' in record['text'] for record in records)
    assert client.get('/api/search', params={'q':'岩石'}).json()['records'] == []


def test_local_standalone_course_folder_name_can_be_chinese(tmp_path):
    from examsage.library import create_library_app
    from examsage.web_intake import imported_course
    result = make_import(tmp_path/'seed')
    folder = tmp_path/'课程 A'
    imported_course(tmp_path/'seed', result['id']).rename(folder)
    app = create_library_app(folder, import_root=tmp_path/'uploads', chat_runner=object())
    assert any(route.path == '/import' for route in app.routes)


def test_long_selected_name_is_preserved_without_partial_staging(tmp_path):
    from examsage.web_intake import imported_course
    filename = 'x' * 160 + '.txt'
    root = tmp_path/'uploads'
    result = make_import(root, [(filename, io.BytesIO(b'Long source name.'))])
    folder = imported_course(root, result['id'])
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['documents'][0]['relative_path'].endswith('/' + filename)
    assert [path.name for path in root.iterdir()] == [result['id']]
