import json
import pytest
from pathlib import Path
from hashlib import sha256
from pypdf import PdfWriter
from fastapi.testclient import TestClient
from examsage.cli import load


def setup_course(tmp_path, name='physics', role='practice_not_past_exam'):
    root=tmp_path/'sources'/name
    root.mkdir(parents=True)
    file=root/'lecture.pdf'
    writer=PdfWriter();writer.add_blank_page(width=200,height=200);writer.write(file)
    audit=tmp_path/'audit.json'
    audit.write_text(json.dumps({'files':[{'course_folder':name,'relative_path':name+'/lecture.pdf',
       'pages_or_slides':1,'sha256':sha256(file.read_bytes()).hexdigest(),'document_type':role}]}))
    return root,audit,{'key':'local:'+name,'name':name.title(),'aliases':[],'query_aliases':{}}


def test_generic_course_build_does_not_assume_grt_exam_structure(tmp_path):
    from examsage.library import build_source_course
    root,audit,config=setup_course(tmp_path)
    data=tmp_path/'data'/'physics'
    report=build_source_course(root,audit,'physics',data,config)
    store,scope=load(data)
    assert scope.course=='local:physics'
    assert report['pages']==1 and report['structure_mode']=='source_pages'
    assert store.manifest(scope).documents[0].kind=='practice'
    assert store.list_records(scope,'question')==[]
    assert store.list_records(scope)[0].details['visual_status']=='not_reviewed'


def test_course_routes_isolate_documents_and_allow_same_origin_browser(tmp_path):
    from examsage.library import build_source_course, create_library_app
    root,audit,config=setup_course(tmp_path,'physics')
    data=tmp_path/'data';build_source_course(root,audit,'physics',data/'physics',config)
    root2,audit2,config2=setup_course(tmp_path,'chemistry')
    build_source_course(root2,audit2,'chemistry',data/'chemistry',config2)
    (data/'library.json').write_text(json.dumps({'default':'physics','courses':[
        {'slug':'physics','data':'physics','name':'Physics'}, {'slug':'chemistry','data':'chemistry','name':'Chemistry'}]}))
    client=TestClient(create_library_app(data/'physics'),base_url='http://localhost')
    assert len(client.get('/api/courses').json())==2
    assert client.get('/courses/chemistry/api/status',headers={'Origin':'http://localhost'}).status_code==200
    doc=client.get('/api/documents').json()[0]['id']
    assert client.get('/courses/chemistry/api/page/'+doc+'/1').status_code==404
    assert client.get('/courses/chemistry/api/status').json()['course']=='Chemistry'


def test_known_solution_file_is_not_denied_as_absent(tmp_path):
    from examsage.library import build_source_course
    from examsage.search import CourseQueryService
    root,audit,config=setup_course(tmp_path,'systems','model_answers_and_marking_feedback')
    data=tmp_path/'data';build_source_course(root,audit,'systems',data,config)
    store,scope=load(data)
    result=CourseQueryService(store).search_evidence(scope,'官方答案')
    assert result.records
    assert result.records[0].details['source_kind']=='exam_solution'
    assert not any('No official' in note for note in result.limitations)


def test_source_course_export_preserves_mode_aliases_and_solution_access(tmp_path):
    from examsage.library import build_source_course
    from examsage.release import publish_release
    from examsage.api import create_app
    from examsage.search import CourseQueryService
    root,audit,config=setup_course(tmp_path,'systems','model_answers_and_marking_feedback')
    config['query_aliases']={'潮流':'power flow'}
    data=tmp_path/'data';build_source_course(root,audit,'systems',data,config)
    store,scope=load(data)
    release=tmp_path/'release';publish_release(store,scope,data/'assets',release)
    reopened,export_scope=load(release)
    client=TestClient(create_app(release),base_url='http://localhost')
    assert client.get('/api/status').json()['structure_mode']=='source_pages'
    assert reopened.metadata(export_scope)['query_aliases']['潮流']=='power flow'
    assert CourseQueryService(reopened).search_evidence(export_scope,'官方答案').records


@pytest.mark.parametrize('failures',[{'physics'},{'physics','chemistry'}])
def test_failed_library_build_preserves_catalog_and_returns_failure(tmp_path,monkeypatch,failures):
    from examsage.cli import main
    data=tmp_path/'data';data.mkdir()
    previous={'default':'physics','courses':[{'slug':s,'data':s,'name':s} for s in ['physics','chemistry']]}
    (data/'library.json').write_text(json.dumps(previous))
    config=tmp_path/'library-config.json'
    config.write_text(json.dumps({'default':'physics','courses':{s:{'name':s} for s in ['physics','chemistry']}}))
    def build(source,audit,slug,target,settings,pilot=None):
        if slug in failures:raise ValueError('source integrity failure')
        return {'documents':1}
    monkeypatch.setattr('examsage.library.build_source_course',build)
    assert main(['build-library','--source',str(tmp_path),'--audit',str(tmp_path/'audit.json'),
                 '--config',str(config),'--data',str(data)])==1
    assert json.loads((data/'library.json').read_text())==previous
    report=json.loads((data/'library-report.json').read_text())
    assert {s for s,r in report.items() if 'error' in r}==failures


def test_answer_file_lookup_obeys_complete_object_context_budget(tmp_path):
    from examsage.library import build_source_course
    from examsage.search import CourseQueryService
    root,audit,config=setup_course(tmp_path,'systems','model_answers_and_marking_feedback')
    data=tmp_path/'data';build_source_course(root,audit,'systems',data,config)
    store,scope=load(data)
    result=CourseQueryService(store).search_evidence(scope,'官方答案',max_chars=100)
    assert sum(len(r.model_dump_json()) for r in result.records)<=100
    assert result.sufficiency=='insufficient'
    assert any('budget' in note for note in result.limitations)
