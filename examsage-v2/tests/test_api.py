import json
from pathlib import Path
import pytest
from test_core import example


def make_client(tmp_path,allowed=True):
    from fastapi.testclient import TestClient
    from examsage.api import create_app
    store,m,r=example(tmp_path)
    r.id='doc:p1';r.details={'assets':['../../outside.png']}
    sid=store.publish('w',m,[r],[],{})
    (tmp_path/'current.json').write_text(json.dumps({'workspace':'w','course':'c','snapshot':sid,'allowed_sources':['doc'] if allowed else []}))
    return TestClient(create_app(tmp_path),base_url='http://localhost')


def test_readonly_api_search_and_scope(tmp_path):
    client=make_client(tmp_path)
    assert client.get('/api/search',params={'q':'Darcy'}).json()['records'][0]['id']=='doc:p1'
    assert client.get('/api/status').json()['course']=='Course'
    assert client.post('/api/search',json={'q':'Darcy'}).status_code==405
    assert client.get('/api/search',params={'q':''}).status_code==422
    assert client.get('/api/record/not-here').status_code==404


def test_media_path_cannot_escape_assets(tmp_path):
    client=make_client(tmp_path)
    assert client.get('/api/media/doc/1/0').status_code==404


def test_documents_and_source_pages_respect_scope(tmp_path):
    client=make_client(tmp_path,False)
    assert client.get('/api/documents').json()==[]
    assert client.get('/api/page/doc/1').status_code==404
    assert client.get('/api/source/doc').status_code==404


def test_local_service_rejects_foreign_host_and_browser_origin(tmp_path):
    client=make_client(tmp_path)
    assert client.get('/api/status',headers={'host':'evil.example'}).status_code==403
    assert client.get('/api/status',headers={'Origin':'https://evil.example'}).status_code==403
