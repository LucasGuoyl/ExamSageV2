import pytest

from examsage.exam_outlook import evaluate_outlook, exam_outlook
from examsage.plugin_tools import CourseBinding, PluginTools, Principal
from test_exam_outlook import corpus


def test_absent_or_untagged_target_cannot_assign_false_positives(tmp_path):
    db,scope=corpus(tmp_path)
    missing=evaluate_outlook(db,scope,'math',2026,2,'paper_year')
    assert missing['unobserved_predictions']==[] and missing['metrics'] is None
    assert missing['comparison_status']=='no_target' and missing['unresolved_predictions']
    rows=db.list_records(scope)
    next(r for r in rows if r.id=='q-target').topic=None
    snap=db.publish('w',db.manifest(scope),rows,db.related(scope,'q-b'),{})
    partial=evaluate_outlook(db,scope.model_copy(update={'snapshot':snap}),'math',2024,2,'paper_year')
    assert partial['comparison_status']=='partial_target' and partial['unobserved_predictions']==[]
    assert partial['metrics'] is None and partial['unresolved_predictions']==['Flow','Pressure']


def test_replay_and_forecast_are_separate_and_references_reopen(tmp_path):
    db,scope=corpus(tmp_path)
    tools=PluginTools([CourseBinding('math',db.path,scope)],Principal('student',frozenset(['math'])))
    args=dict(course_id='math',target_year=2024,top_k=2,history_mode='paper_year')
    forecast=tools.call('get_exam_outlook',args)
    replay=tools.call('evaluate_exam_outlook',args)
    assert replay['outlook']==forecast and 'target_questions' not in forecast
    assert replay['comparison_status']=='compared' and replay['unobserved_predictions']==['Flow','Pressure']
    q,=replay['target_questions']
    assert q['question_number']=='1' and q['observed_topics']==['HELD_OUT'] and q['matched_topics']==[]
    src=q['source']
    canon=tools.call('get_source_page',{'course_id':'math','document_id':src['document_id'],'page':src['page']})
    assert src['source_id']==canon['sources'][0]['source_id']
    old_only=scope.model_copy(update={'allowed_sources':['a','b','lecture']})
    bounded=PluginTools([CourseBinding('math',db.path,old_only)],Principal('student',frozenset(['math'])))
    hidden=bounded.call('evaluate_exam_outlook',args)
    assert hidden['comparison_status']=='no_target' and 'HELD_OUT' not in str(hidden)


def test_conflicting_copy_of_target_cannot_enter_history_even_under_narrow_grant(tmp_path):
    db,scope=corpus(tmp_path)
    mf=db.manifest(scope)
    a=next(d for d in mf.documents if d.id=='a')
    target=next(d for d in mf.documents if d.id=='target')
    a.sha256=target.sha256
    records=db.list_records(scope)
    next(r for r in records if r.id=='q-a').topic='MISDATED COPY OF TARGET'
    snap=db.publish('w',mf,records,db.related(scope,'q-b'),{})
    for allowed in [scope.allowed_sources,['a','lecture']]:
        s=scope.model_copy(update={'snapshot':snap,'allowed_sources':allowed})
        f=exam_outlook(db,s,'math',2024,3,'paper_year')
        assert 'MISDATED COPY OF TARGET' not in str(f) and 2020 not in f['training_years']


def test_no_historical_prediction_is_an_abstention(tmp_path):
    db,scope=corpus(tmp_path)
    review=evaluate_outlook(db,scope,'math',2020,2,'strict')
    assert review['comparison_status']=='no_forecast' and review['metrics'] is None
    assert review['new_to_prediction']==[] and review['observed_topics']==['Pressure']

def test_restricted_export_keeps_the_conflict_after_other_copy_is_removed(tmp_path):
    from examsage.release import publish_release
    from examsage.storage import Store
    from examsage.domain import Scope
    db,scope=corpus(tmp_path)
    mf=db.manifest(scope)
    target=next(d for d in mf.documents if d.id=='target')
    a=next(d for d in mf.documents if d.id=='a')
    target.sha256=a.sha256
    target.exam_year=None
    target.relative_path='Final exam 2023-24.pdf'
    snap=db.publish('w',mf,db.list_records(scope),db.related(scope,'q-b'),{})
    scope=scope.model_copy(update={'snapshot':snap,'allowed_sources':['a','lecture']})
    release=tmp_path/'release'
    publish_release(db,scope,tmp_path,release)
    saved=Scope.model_validate_json((release/'current.json').read_bytes())
    outlook=exam_outlook(Store(release/'course.sqlite3',read_only=True),saved,'math',2024,2,'paper_year')
    assert outlook['training_years']==[] and not outlook['ranking']

def test_private_heading_case_and_paging_share_one_comparison(tmp_path):
    from examsage.student_workspace import StudentWorkspace, student_tools
    from test_uploaded_paper_topics import upload
    space=StudentWorkspace(tmp_path,Principal('learner',frozenset()))
    receipt=upload(space,[('older.txt','exam',2022,'Question 1 on Heat'),
                          ('held.txt','exam',2024,'\n'.join(f'Question {i} on HEAT' for i in range(1,24)))])
    tools=student_tools(None,space)
    args=dict(course_id='upload-'+receipt['id'],target_year=2024,top_k=3,history_mode='paper_year')
    first=tools.call('evaluate_exam_outlook',args)
    next_page=tools.call('evaluate_exam_outlook',{**args,'offset':first['next_offset']})
    assert first['target_questions_total']==23 and first['next_offset']==20
    assert next_page['next_offset'] is None and next_page['metrics'] is None
    rows=first['target_questions']+next_page['target_questions']
    assert [int(r['question_number']) for r in rows]==list(range(1,24))
    assert all(r['matched_topics']==['HEAT'] for r in rows)
    assert first['matched_topics']==['HEAT'] and first['unresolved_predictions']==[]

def test_unlabelled_parent_remains_inspectable_and_never_counts_as_a_miss(tmp_path):
    db,scope=corpus(tmp_path)
    rows=db.list_records(scope)
    tagged=next(r for r in rows if r.id=='q-target')
    rows.append(tagged.model_copy(update={'id':'another-q','topic':None,'details':{'number':'2','exam_year':2024}}))
    snap=db.publish('w',db.manifest(scope),rows,db.related(scope,'q-b'),{})
    report=evaluate_outlook(db,scope.model_copy(update={'snapshot':snap}),'math',2024,2,'paper_year')
    assert report['target_questions_total']==2
    q=report['target_questions'][1]
    assert q['question_number']=='2' and q['source']['record_id']=='target:p1'
    assert not q['observed_topics'] and q['label_status']=='unlabelled'
    assert report['metrics'] is None and report['unobserved_predictions']==[]


def test_unknown_role_with_contradictory_declared_year_invalidates_an_exam_copy(tmp_path):
    db,scope=corpus(tmp_path)
    mf=db.manifest(scope)
    target=next(d for d in mf.documents if d.id=='target')
    target.kind='unknown'
    target.sha256=next(d for d in mf.documents if d.id=='a').sha256
    snap=db.publish('w',mf,db.list_records(scope),db.related(scope,'q-b'),{})
    narrow=scope.model_copy(update={'snapshot':snap,'allowed_sources':['a']})
    assert not exam_outlook(db,narrow,'math',2024,2,'paper_year')['ranking']


def test_re_export_does_not_retain_hidden_ids_in_nested_provenance(tmp_path):
    from examsage.release import publish_release
    from examsage.domain import Scope
    from examsage.storage import Store
    db,scope=corpus(tmp_path)
    mf=db.manifest(scope)
    next(d for d in mf.documents if d.id=='a').sha256=next(d for d in mf.documents if d.id=='target').sha256
    snap=db.publish('w',mf,db.list_records(scope),db.related(scope,'q-b'),{})
    first,second=tmp_path/'first',tmp_path/'second'
    publish_release(db,scope.model_copy(update={'snapshot':snap}),tmp_path,first)
    saved=Scope.model_validate_json((first/'current.json').read_bytes()).model_copy(update={'allowed_sources':['a','lecture']})
    publish_release(Store(first/'course.sqlite3'),saved,first/'assets',second)
    assert '"target"' not in (second/'provenance.json').read_text(encoding='utf8')
    latest=Scope.model_validate_json((second/'current.json').read_bytes())
    assert 'target' not in str(Store(second/'course.sqlite3').metadata(latest))

@pytest.mark.parametrize('assessment_kind',['exam','exam_solution','assessment_rubric','tutorial_feedback','exam_guidance'])
def test_target_copy_as_lecture_cannot_supply_historical_topic_or_survive_export(tmp_path,assessment_kind):
    from examsage.release import publish_release
    from examsage.domain import Scope
    from examsage.storage import Store
    db,scope=corpus(tmp_path)
    mf=db.manifest(scope)
    target=next(d for d in mf.documents if d.id=='target')
    target.kind=assessment_kind
    next(d for d in mf.documents if d.id=='lecture').sha256=target.sha256
    rows=db.list_records(scope)
    next(r for r in rows if r.id=='c').topic='Held-out copy'
    snap=db.publish('w',mf,rows,db.related(scope,'q-b'),{})
    narrow=scope.model_copy(update={'snapshot':snap,'allowed_sources':['b','lecture']})
    output=tmp_path/'export'
    publish_release(db,narrow,tmp_path,output)
    saved=Scope.model_validate_json((output/'current.json').read_bytes())
    for store,grant in ((db,narrow),(Store(output/'course.sqlite3'),saved)):
        assert 'Held-out copy' not in str(exam_outlook(store,grant,'math',2024,2,'paper_year'))

def test_private_review_preserves_known_numbers_without_topic_headings(tmp_path):
    from examsage.student_workspace import StudentWorkspace, student_tools
    from test_uploaded_paper_topics import upload
    ws=StudentWorkspace(tmp_path,Principal('student',frozenset()))
    receipt=upload(ws,[('before.txt','exam',2023,'Question 1 on Energy'),
                       ('target.txt','exam',2024,'Question 1 on energy\f2. Find the transfer rate.\n3. Other task.')])
    cid='upload-'+receipt['id']
    tools=student_tools(None,ws)
    ask=dict(course_id=cid,target_year=2024,top_k=3,history_mode='paper_year')
    report=tools.call('evaluate_exam_outlook',ask)
    assert report['target_coverage']['parent_questions']==3 and report['target_coverage']['tagged_questions']==1
    rows=report['target_questions']
    assert [(q['question_number'],q['source']['page'],q['label_status']) for q in rows]==[
        ('1',1,'labelled'),('2',2,'unlabelled'),('3',2,'unlabelled')]
    assert 'transfer rate' not in str(report['outlook'])
    for q in rows:
        ref=q['source'];page=tools.call('get_source_page',dict(course_id=cid,document_id=ref['document_id'],page=ref['page']))
        assert page['sources'][0]['source_id']==ref['source_id']
