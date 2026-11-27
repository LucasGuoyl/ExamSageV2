import json
from datetime import date
from pathlib import Path
from runpy import run_path

from examsage.cli import main
from examsage.domain import Scope
from examsage.ingest import atomic_json
from examsage.release import publish_release
from examsage.storage import Store
from test_core import example


def course(root):
    data=root/'data'/'physics'
    _,manifest,r=example(root)
    manifest.documents[0].available_from=date(2019,12,31)
    manifest.documents.append(manifest.documents[0].model_copy(update={'id':'other','relative_path':'second.pdf'}))
    store=Store(data/'course.sqlite3')
    sid=store.publish('w',manifest,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc','other'])
    atomic_json(data/'current.json',scope.model_dump(mode='json'))
    atomic_json(data.parent/'library.json',{'default':'physics','courses':[{'slug':'physics','data':'physics'}]})
    atomic_json(data/'evaluation/report-new.json',{'snapshot':sid,'results':['other']})
    atomic_json(data/'evaluation/report-old.json',{'snapshot':'previous','results':['old-check']})
    return data,store,scope


def test_course_and_library_publish_only_attach_evaluations_from_the_current_full_snapshot(tmp_path,capsys):
    data,_,grant=course(tmp_path)
    publish_library=run_path(str(Path(__file__).resolve().parents[1]/'tools/publish_library.py'))['publish_library']
    for name,scope in [('all',grant),('one',grant.model_copy(update={'allowed_sources':['doc']})),
                       ('past',grant.model_copy(update={'strict_history':True,'cutoff':date(2020,1,1)}))]:
        atomic_json(data/'current.json',scope.model_dump(mode='json'))
        out=tmp_path/name
        main(['publish','--data',str(data),'--out',str(out)])
        lib=tmp_path/('library-'+name)
        publish_library(data.parent,lib)
        for release in [out,lib/'physics']:
            path=release/'quality_reports.json'
            if name=='all':
                assert json.loads(path.read_text(encoding='utf8'))=={'report-new':{'snapshot':grant.snapshot,'results':['other']}}
            else:
                assert not path.exists()


def test_release_cannot_reintroduce_unscoped_reports_when_reexported(tmp_path):
    data,store,scope=course(tmp_path)
    restricted=scope.model_copy(update={'allowed_sources':['doc']})
    path=tmp_path/'narrow'
    publish_release(store,restricted,data/'assets',path,extras={'summary':{'mentions':'another document'}})
    assert not (path/'quality_reports.json').exists()
    scope=Scope.model_validate_json((path/'current.json').read_bytes())
    again=tmp_path/'again'
    publish_release(Store(path/'course.sqlite3',read_only=True),scope,path/'assets',again,
                    extras={'summary':{'mentions':'another document'}})
    assert not (again/'quality_reports.json').exists()

def test_library_publish_recovers_from_brief_windows_directory_lock(tmp_path,monkeypatch):
    data,_,scope=course(tmp_path)
    output=tmp_path/'course-library'
    original=Path.rename
    attempts=[]
    def rename(folder,target):
        if target==output:
            attempts.append(folder)
            if len(attempts)==1:
                error=PermissionError('temporary sharing violation')
                error.winerror=32
                raise error
        return original(folder,target)
    monkeypatch.setattr(Path,'rename',rename)
    publish=run_path(str(Path(__file__).resolve().parents[1]/'tools/publish_library.py'))['publish_library']
    publish(data.parent,output)
    assert (output/'physics/course.sqlite3').is_file()
    assert json.loads((output/'physics/quality_reports.json').read_bytes())['report-new']['snapshot']==scope.snapshot
    assert len(attempts)==2 and attempts[0]==attempts[1]
