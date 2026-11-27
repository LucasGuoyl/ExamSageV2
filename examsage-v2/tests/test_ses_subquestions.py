from copy import deepcopy
import pytest
from test_course_pilots import built
from examsage.search import CourseQueryService


def nested(m,p,recipe):
    for part in ['a','a.i','a.ii','b']:
        for index,kind in [(0,'question'),(1,'answer')]:
            r=deepcopy(recipe['records'][index]);stem=r['id'];r['id']=stem+':'+part
            r['parent_id']=stem+':a' if '.' in part else stem
            r['title']+=' ('+part+')';r['text']='Requested child calculation '+part
            r['details'].update(part=part,scope='subquestion',content_type='source_checked_subquestion',audit={
                'status':'checked','conditions':['P = 10 W'],
                'formula_checks':[{'latex':'E=Pt','note':'energy in joules'}],
                'numerical_checks':[{'label':'E','expression':'P*t','inputs':{'P':10,'t':3},'unit':'J',
                    'source_value':30,'source_refs':[{'document_id':'q','page':2},{'document_id':'a','page':2}]}],
                'numerical_status':'recomputed','warnings':[]})
            recipe['records'].append(r)
        recipe['relations'].append({'kind':'has_answer','source':'q:'+part,'target':'a:'+part,
            'refs':[{'document_id':'q','page':2},{'document_id':'a','page':2}], 'origin':'explicit','review':'agent_source_checked'})


@pytest.mark.parametrize('query',['2024 Q1(a)(i) 答案','2024 Q1(a.i) answer','2024 Q1a(i) solution',
    '2024 Q1 a.i answer','2024 第1题(a)(i)答案','2024 Q1 Part A(i) answer',
    'Q1(a)(i) 2024 答案','2024 Q1(a)(i) 1400万家庭答案','2024 Q1(a)(i) 500 W条件答案',
    '2024 Q1(a)(i) 806和816为何不同？','2024 Q1(a)(i) 怎么算？','2024 Q1(a)(i) 需要多少？'])
def test_exact_nested_lookup_returns_all_ancestors(tmp_path,query):
    store,scope=built(tmp_path,nested)
    result=CourseQueryService(store).search_evidence(scope,query)
    assert [r.id for r in result.records]==['q:a.i','q:a','q','a:a.i','a:a','a']
    assert result.records[0].details['audit']['numerical_checks'][0]['comparison']=='agrees'


@pytest.mark.parametrize('query',['2024 Q1(a)(iii) answer','2024 Q1(a)(i)(x) answer',
    '2024 Q1(a)(i) and Q1(b) answer','2024 Q1(a)(i) Part b answer','2023 Q1(a)(i) answer',
    '2024 Q1(a) and (b) answer','2024 Q1(a) b answer','2024 Q1(a)和(b)答案'])
def test_absent_or_ambiguous_part_cannot_fall_back(tmp_path,query):
    store,scope=built(tmp_path,nested)
    assert not CourseQueryService(store).search_evidence(scope,query).records


def test_all_parent_context_obeys_budget_and_source_scope(tmp_path):
    store,scope=built(tmp_path,nested);service=CourseQueryService(store)
    assert not service.search_evidence(scope,'2024 Q1(a)(i) answer',limit=5).records
    assert not service.search_evidence(scope,'2024 Q1(a)(i) answer',max_chars=200).records
    scope.allowed_sources=['q']
    result=service.get_answer(scope,'q:a.i')
    assert [r.id for r in result.records]==['q:a.i','q:a','q']
    assert result.sufficiency=='insufficient' and not result.records[0].details['has_answer']


@pytest.mark.parametrize('fault',['missing_parent','skipped_parent','wrong_kind','wrong_year','wrong_part','numeric_scope','fake_computation'])
def test_subquestion_contract_and_calculation_checks(tmp_path,fault):
    def change(m,p,r):
        nested(m,p,r);child=next(x for x in r['records'] if x['id']=='q:a.i')
        if fault=='missing_parent':child['parent_id']='missing'
        if fault=='skipped_parent':child['parent_id']='q'
        if fault=='wrong_kind':child['parent_id']='a:a'
        if fault=='wrong_year':child['details']['exam_year']=2023
        if fault=='wrong_part':child['details']['part']='a..i'
        if fault=='numeric_scope':child['details']['audit']['numerical_checks'][0]['source_refs']=[{'document_id':'l2','page':1}]
        if fault=='fake_computation':child['details']['audit']['numerical_checks'][0]['expression']='__import__("os")'
    with pytest.raises(ValueError):built(tmp_path,change)


def test_source_answer_disagreement_cannot_claim_checked(tmp_path):
    def change(m,p,r):
        nested(m,p,r)
        next(x for x in r['records'] if x['id']=='q:b')['details']['audit']['numerical_checks'][0]['source_value']=40
    store,scope=built(tmp_path,change)
    audit=store.get(scope,'q:b').details['audit']
    assert audit['status']=='source_conflict' and audit['numerical_checks'][0]['comparison']=='mismatch'
    assert audit['warnings']


def test_browser_api_offers_roots_children_and_scope_correct_counts(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from examsage.api import create_app
    store,scope=built(tmp_path,nested)
    monkeypatch.setattr('examsage.api.load',lambda data:(store,scope))
    client=TestClient(create_app(tmp_path),base_url='http://localhost')
    assert [r['id'] for r in client.get('/api/records?kind=question&roots=true').json()]==['q']
    assert {r['id'] for r in client.get('/api/records?kind=question&parent=q:a').json()}=={'q:a.i','q:a.ii'}
    status=client.get('/api/status').json()
    assert status['whole_questions']==1 and status['subquestions']==4 and status['leaf_subquestions']==3
    assert status['numerical_checks']==4 and status['numerical_comparisons']=={'agrees':4}
    assert client.get('/api/record/q:a').json()['children_count']==2


def test_answer_audit_never_leaks_through_question_only_scope_or_export(tmp_path):
    from examsage.release import publish_release
    from examsage.cli import load
    store,scope=built(tmp_path,nested);scope.allowed_sources=['q']
    for record in [store.get(scope,'q:a.i'),*store.list_records(scope,'question')]:
        assert 'audit' not in record.details
    publish_release(store,scope,tmp_path/'assets',tmp_path/'question-only')
    exported,restricted=load(tmp_path/'question-only')
    assert 'audit' not in exported.get(restricted,'q:a.i').details


def test_large_parent_audit_keeps_conditions_without_duplicate_calculation_budget(tmp_path):
    def change(m,p,r):
        nested(m,p,r)
        for record in r['records']:
            if record['id'] in {'q:a','a:a'}:
                audit=record['details']['audit'];audit['conditions']=['Inherited table P=10W, t=3s']
                audit['numerical_checks']=[{**deepcopy(audit['numerical_checks'][0]),'label':f'Parent sibling {i}'} for i in range(80)]
    store,scope=built(tmp_path,change)
    result=CourseQueryService(store).search_evidence(scope,'2024 Q1(a)(i) answer')
    assert [r.id for r in result.records]==['q:a.i','q:a','q','a:a.i','a:a','a']
    target,parent=result.records[:2]
    assert target.details['audit']['numerical_checks'][0]['computed_value']==30
    assert parent.details['audit']['conditions']==['Inherited table P=10W, t=3s']
    assert parent.details['audit_checks_deferred_count']==80
    assert result.records[3].details['audit_on_record_id']=='q:a.i'
    assert len(store.get(scope,'q:a').details['audit']['numerical_checks'])==80


def test_restricted_ancestor_does_not_expose_joint_guide_or_mapping_evidence(tmp_path):
    from examsage.release import publish_release
    from examsage.cli import load
    def change(m,p,r):
        nested(m,p,r)
        r['records'][0]['text']+=' 来源警示：EXCLUDED_ANSWER 43.44%'
        r['records'][0]['details']['mapping_evidence']=['EXCLUDED_ANSWER 38.5 degrees']
        r['records'][0]['details']['warnings']=['EXCLUDED_ANSWER 10 Hz']
        for page in p:
            if page.document_id=='q':page.text='SOURCE_QUESTION table P=10 W and t=3 s'
    store,scope=built(tmp_path,change)
    assert 'EXCLUDED_ANSWER' in store.get(scope,'q').model_dump_json()
    scope.allowed_sources=['q'];bundle=CourseQueryService(store).get_question(scope,'q:a.i')
    assert 'EXCLUDED_ANSWER' not in bundle.model_dump_json()
    assert 'SOURCE_QUESTION table P=10 W' in bundle.records[-1].text
    publish_release(store,scope,tmp_path/'assets',tmp_path/'restricted-parents')
    assert 'EXCLUDED_ANSWER' not in (tmp_path/'restricted-parents/questions.jsonl').read_text(encoding='utf-8')
    exported,restricted=load(tmp_path/'restricted-parents')
    reopened=CourseQueryService(exported).get_question(restricted,'q:a.i')
    assert 'EXCLUDED_ANSWER' not in reopened.model_dump_json()
    assert 'SOURCE_QUESTION table P=10 W' in reopened.records[-1].text


def test_question_api_retains_complete_context_for_child_navigation(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from examsage.api import create_app
    store,scope=built(tmp_path,nested);scope.allowed_sources=['q']
    monkeypatch.setattr('examsage.api.load',lambda data:(store,scope))
    client=TestClient(create_app(tmp_path),base_url='http://localhost')
    response=client.get('/api/question/q:a.i')
    assert response.status_code==200
    result=response.json()
    assert [r['id'] for r in result['records']]==['q:a.i','q:a','q']
    assert not any(r['details'].get('audit') for r in result['records'])
