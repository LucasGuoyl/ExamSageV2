"""Exercise the regular GRT build, with the real source page and course item."""
import json
from pathlib import Path
import shutil

import pytest

from examsage.cli import build
from examsage.domain import Scope
from examsage.storage import Store

ROOT = Path(__file__).resolve().parents[1]
REVIEW = 'grt_source_correction_20261116.json'
PAGE = 'doc_302412114374759d0a4d2edb:p24'
CONCEPT = 'imperial:70151:concept:groundwater_age'


@pytest.fixture(scope='module')
def textbook(tmp_path_factory):
    folder = tmp_path_factory.mktemp('groundwater-age')
    source = folder/'sources'
    (source/'slides').mkdir(parents=True)
    review = json.loads((ROOT/'courses'/REVIEW).read_bytes())
    source_hash = review['adjudication']['evidence'][0]['source_sha256']
    doc = source/'slides/GeolRctvTransport.pdf'
    shutil.copyfile(ROOT/'data/grt/assets/sources'/(source_hash+'.pdf'), doc)
    (folder/'audit.json').write_text(json.dumps({'files':[{'course_folder':'grt',
        'relative_path':'grt/slides/GeolRctvTransport.pdf','document_type':'lecture_or_revision',
        'pages_or_slides':97,'sha256':source_hash}]}),encoding='utf8')
    return folder


def fixture_recipe(folder):
    config = json.loads((ROOT/'courses/grt.json').read_bytes())
    config.update(items=[x for x in config['items'] if x['key']=='groundwater_age'], relations=[], question_map={})
    (folder/'grt.json').write_text(json.dumps(config), encoding='utf8')
    shutil.copyfile(ROOT/'courses'/REVIEW,folder/REVIEW)


def test_regular_build_retains_two_bound_errata_and_original_text(tmp_path,textbook):
    fixture_recipe(tmp_path)
    data=tmp_path/'course'
    result=build(textbook/'sources',textbook/'audit.json',tmp_path/'grt.json',data)
    scope=Scope.model_validate_json((data/'current.json').read_bytes())
    assert result['snapshot']==scope.snapshot
    records=Store(data/'course.sqlite3',read_only=True).list_records(scope)
    notes={r.id:r for r in records if r.details.get('audit',{}).get('adjudication')}
    assert set(notes)=={PAGE,CONCEPT}
    for record in notes.values():
        note=record.details['audit']['adjudication']
        assert note['category']=='source_error' and note['review']=='agent_source_checked'
        assert 'dt/dl=1/v' in note['summary'] and note['evidence'][0]['page']==24
    assert 'dt/dl' in notes[PAGE].text.replace(' ','')
    assert notes[PAGE].review=='machine_checked' and notes[CONCEPT].review=='candidate'
    from io import StringIO
    from examsage.api import create_app
    from examsage.study_file import write_study_text
    from test_student_web import read_course_route
    doc=notes[PAGE].refs[0].document_id
    db=Store(data/'course.sqlite3',read_only=True)
    target=StringIO()
    write_study_text(target,db,scope,'grt',[doc])
    summary=notes[PAGE].details['audit']['adjudication']['summary']
    assert summary in target.getvalue() and target.getvalue().count(summary)==1
    app=create_app(data,course_id='grt')
    pg=read_course_route(app,'/api/page/{doc_id}/{number}',doc,24,None,None)
    assert pg.get('page_erratum')==summary
    adjacent=read_course_route(app,'/api/page/{doc_id}/{number}',doc,25,None,None)
    assert not adjacent.get('page_erratum')


def test_changed_review_cannot_publish_a_snapshot(tmp_path,textbook):
    fixture_recipe(tmp_path)
    recipe=tmp_path/REVIEW
    modified=json.loads(recipe.read_bytes())
    modified['adjudication']['summary']='Different conclusion'
    recipe.write_text(json.dumps(modified),encoding='utf8')
    data=tmp_path/'course'
    with pytest.raises(ValueError,match='review'):
        build(textbook/'sources',textbook/'audit.json',tmp_path/'grt.json',data)
    assert not (data/'current.json').exists()

@pytest.mark.parametrize('failure', ['hidden_page', 'changed_concept'])
def test_rejects_ineligible_review_atomically(failure):
    from examsage.domain import digest
    from examsage.source_corrections import apply_review_to_records
    data = ROOT/'data/grt'
    scope = Scope.model_validate_json((data/'current.json').read_bytes()).model_copy(
        update={'snapshot':'snap_49a6db972ef9debf56899aeea67b2349'})
    store = Store(data/'course.sqlite3',read_only=True)
    records = [r for r in store.list_records(scope) if r.id in (PAGE,CONCEPT)]
    page = next(r for r in records if r.id==PAGE)
    concept = next(r for r in records if r.id==CONCEPT)
    if failure=='hidden_page':
        page.visibility='hidden'
    else:
        concept.text+=' New interpretation.'
    correction=json.loads((ROOT/'courses'/REVIEW).read_bytes())
    with pytest.raises(ValueError):
        apply_review_to_records(store.manifest(scope),records,correction,
            rebuilt_hashes={PAGE:digest(page.model_dump(mode='json'))})
    assert all('audit' not in r.details for r in records)

def test_status_reports_selected_snapshot_if_report_write_was_interrupted(tmp_path,capsys):
    from examsage.cli import main
    from test_core import example
    store,manifest,record=example(tmp_path)
    sid=store.publish('local',manifest,[record],[],{})
    scope=Scope(workspace='local',course=manifest.course_key,snapshot=sid,allowed_sources=['doc'])
    (tmp_path/'current.json').write_text(scope.model_dump_json(),encoding='utf8')
    (tmp_path/'build_report.json').write_text(json.dumps({'snapshot':'wrong','pages':12345}))
    assert main(['status','--data',str(tmp_path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['snapshot']==sid and 'pages' not in result

def test_strict_replay_of_dated_textbook_omits_undated_correction(tmp_path):
    from datetime import date
    from examsage.source_corrections import apply_review_to_records
    base = ROOT/'data/grt'
    scope = Scope.model_validate_json((base/'current.json').read_bytes()).model_copy(
        update={'snapshot':'snap_49a6db972ef9debf56899aeea67b2349'})
    original = Store(base/'course.sqlite3',read_only=True)
    manifest = original.manifest(scope)
    doc = next(d for d in manifest.documents if d.id+':p24'==PAGE)
    doc.available_from = date(2020,1,1)
    records = [r for r in original.list_records(scope) if r.id in {PAGE,CONCEPT}]
    correction = json.loads((ROOT/'courses'/REVIEW).read_bytes())
    apply_review_to_records(manifest,records,correction)
    db = Store(tmp_path/'strict.sqlite3')
    sid = db.publish(scope.workspace,manifest,records,[],{})
    current = scope.model_copy(update={'snapshot':sid})
    strict = current.model_copy(update={'strict_history':True,'cutoff':date(2023,1,1)})
    summary = correction['adjudication']['summary']
    assert summary in db.get(current,PAGE).limitations
    _, pages = db.original_page_slice(strict,0,8,document_id=doc.id)
    for record in [db.get(strict,PAGE),db.get(strict,CONCEPT),*db.list_records(strict),*pages]:
        assert record is not None
        assert 'audit' not in record.details and summary not in record.limitations
    assert db.get(strict,PAGE).text==db.get(current,PAGE).text
