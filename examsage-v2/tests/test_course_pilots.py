import json
from copy import deepcopy
import pytest
from examsage.domain import Document, Manifest, Page, Scope
from examsage.storage import Store
from examsage.search import CourseQueryService

def fixture():
    docs=[Document(id=k,relative_path=k+'.pdf',sha256=s*64,kind=t,pages=3) for k,s,t in [('q','a','exam'),('a','b','exam_solution'),('l1','c','lecture'),('l2','d','lecture')]]
    manifest=Manifest(course_key='c',course_name='C',documents=docs)
    pages=[Page(document_id=d.id,number=n,text='original') for d in docs for n in range(1,4)]
    records=[{'id':k,'kind':kind,'title':'2024 Q1 '+kind,'text':'source reading guide','review':'agent_source_checked','refs':[{'document_id':k,'page':2}],
        'details':{'exam_year':2024,'number':1,'year_basis':'cover_verified','mapping_status':'source_matched','source_sha256':sha*64,'paired_document_id':other,'warnings':['source parameter mismatch']}}
        for k,kind,sha,other in [('q','question','a','a'),('a','answer','b','q')]]
    records.append({'id':'derive','kind':'concept','title':'Bending','text':'derive','review':'agent_source_checked','refs':[{'document_id':'l1','page':1},{'document_id':'l2','page':2}],
        'details':{'derivation':{'steps':[{'title':'step','text':'balance','refs':[{'document_id':'l2','page':2}]}],'conditions':['elastic']}}})
    recipe={'schema':'course-pilot-v1','course_key':'c','source_hashes':{d.id:d.sha256 for d in docs},'document_years':{'q':2024},'year_labels':{'q':{'year':2024,'basis':'cover_verified'}},
        'records':records,'relations':[{'kind':'has_answer','source':'q','target':'a','refs':records[0]['refs']+records[1]['refs'],'origin':'explicit','review':'agent_source_checked','details':{'mapping_evidence':['same parameters']}}]}
    return manifest,pages,recipe

def built(tmp_path,mutation=None):
    from examsage.course_pilots import load_pilot
    manifest,pages,recipe=fixture()
    if mutation:mutation(manifest,pages,recipe)
    path=tmp_path/'pilot.json';path.write_text(json.dumps(recipe))
    records,edges,metadata=load_pilot(path,manifest,pages)
    store=Store(tmp_path/'course.sqlite3');sid=store.publish('w',manifest,records,edges,{'structure_mode':'source_pages',**metadata})
    return store,Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['q','a','l1','l2'])

def test_exact_question_answer_and_cross_document_derivation(tmp_path):
    store,scope=built(tmp_path);service=CourseQueryService(store)
    bundle=service.search_evidence(scope,'2024 Q1 官方答案')
    assert [r.id for r in bundle.records]==['q','a']
    assert bundle.relations[0].kind=='has_answer'
    assert store.get(scope,'derive').details['derivation']['steps'][0]['refs'][0]['document_id']=='l2'
    assert store.manifest(scope).documents[0].available_from is None

@pytest.mark.parametrize('query',['2023 Q1 官方答案','2024 Q9','2024 Q1(a)','2023 2024 Q1 官方答案',
    '2024 Q1b 官方答案','2024 Q1 b 官方答案','2024 第1题第b小问答案','2024 Q1.2 官方答案','2024 Q1 and Q2 answers','2024 Q1 Part A(b) 答案'])
def test_missing_year_number_or_part_never_falls_back(tmp_path,query):
    store,scope=built(tmp_path);result=CourseQueryService(store).search_evidence(scope,query)
    assert not result.records and result.sufficiency=='insufficient'

def test_answer_requires_both_sources_and_complete_context_budget(tmp_path):
    store,scope=built(tmp_path);service=CourseQueryService(store)
    scope.allowed_sources=['q','l1','l2']
    result=service.get_answer(scope,'q');assert not any(r.kind=='answer' for r in result.records)
    assert result.sufficiency=='insufficient'
    scope.allowed_sources.append('a')
    assert not service.search_evidence(scope,'2024 Q1 answer',limit=1).records
    assert not service.search_evidence(scope,'2024 Q1 answer',max_chars=100).records

def test_year_and_topic_answer_lookup_stays_within_requested_year(tmp_path):
    store,scope=built(tmp_path);service=CourseQueryService(store)
    assert [r.id for r in service.search_evidence(scope,'2024 source 官方答案').records]==['q','a']
    assert not service.search_evidence(scope,'2099 source 官方答案').records

@pytest.mark.parametrize('fault',['hash','year','question_number','cross_pair','step_scope','hidden','date_basis','both_years','both_bases'])
def test_invalid_pilot_rejected(tmp_path,fault):
    def change(m,p,r):
        if fault=='hash':r['source_hashes']['q']='f'*64
        if fault=='year':r['records'][1]['details']['exam_year']=2023
        if fault=='question_number':r['records'][1]['details']['number']=2
        if fault=='cross_pair':r['records'][1]['details']['paired_document_id']='l1'
        if fault=='step_scope':r['records'][2]['details']['derivation']['steps'][0]['refs'][0]['page']=3
        if fault=='hidden':p[1].hidden=True
        if fault=='date_basis':r['year_labels']['q']['basis']='filename_label'
        if fault=='both_years':
            for item in r['records'][:2]:item['details']['exam_year']=2099
        if fault=='both_bases':
            for item in r['records'][:2]:item['details']['year_basis']='filename_label'
    with pytest.raises(ValueError):built(tmp_path,change)

def test_academic_year_uses_explicit_source_label(tmp_path):
    def change(m,p,r):
        for record in r['records'][:2]:
            record['details'].update(year_label='2023-24',year_basis='filename_label')
        r['document_years']={};r['year_labels']={'q':{'year':2024,'basis':'filename_label','label':'2023-24'}}
    store,scope=built(tmp_path,change)
    result=CourseQueryService(store).search_evidence(scope,'2023-24 Q1 解答')
    assert [r.id for r in result.records]==['q','a']
    assert not CourseQueryService(store).search_evidence(scope,'2022-23 Q1 解答').records

def test_scoped_status_and_export_do_not_advertise_unavailable_answers(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from examsage.api import create_app
    from examsage.cli import load
    from examsage.release import publish_release
    store,scope=built(tmp_path);scope.allowed_sources=['q']
    monkeypatch.setattr('examsage.api.load',lambda data:(store,scope))
    client=TestClient(create_app(tmp_path),base_url='http://localhost')
    status=client.get('/api/status').json()
    assert status['pilot_records']==1 and status['pilot_answer_pairs']==0
    assert not client.get('/api/records?kind=question').json()[0]['details']['has_answer']
    assert not CourseQueryService(store).search_evidence(scope,'source').records[0].details['has_answer']
    publish_release(store,scope,tmp_path/'assets',tmp_path/'export')
    reopened,allowed=load(tmp_path/'export')
    assert reopened.metadata(allowed)['pilot_answer_pairs']==0
    assert not reopened.get(allowed,'q').details['has_answer']
