import json
from pathlib import Path

import pytest

from examsage.course_pack import CoursePack, import_pack
from examsage.plugin_tools import CourseBinding, PluginTools, Principal

EXAMPLES = Path(__file__).resolve().parents[1] / 'examples' / 'course-packs'


@pytest.mark.parametrize('discipline', ['physics', 'mathematics', 'literature', 'history'])
def test_student_source_followup_and_answer_boundaries(tmp_path, discipline):
    source = EXAMPLES / discipline
    pack = CoursePack.model_validate_json((source/'pack.json').read_text(encoding='utf-8'))
    result = import_pack(pack, source, tmp_path/discipline)
    cid = pack.profile.course_id
    tools = PluginTools([CourseBinding(cid, tmp_path/discipline/'course.sqlite3', result.scope)],
                        Principal('demo-student', frozenset([cid])))
    profile = tools.call('get_course_profile', {'course_id': cid})
    assert profile['material_status'] == 'demonstration'
    assert profile['outcomes']
    query = {'physics': 'Hooke spring', 'mathematics': 'induction sum', 'literature': '窗', 'history': 'equal'}[discipline]
    found = tools.call('search_evidence', {'course_id': cid, 'query': query})
    assert 'focus' in {r['id'] for r in found['records']}
    detail = tools.call('get_record', {'course_id': cid, 'record_id': 'focus'})
    assert detail['sources'] and detail['records'][0]['review'] == 'candidate'
    question = tools.call('get_question', {'course_id': cid, 'question_id': 'q-a'})
    assert {r['id'] for r in question['records']} == {'q', 'q-a'}
    answer = tools.call('get_answer', {'course_id': cid, 'question_id': 'q-a'})
    if discipline in {'physics', 'mathematics'}:
        assert 'a-a' in {r['id'] for r in answer['records']}
        assert len(detail['records'][0]['details']['academic']['steps']) == 2
        assert {r['page'] for r in detail['records'][0]['refs']} == {1, 2}
        citation = detail['sources'][0]
        args = {'course_id': cid, 'sources': [{'source_id': citation['source_id'], 'record_id': 'focus'}],
                'expression': 'F/k' if discipline == 'physics' else 'n*(n+1)/2',
                'inputs': {'F': 10, 'k': 200} if discipline == 'physics' else {'n': 10},
                'units': 'm' if discipline == 'physics' else 'dimensionless'}
        assert tools.call('calculate', args)['value'] == (.05 if discipline == 'physics' else 55)
        args['inputs'] = {'F': 20, 'k': 200} if discipline == 'physics' else {'n': 20}
        assert tools.call('calculate', args)['value'] == (.1 if discipline == 'physics' else 210)
    else:
        assert answer['sufficiency'] == 'insufficient'
        assert not any(r['kind'] == 'answer' for r in answer['records'])
        assert detail['records'][0]['details']['academic']['evidence_record_ids'] == ['quote']
        if discipline == 'literature':
            genre = tools.call('search_evidence', {'course_id':cid, 'query':'短诗'})
            assert any(r['id']=='quote' and any(ref['document_id']=='lesson' and ref['page']==1
                       for ref in r['refs']) for r in genre['records'])
            other = tools.call('get_record', {'course_id': cid, 'record_id': 'alternative'})
            assert other['records'][0]['kind'] == 'interpretation'
            assert any(r['kind'] == 'contradicts' for r in detail['relations'])
        else:
            assert detail['records'][0]['kind'] == 'claim'
            assert '不等于' in detail['records'][0]['limitations'][0]
    ref = detail['sources'][0]['refs'][0]
    page = tools.call('get_source_page', {'course_id': cid, 'document_id': ref['document_id'], 'page': ref['page']})
    assert page['records'] and page['sources'][0]['refs'][0]['sha256'] == ref['sha256']


def math_tools(tmp_path):
    source = EXAMPLES/'mathematics'
    pack = CoursePack.model_validate_json((source/'pack.json').read_text(encoding='utf-8'))
    result = import_pack(pack, source, tmp_path/'course')
    return PluginTools([CourseBinding('demo-mathematics', tmp_path/'course/course.sqlite3', result.scope)],
                       Principal('student', frozenset(['demo-mathematics'])))


def test_direct_answer_search_includes_question_and_parent(tmp_path):
    tools = math_tools(tmp_path)
    response = tools.call('search_evidence', {'course_id':'demo-mathematics', 'query':'S_10'})
    assert {r['id'] for r in response['records']} >= {'a-a','q-a','q'}
    assert any(e['kind']=='has_answer' for e in response['relations'])
    binding, store = tools._course('demo-mathematics')
    from examsage.search import CourseQueryService
    bounded = CourseQueryService(store).search_evidence(binding.scope, 'S_10', limit=1)
    assert bounded.records == []
    assert bounded.sufficiency == 'insufficient'


def test_proof_is_available_through_advertised_concept_tool(tmp_path):
    response = math_tools(tmp_path).call('get_concept', {'course_id':'demo-mathematics','concept_id':'focus'})
    assert response['records'][0]['kind']=='proof'


def test_physics_step_formula_is_on_cited_demo_page():
    source = EXAMPLES/'physics'
    pack = CoursePack.model_validate_json((source/'pack.json').read_text(encoding='utf-8'))
    focus = next(r for r in pack.records if r.id=='focus')
    step = focus.details['academic']['steps'][0]
    pages = (source/'lesson.txt').read_text(encoding='utf-8').split('\f')
    assert any('Fs=-kx' in pages[ref['page']-1] for ref in step['refs'])


@pytest.mark.parametrize('failure', ['parent_excluded', 'ambiguous_pair'])
def test_answer_hit_cannot_bypass_context_grants_or_pairing(tmp_path, failure):
    from examsage.domain import Document, Record, Relation, Scope, SourceRef
    from examsage.search import CourseQueryService
    from test_core import example
    store, manifest, raw = example(tmp_path)
    manifest.documents.append(Document(id='private',relative_path='private.pdf',sha256='b'*64,kind='exam',pages=1))
    private = SourceRef(document_id='private',page=1)
    records = [Record(id='parent',kind='question',title='Shared conditions',text='Secret condition',refs=[private]),
               Record(id='q',kind='question',title='Question',text='Compute.',refs=raw.refs,parent_id='parent'),
               Record(id='a',kind='answer',title='Answer',text='uniqueanswerterm',refs=raw.refs)]
    relations = [Relation(id='pair',source='q',target='a',kind='has_answer',refs=raw.refs)]
    if failure=='ambiguous_pair':
        records.append(Record(id='other',kind='question',title='Other',text='Other question',refs=raw.refs))
        relations.append(Relation(id='other-pair',source='other',target='a',kind='has_answer',refs=raw.refs))
    sid = store.publish('w',manifest,records,relations,{})
    scope = Scope(workspace='w',course=manifest.course_key,snapshot=sid,
                  allowed_sources=['doc'] if failure=='parent_excluded' else ['doc','private'])
    response = CourseQueryService(store).search_evidence(scope,'uniqueanswerterm')
    assert response.records == []
    assert response.sufficiency == 'insufficient'


def test_exact_subquestion_answer_search_never_adds_other_parts(tmp_path):
    from examsage.domain import Record, Relation, Scope
    from examsage.search import CourseQueryService
    from test_core import example
    store, manifest, raw = example(tmp_path)
    records, relations = [], []
    for part in ['a','b']:
        records += [Record(id='q'+part,kind='question',title='Q1('+part+')',text='Compute '+part,
                           refs=raw.refs,details={'exam_year':2024,'number':'1','part':part}),
                    Record(id='a'+part,kind='answer',title='Answer '+part,text='Answer for '+part,refs=raw.refs)]
        relations.append(Relation(id='pair-'+part,source='q'+part,target='a'+part,kind='has_answer',refs=raw.refs))
    sid=store.publish('w',manifest,records,relations,{})
    scope=Scope(workspace='w',course=manifest.course_key,snapshot=sid,allowed_sources=['doc'])
    response=CourseQueryService(store).search_evidence(scope,'2024 Q1(a) answer')
    assert {r.id for r in response.records} == {'qa','aa'}
