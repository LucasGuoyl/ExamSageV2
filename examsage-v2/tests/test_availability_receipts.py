"""A dated observation applies to these bytes and cannot retroactively admit an exam."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO

from examsage.exam_outlook import exam_outlook
from examsage.plugin_tools import Principal
from examsage.student_workspace import StudentWorkspace, student_tools
from examsage.web_intake import import_selection
from test_exam_outlook import corpus


def upload(workspace, year, *, observed):
    raw = b'Exam date: 2019-01-03\nCoursework published on Blackboard: 2019-01-01\fQuestion 1 on Heat'
    solution = b'Question 1 on SolutionOnly'
    receipt = import_selection(workspace.imports, 'Energy', 'Physics',
        [('paper.txt',BytesIO(raw)),('key.txt',BytesIO(solution))],
        materials=[dict(filename='paper.txt',kind='exam',exam_year=year),
                   dict(filename='key.txt',kind='exam_solution',exam_year=year)],
        **({'record_receipt':True} if observed else {}))
    return receipt, sha256(raw).hexdigest()


def test_new_observation_admits_future_forecast_but_not_older_holdout(tmp_path):
    space = StudentWorkspace(tmp_path,Principal('owner',frozenset()))
    before = datetime.now(timezone.utc).date()
    receipt, digest = upload(space, before.year-2, observed=True)
    day = date.fromisoformat(receipt['received_on_utc'])
    assert before <= day <= datetime.now(timezone.utc).date()
    tools = student_tools(None,space)
    cid='upload-'+receipt['id']
    binding,store=tools._course(cid)
    docs=store.manifest(binding.scope).documents
    assert [d.available_from for d in docs] == [day,day] and docs[0].sha256==digest
    future=tools.call('get_exam_outlook',dict(course_id=cid,target_year=day.year+1,top_k=3,history_mode='strict'))
    assert future['training_years']==[before.year-2] and [r['topic'] for r in future['ranking']]==['Heat']
    ref=future['ranking'][0]['sources'][0]
    assert ref['availability']=={'known_by':day.isoformat(),'basis':'project_receipt','file_sha256':digest}
    page=tools.call('get_source_page',dict(course_id=cid,document_id=ref['document_id'],page=ref['page']))
    assert ref['source_id']==page['sources'][0]['source_id'] and page['sources'][0]['refs'][0]['sha256']==digest
    past=tools.call('get_exam_outlook',dict(course_id=cid,target_year=day.year,top_k=3,history_mode='strict'))
    assert past['ranking']==[] and 'SolutionOnly' not in str(future)
    assert store.permitted_documents(binding.scope.model_copy(update={'strict_history':True,'cutoff':day-timedelta(days=1)}))==set()


def test_legacy_upload_has_no_receipt_and_is_still_readable(tmp_path):
    space=StudentWorkspace(tmp_path,Principal('owner',frozenset()))
    receipt,_=upload(space,2022,observed=False)
    assert not receipt.get('received_on_utc')
    api=student_tools(None,space); cid='upload-'+receipt['id']
    args={'course_id':cid,'target_year':2025,'top_k':3}
    assert api.call('get_exam_outlook',{**args,'history_mode':'paper_year'})['ranking']
    assert not api.call('get_exam_outlook',{**args,'history_mode':'strict'})['ranking']


def test_registered_archive_date_is_distinct_from_possession_receipt(tmp_path):
    store, scope=corpus(tmp_path)
    report=exam_outlook(store,scope,'math',2024,3,'strict')
    ref=report['ranking'][0]['sources'][0]
    doc=next(d for d in store.manifest(scope).documents if d.id==ref['document_id'])
    assert ref['availability']=={'basis':'manifest_date','known_by':doc.available_from.isoformat(),'file_sha256':doc.sha256}


def test_strict_future_outlook_cannot_consume_a_scheduled_release(tmp_path):
    store,scope=corpus(tmp_path)
    today=datetime.now(timezone.utc).date()
    manifest=store.manifest(scope)
    for doc in manifest.documents:
        doc.available_from=today+timedelta(days=1)
    snap=store.publish('w',manifest,store.list_records(scope),[],{})
    report=exam_outlook(store,scope.model_copy(update={'snapshot':snap}),'math',today.year+2,3,'strict')
    assert report['availability_cutoff']==today.isoformat() and not report['ranking']

def test_no_rank_separates_missing_eligible_papers_from_unlabelled_observed_papers(tmp_path):
    space=StudentWorkspace(tmp_path,Principal('s',frozenset()))
    year=datetime.now(timezone.utc).year
    result=import_selection(space.imports,'Physics','Physics',[('exam.txt',BytesIO(b'1. Derive the response.'))],
        materials=[{'filename':'exam.txt','kind':'exam','exam_year':year-2}],record_receipt=True)
    api=student_tools(None,space)
    args={'course_id':'upload-'+result['id'],'top_k':3,'history_mode':'strict'}
    before=api.call('get_exam_outlook',{**args,'target_year':year})
    after=api.call('get_exam_outlook',{**args,'target_year':year+1})
    assert before['unranked_reason']=='no_eligible_papers'
    assert after['unranked_reason']=='no_supported_topics' and after['coverage']['exam_papers']==1


def test_existing_strict_grant_is_respected_in_paper_year_mode(tmp_path):
    store,scope=corpus(tmp_path)
    today=datetime.now(timezone.utc).date()
    tomorrow=today+timedelta(days=1)
    manifest=store.manifest(scope)
    for doc in manifest.documents:
        doc.available_from=tomorrow
    snap=store.publish('w',manifest,store.list_records(scope),[],{})
    ordinary=scope.model_copy(update={'snapshot':snap})
    historical=ordinary.model_copy(update={'strict_history':True,'cutoff':tomorrow})
    assert exam_outlook(store,ordinary,'math',today.year+2,3,'paper_year')['ranking']
    result=exam_outlook(store,historical,'math',today.year+2,3,'paper_year')
    assert result['availability_cutoff']==today.isoformat() and result['ranking']==[]
    result=exam_outlook(store,historical,'math',2022,3,'paper_year')
    assert result['availability_cutoff']=='2021-12-31'


def test_subset_export_binds_receipt_to_the_bytes_actually_copied(tmp_path, monkeypatch):
    import json
    import shutil
    from pathlib import Path
    import pytest
    from examsage.release import publish_release
    from examsage.storage import Store
    from examsage.domain import Scope
    space=StudentWorkspace(tmp_path/'users',Principal('owner',frozenset()))
    receipt,paper_hash=upload(space,2020,observed=True)
    cid='upload-'+receipt['id']
    binding,store=student_tools(None,space)._course(cid)
    doc=next(d for d in store.manifest(binding.scope).documents if d.kind=='exam')
    subset=binding.scope.model_copy(update={'allowed_sources':[doc.id]})
    assets=binding.database.parent/'assets'
    valid=tmp_path/'valid'
    publish_release(store,subset,assets,valid)
    reopened=Store(valid/'course.sqlite3',read_only=True)
    scope=Scope.model_validate_json((valid/'current.json').read_bytes())
    verified=exam_outlook(reopened,scope,cid,datetime.now(timezone.utc).year+1,3,'strict')
    assert verified['ranking'][0]['sources'][0]['availability']['file_sha256']==paper_hash
    assert verified['ranking'][0]['sources'][0]['availability']['basis']=='project_receipt'
    assert 'key.txt' not in json.dumps(verified)
    copy=shutil.copyfile
    def copy_updated_file(source,dest):
        if Path(source).name==Path(doc.asset).name:
            Path(source).write_bytes(b'The source was revised during export.')
        return copy(source,dest)
    monkeypatch.setattr(shutil,'copyfile',copy_updated_file)
    output=tmp_path/'changed'
    with pytest.raises(ValueError,match='integrity'):
        publish_release(store,subset,assets,output)
    assert not output.exists()
