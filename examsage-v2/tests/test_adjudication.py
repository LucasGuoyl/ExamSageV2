from copy import deepcopy
import pytest
from test_course_pilots import built
from test_ses_subquestions import nested


def verdict():
    return {'schema':'source-adjudication-v1','category':'system_error','summary':'Earlier comparison used the wrong value.',
            'system_findings':['Incorrect comparison input'],'source_findings':[],
            'actions':['Use the visible source value'],'remaining':[],
            'evidence':[{'document_id':'q','page':2,'source_sha256':'a'*64,'observation':'Question value.'}],
            'review':'agent_source_checked'}


def adjudicated(m,p,r):
    nested(m,p,r)
    v=verdict();v['evidence'][0]['source_sha256']=m.documents[0].sha256
    for record in r['records']:
        if record['id'] in {'q:a.i','a:a.i'}:
            record['details']['audit']['adjudication']=deepcopy(v)
            record['details']['audit']['previous_assessment']={'warnings':['OLD PRIVATE COMPARISON']}


@pytest.mark.parametrize('fault',['hash','hidden_page','category','review','missing_evidence','empty_summary'])
def test_invalid_adjudication_rejected(tmp_path,fault):
    def change(m,p,r):
        adjudicated(m,p,r)
        v=next(x for x in r['records'] if x['id']=='q:a.i')['details']['audit']['adjudication']
        if fault=='hash':v['evidence'][0]['source_sha256']='0'*64
        elif fault=='hidden_page':v['evidence'][0]['page']=999
        elif fault=='category':v['category']='approved'
        elif fault=='review':v['review']='teacher_approved'
        elif fault=='missing_evidence':v['evidence']=[]
        elif fault=='empty_summary':v['summary']=''
    with pytest.raises(ValueError):built(tmp_path,change)


def test_external_evidence_cannot_leak_into_narrow_scope(tmp_path):
    from examsage.release import publish_release
    from examsage.cli import load
    def change(m,p,r):
        adjudicated(m,p,r)
        extra=next(d for d in m.documents if d.id=='l1')
        r['source_hashes'][extra.id]=extra.sha256
        for record in r['records']:
            if record['id'] in {'q:a.i','a:a.i'}:
                record['details']['audit']['adjudication']['evidence'].append(
                    {'document_id':extra.id,'page':1,'source_sha256':extra.sha256,'observation':'PRIVATE LECTURE'})
                record['text']='PRIVATE LECTURE derived comparison'
    store,scope=built(tmp_path,change)
    scope.allowed_sources=['q','a']
    for rec in [store.get(scope,'q:a.i'),store.get(scope,'a:a.i')]:
        assert 'audit' not in rec.details
        assert 'PRIVATE' not in rec.text
    publish_release(store,scope,tmp_path/'assets',tmp_path/'restricted')
    exported,sc=load(tmp_path/'restricted')
    assert 'audit' not in exported.get(sc,'q:a.i').details


def test_search_defers_history_but_full_record_preserves_it(tmp_path):
    from examsage.search import CourseQueryService
    store,scope=built(tmp_path,adjudicated)
    assert store.get(scope,'q:a.i').details['audit']['previous_assessment']
    result=CourseQueryService(store).search_evidence(scope,'2024 Q1(a)(i) answer')
    assert result.records[0].details['audit']['adjudication']['category']=='system_error'
    assert 'previous_assessment' not in result.records[0].details['audit']


def test_corrected_parent_guide_is_source_only_without_answer_permission(tmp_path):
    def change(m,p,r):
        nested(m,p,r)
        next(x for x in r['records'] if x['id']=='q:a')['text']='ANSWER DERIVED corrected parent guide'
    store,scope=built(tmp_path,change);scope.allowed_sources=['q']
    record=store.get(scope,'q:a')
    assert 'ANSWER DERIVED' not in record.text
    assert 'original' in record.text


def test_prior_review_cannot_disclose_removed_supporting_source(tmp_path):
    def change(m,p,r):
        adjudicated(m,p,r)
        audit=next(x for x in r['records'] if x['id']=='q:a.i')['details']['audit']
        audit['previous_assessment']={'adjudication':{'evidence':[{'document_id':'l1','page':1,'observation':'PRIVATE OLD LECTURE'}]}}
    store,scope=built(tmp_path,change);scope.allowed_sources=['q','a']
    assert 'PRIVATE OLD LECTURE' not in store.get(scope,'q:a.i').model_dump_json()


def test_conditional_calculation_can_cite_explicitly_bound_support(tmp_path):
    def change(m,p,r):
        adjudicated(m,p,r)
        a=next(x for x in r['records'] if x['id']=='q:a.i')['details']['audit']
        a['adjudication']['evidence'].append({'document_id':'l1','page':1,'source_sha256':'c'*64,'observation':'Explicit conditional input'})
        a['numerical_checks'][0]['source_refs'].append({'document_id':'l1','page':1})
    store,scope=built(tmp_path,change)
    assert store.get(scope,'q:a.i').details['audit']['numerical_checks'][0]['computed_value']==30
