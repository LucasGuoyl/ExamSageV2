import json
from pathlib import Path
import pytest
from test_core import example


def test_release_is_self_contained_reimportable_and_refuses_overwrite(tmp_path):
    from examsage.release import publish_release
    from examsage.storage import Store
    from examsage.domain import Scope
    store,m,r=example(tmp_path)
    # Use an actual content hash for the immutable source copy.
    from hashlib import sha256
    original=b'course source'
    m.documents[0].sha256=sha256(original).hexdigest()
    m.documents[0].asset='sources/a.pdf'
    assets=tmp_path/'assets';(assets/'sources').mkdir(parents=True)
    (assets/'sources/a.pdf').write_bytes(original)
    metadata={'parser':'native-v1','recipe_hash':'abc','model':'no-generation-model-used'}
    sid=store.publish('w',m,[r],[],metadata)
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    out=tmp_path/'release'
    report=publish_release(store,scope,assets,out)
    assert report['human_acceptance']=='pending'
    new_scope=Scope.model_validate_json((out/'current.json').read_text())
    assert Store(out/'course.sqlite3').get(new_scope,'b').text==r.text
    assert (out/'assets/sources/a.pdf').read_bytes()==original
    assert report['files']['course.sqlite3']
    assert json.loads((out/'provenance.json').read_text())['source_metadata']==store.metadata(scope)
    with pytest.raises(FileExistsError):
        publish_release(store,scope,assets,out)


def test_release_never_exports_other_workspaces(tmp_path):
    from examsage.release import publish_release
    from examsage.domain import Scope
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='wrong',course='c',snapshot=sid,allowed_sources=['doc'])
    with pytest.raises(ValueError):
        publish_release(store,scope,tmp_path/'assets',tmp_path/'out')


def test_reopened_release_retains_snapshot_topics_and_course_specific_limits(tmp_path):
    from fastapi.testclient import TestClient
    from examsage.release import publish_release
    from examsage.domain import Scope
    from examsage.api import create_app
    store,m,r=example(tmp_path)
    topics=[{'id':'groundwater','title':'Groundwater'}]
    sid=store.publish('w',m,[r],[],{'topics':topics})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    out=tmp_path/'export';report=publish_release(store,scope,tmp_path/'assets',out)
    client=TestClient(create_app(out),base_url='http://localhost')
    assert client.get('/api/status').json()['topics']==topics
    assert not any('GRT' in text for text in report['limitations'])


def test_cli_search_returns_structured_json(tmp_path,capsys):
    from examsage.cli import main
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    (tmp_path/'current.json').write_text(json.dumps({'workspace':'w','course':'c','snapshot':sid,'allowed_sources':['doc']}))
    assert main(['search','--data',str(tmp_path),'--query','Darcy'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['records'][0]['id']=='b'


def test_partial_source_export_omits_orphan_children_and_edges(tmp_path):
    from examsage.release import publish_release
    from examsage.domain import Document,Record,Relation,SourceRef,Scope
    from examsage.storage import Store
    store,m,r=example(tmp_path)
    m.documents.append(Document(id='private',relative_path='private.pdf',sha256='b'*64,pages=1,kind='exam'))
    parent=Record(id='q',kind='question',title='Q1',text='Shared table',refs=r.refs+[SourceRef(document_id='private',page=1)])
    child=Record(id='qi',kind='question',title='Part i',text='Use table',refs=r.refs,parent_id='q')
    nested=Record(id='qia',kind='question',title='Part i(a)',text='Explain',refs=r.refs,parent_id='qi')
    edge=Relation(id='e',source='qi',target=r.id,kind='assesses',refs=r.refs)
    sid=store.publish('w',m,[r,parent,child,nested],[edge],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    out=tmp_path/'export'
    report=publish_release(store,scope,tmp_path/'assets',out)
    released=Scope.model_validate_json((out/'current.json').read_text())
    assert [x.id for x in Store(out/'course.sqlite3').list_records(released)]==[r.id]
    assert report['relations']==0
    assert report['omitted_orphan_records']==2


@pytest.mark.parametrize('persistent',[False,True])
def test_release_retries_transient_windows_rename_without_hiding_persistent_errors(tmp_path,monkeypatch,persistent):
    from examsage.release import publish_release
    from examsage.domain import Scope
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    original=Path.rename
    attempts=[]
    def guarded(path,target):
        if '.staging-' in path.name:
            attempts.append(path)
            if persistent or len(attempts)==1:
                error=PermissionError('temporarily locked')
                error.winerror=5
                raise error
        return original(path,target)
    monkeypatch.setattr(Path,'rename',guarded)
    if persistent:
        monkeypatch.setattr('time.sleep',lambda _:None)
    out=tmp_path/'export'
    if persistent:
        with pytest.raises(PermissionError):
            publish_release(store,scope,tmp_path/'assets',out)
        assert len(attempts)==5 and not out.exists()
    else:
        assert publish_release(store,scope,tmp_path/'assets',out)['records']==1
        # The real Windows filesystem can add another transient sharing violation.
        assert 2<=len(attempts)<=5
