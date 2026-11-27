import json
from datetime import date
from hashlib import sha256

import pytest

from examsage.domain import Document, Manifest, Record, Relation, Scope, SourceRef
from examsage.plugin_tools import CourseBinding, PluginTools, Principal
from examsage.storage import Store


def corpus(root):
    docs, records, edges = [], [], []
    def document(key, kind, year, available, title=None):
        doc = Document(id=key, relative_path=title or key+'.pdf', kind=kind, pages=1,
                       sha256=sha256(key.encode()).hexdigest(), exam_year=year, available_from=available)
        docs.append(doc)
        ref = SourceRef(document_id=key, page=1)
        records.append(Record(id=key+':p1', kind='block', title='Original', text='Original exam page.', refs=[ref]))
        return ref

    lecture = document('lecture','lecture',None,date(2019,1,1))
    records.append(Record(id='c',kind='concept',title='Flow',topic='Flow',text='Concept',refs=[lecture]))
    for key, year, available, topic, label in [
        ('a',2020,date(2021,1,1),'Pressure',None), ('b',2022,None,None,None),
        ('c23',None,date(2024,5,1),'Pressure','2022-23'),
        ('target',2024,date(2023,1,1),'HELD_OUT',None), ('later',2025,None,'LATER',None)]:
        ref = document(key,'exam',year,available,'paper_2022-23.pdf' if label else None)
        exam_year = year or 2023
        q = Record(id='q-'+key, kind='question', title='Q1', text='POSTHOC SOLUTION TEXT',topic=topic,
                   refs=[ref],details={'number':'1','exam_year':exam_year,'year_label':label})
        # Modeled pilot records may carry answer-derived annotations. Only labels and source locators are inputs.
        records.extend([q,Record(id=q.id+'-i',kind='question',title='(i)',text='nested',topic='NESTED',
                                parent_id=q.id,refs=[ref],details={'number':'1','exam_year':exam_year})])
        if key=='b':
            edges.append(Relation(id='edge',source=q.id,target='c',kind='assesses',refs=[ref,lecture]))
    answer = document('solution','exam_solution',2021,date(2022,1,1))
    records.append(Record(id='answer-as-question',kind='question',text='PAID_ANSWER',title='q',topic='PAID_ANSWER',
                          refs=[answer],details={'number':'1','exam_year':2021}))
    mf=Manifest(course_key='internal-math',course_name='Test',documents=docs)
    store=Store(root/'course.sqlite3')
    snap=store.publish('w',mf,records,edges,{})
    scope=Scope(workspace='w',course=mf.course_key,snapshot=snap,allowed_sources=[d.id for d in docs])
    return store,scope


def test_earlier_papers_only_count_parent_once_and_cite_original_page(tmp_path):
    from examsage.exam_outlook import exam_outlook
    store,s=corpus(tmp_path)
    report=exam_outlook(store,s,'math',2024,4,'paper_year')
    assert report['training_years']==[2020,2022,2023]
    assert [(r['topic'],r['question_count']) for r in report['ranking']]==[('Pressure',2),('Flow',1)]
    assert report['coverage']['parent_questions']==report['coverage']['tagged_questions']==3
    text=json.dumps(report)
    assert all(marker not in text for marker in ['HELD_OUT','LATER','POSTHOC','NESTED','PAID_ANSWER'])
    tools=PluginTools([CourseBinding('math',store.path,s)],Principal('owner',frozenset(['math'])))
    for row in report['ranking']:
        for ref in row['sources']:
            found=tools.call('get_source_page',{'course_id':'math','document_id':ref['document_id'],'page':ref['page']})
            assert ref['source_id']==found['sources'][0]['source_id']
    assert tools.call('get_exam_outlook',dict(course_id='math',target_year=2024,top_k=4,history_mode='paper_year'))==report


def test_strict_dates_revocations_and_no_classifier_source(tmp_path):
    from examsage.exam_outlook import exam_outlook
    store,s=corpus(tmp_path)
    report=exam_outlook(store,s,'math',2024,4,'strict')
    assert report['training_years']==[2020]
    assert [r['topic'] for r in report['ranking']]==['Pressure']
    revoked=s.model_copy(update={'allowed_sources':['b','target']})
    limited=exam_outlook(store,revoked,'math',2024,4,'paper_year')
    assert limited['status']=='insufficient' and limited['ranking']==[]
    assert 'Flow' not in json.dumps(limited)
    strict=s.model_copy(update={'strict_history':True,'cutoff':date(2020,1,1)})
    assert exam_outlook(store,strict,'math',2024,4,'paper_year')['ranking']==[]


def test_holdout_uses_training_ranking_before_target_and_preserves_new_labels(tmp_path):
    from examsage.exam_outlook import evaluate_outlook
    store,s=corpus(tmp_path)
    result=evaluate_outlook(store,s,'math',2024,2,'paper_year')
    assert result['outlook']['training_years']==[2020,2022,2023]
    assert result['observed_topics']==['HELD_OUT'] and result['new_to_prediction']==['HELD_OUT']
    assert result['metrics']=={'matched':0,'predicted':2,'observed':1,'requested_k':2,
                               'precision_at_k':0,'precision_on_returned':0,'recall':0}
    assert evaluate_outlook(store,s,'math',2026,2,'paper_year')['metrics'] is None


def test_precision_denominator_when_fewer_labels_than_requested(tmp_path):
    from examsage.exam_outlook import evaluate_outlook
    store,s=corpus(tmp_path)
    scored=evaluate_outlook(store,s,'math',2023,10,'paper_year')
    assert scored['metrics']['precision_at_k']==0.1
    assert scored['metrics']['precision_on_returned']==0.5


def test_misdirected_page_and_later_dated_classification_are_excluded(tmp_path):
    from examsage.exam_outlook import exam_outlook
    store,s=corpus(tmp_path)
    manifest=store.manifest(s)
    next(d for d in manifest.documents if d.id=='lecture').document_date=date(2025,1,1)
    records=store.list_records(s)
    # A record with the expected identifier still has to point to the actual page.
    page=next(r for r in records if r.id=='a:p1')
    page.refs=[SourceRef(document_id='c23',page=1)]
    snap=store.publish('w',manifest,records,store.related(s,'q-b'),{})
    report=exam_outlook(store,s.model_copy(update={'snapshot':snap}),'math',2024,4,'paper_year')
    assert [(r['topic'],r['years']) for r in report['ranking']]==[('Pressure',[2023])]


@pytest.mark.parametrize('mismatch', ['filename','document_date'])
def test_conflicting_year_or_newer_paper_version_cannot_enter_training(tmp_path,mismatch):
    from examsage.exam_outlook import exam_outlook
    store,s=corpus(tmp_path)
    manifest=store.manifest(s)
    edition=next(d for d in manifest.documents if d.id=='a')
    if mismatch == 'filename':
        edition.relative_path='Exam Paper_2024-25.pdf'
    else:
        edition.document_date=date(2025,1,1)
    snap=store.publish('w',manifest,store.list_records(s),store.related(s,'q-b'),{})
    report=exam_outlook(store,s.model_copy(update={'snapshot':snap}),'math',2024,4,'strict')
    assert report['status']=='insufficient' and report['training_years']==[]


@pytest.mark.parametrize('year,top,mode',[(True,3,'strict'),(2024,0,'paper_year'),(2024,2,'typo')])
def test_outlook_arguments_rejected(tmp_path,year,top,mode):
    from examsage.exam_outlook import exam_outlook
    store,s=corpus(tmp_path)
    with pytest.raises(ValueError): exam_outlook(store,s,'math',year,top,mode)
