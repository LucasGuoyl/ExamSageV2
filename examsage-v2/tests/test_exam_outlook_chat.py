import json
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from examsage.chat_runner import ChatRunner
from examsage.chat_service import CourseTools, build_context, outlook_request, validate_answer
from examsage.domain import Document, Manifest, Record, Scope, SourceRef
from examsage.model_runtime import RuntimeFailure
from examsage.storage import Store
from test_chat_runner import wait_run


REQUEST = '【历年试卷主题】2025 年，按卷面考年回顾。请给出优先复习主题。'
ARGS = {'target_year':2025, 'top_k':4, 'history_mode':'paper_year'}


@pytest.fixture
def course(tmp_path, monkeypatch):
    store = Store(tmp_path/'course.sqlite3')
    doc = Document(id='past', relative_path='past.pdf', kind='exam', exam_year=2024,
                   sha256='1'*64, pages=2)
    ref = SourceRef(document_id=doc.id, page=2)
    q = Record(id='q', kind='question', title='Q1', text='LATER_SOLUTION',
               refs=[ref], details={'mapping_evidence':'LATER_SOLUTION'})
    sid = store.publish('w', Manifest(course_key='internal',course_name='数学',documents=[doc]), [q],[],{})
    scope = Scope(workspace='w',course='internal',snapshot=sid,allowed_sources=['past'])
    def history(db, bound, course_id, target_year, top_k, history_mode):
        assert db is store and bound == scope and course_id == 'math'
        row = {'topic':'归纳法','years':[2024],'year_count':1,'question_count':1,
               'sources':[{'document_id':'past','page':2,'record_id':'past:p2','source_id':'S1','filename':'past.pdf'}]}
        ranked = history_mode == 'paper_year'
        return {'course_id':course_id,'snapshot':sid,'target_year':target_year,'history_mode':history_mode,
                'status':'ranked' if ranked else 'insufficient','ranking':[row] if ranked else [],
                'training_years':[2024] if ranked else [],'coverage':{},
                'limitations':['可得日期未知。']}
    monkeypatch.setitem(sys.modules, 'examsage.exam_outlook', SimpleNamespace(exam_outlook=history))
    return store, scope


def answer(eids, kind='source'):
    return {'paragraphs':[{'text':'归纳法出现在往卷中。','kind':kind,'citations':eids}]}


def test_outlook_has_dedicated_evidence_and_ignores_unadopted_result(course):
    tools = CourseTools(*course,course_id='math',outlook_args=ARGS)
    result = tools.call('get_exam_outlook',ARGS)
    eid = result['exam_outlook']['ranking'][0]['evidence_id']
    assert 'LATER_SOLUTION' not in json.dumps(result)
    source = tools.evidence[eid]
    assert source['kind'] == 'exam_topic' and source['refs'][0]['source_id'] == 'S1'
    assert 'LATER_SOLUTION' not in json.dumps(source)
    used = validate_answer(answer([eid]),tools,question=REQUEST)
    assert used['exam_outlook']['training_years'] == [2024]
    assert used['limitations'] == ['可得日期未知。']
    ordinary_tools = CourseTools(*course,course_id='math')
    ordinary = ordinary_tools.call('get_question',{'question_id':'q'})['records'][0]['evidence_ids']
    unused = validate_answer(answer(ordinary),ordinary_tools)
    assert 'exam_outlook' not in unused
    with pytest.raises(RuntimeFailure):
        validate_answer(answer(ordinary),ordinary_tools,question=REQUEST)
    context = json.loads(build_context([{'role':'assistant','content':'见清单。','answer':used}], 'math'))
    locator = context['last_exam_outlook_context_not_evidence']
    assert locator['topics'] == ['归纳法'] and locator['target_year'] == 2025
    assert 'S1' not in json.dumps(locator) and 'LATER_SOLUTION' not in json.dumps(locator)


@pytest.mark.parametrize('question', [
    'Which topics should I prioritize for the 2025 exam in 数学?',
    'Likely exam topics for 数学 in 2025?',
    'Will 数学 include induction in the 2025 exam?',
])
def test_english_outlook_keeps_original_topic_and_source_reference(course, question):
    tools = CourseTools(*course, course_id='math', outlook_args=ARGS)
    report = tools.call('get_exam_outlook', ARGS)['exam_outlook']
    eid = report['ranking'][0]['evidence_id']
    result = validate_answer(answer([eid]), tools, question=question)
    assert '2025' in result['text'] and 'revision' in result['text'].lower()
    assert report['ranking'][0]['topic'] in result['text']
    assert result['paragraphs'][0]['citations'] == [eid]
    assert result['limitations'] == ['Source availability dates are unknown.']


def test_insufficient_cannot_become_an_outlook_for_another_year_or_mode(course):
    args = {**ARGS,'history_mode':'strict'}
    tools = CourseTools(*course,course_id='math',outlook_args=args)
    result = tools.call('get_exam_outlook',args)
    assert result['exam_outlook']['status'] == 'insufficient'
    strict = '【历年试卷主题】2025 年，限考前可得资料。请给出优先复习主题。'
    insufficient = answer([], 'insufficient')
    assert validate_answer(insufficient,tools,question=strict)['exam_outlook']['ranking'] == []
    for q in (REQUEST, strict.replace('2025','2024')):
        with pytest.raises(RuntimeFailure):
            validate_answer(insufficient,tools,question=q)
    honest = validate_answer(answer([], 'assumption'),tools,question=strict)
    assert honest['paragraphs'][0]['kind'] == 'insufficient'


def test_failed_replacement_retains_previous_accepted_outlook(course):
    tools = CourseTools(*course,course_id='math',outlook_args=ARGS)
    first = tools.call('get_exam_outlook',ARGS)['exam_outlook']
    evidence = dict(tools.evidence)
    tools._bytes = 99999
    with pytest.raises(RuntimeFailure) as exc:
        tools.call('get_exam_outlook',ARGS)
    assert exc.value.code == 'evidence_limit'
    assert tools.outlook == first and tools.evidence == evidence
    assert [step['tool'] for step in tools.trace] == ['get_exam_outlook']


@pytest.mark.parametrize('question',[REQUEST,'请预测2025年SES的考试范围。我听说是LATER_SOLUTION。'])
def test_explicit_year_request_cannot_read_solution_or_old_messages(course, tmp_path, question):
    class Probe:
        def generate(self,context,specs,call,cancel,phase,*,before_send):
            before_send()
            assert 'LATER_SOLUTION' not in context
            assert [spec['name'] for spec in specs] == ['get_exam_outlook']
            with pytest.raises(RuntimeFailure):
                call('get_question',{'question_id':'q'})
            with pytest.raises(RuntimeFailure):
                call('get_exam_outlook',{**ARGS,'target_year':2027})
            result = call('get_exam_outlook',ARGS)['exam_outlook']
            return answer([result['ranking'][0]['evidence_id']])
    store, scope = course
    runner = ChatRunner(tmp_path/'sessions', runtime=Probe())
    try:
        session = runner.store.create_session(scope)
        old = runner.store.begin_run(scope,session['id'],'LATER_SOLUTION','prior')
        runner.store.finish_run(scope,old['id'],answer([], 'assumption') | {'text':'from 2026'})
        start = runner.submit(store,scope,session['id'],question,'outlook',course_id='math')
        final = wait_run(runner,scope,start['id'])
        assert final['status'] == 'completed', final.get('error')
        assert runner.store.messages(scope,session['id'])[-1]['answer']['exam_outlook']['target_year'] == 2025
    finally:
        runner.close()


@pytest.mark.parametrize(('question','year','mode'),[
    ('请预测2025年SES的考试范围',2025,'paper_year'),
    ('Predict the likely exam topics for 2025, using only sources available before the exam.',2025,'strict'),
    ('哪些考点最可能在明年的试卷出现？',date.today().year+1,'paper_year'),
    ("What topics are likely to appear on next year's exam?",date.today().year+1,'paper_year'),
])
def test_natural_outlook_binds_the_actual_target_before_the_model(question,year,mode):
    assert outlook_request(question) == {'target_year':year,'history_mode':mode,'top_k':4}


def test_followup_keeps_only_settings_and_allows_switch_back_to_a_real_problem():
    previous = {'target_year':2025,'history_mode':'strict','top_k':3}
    assert outlook_request('那2024年呢？', previous) == {**previous,'target_year':2024}
    for question in ['不要预测了，解释2025原题Q1。','请解释2025年试卷Q1为什么可能有两个解。',
                     'Explain the possible solutions to the 2025 exam question.']:
        assert outlook_request(question,previous) is None
    with pytest.raises(RuntimeFailure) as bad:
        outlook_request('预测考试范围')
    assert bad.value.code == 'invalid_outlook_request'


def test_unrestricted_turn_cannot_make_a_forecast_after_reading_later_question(course):
    tools = CourseTools(*course,course_id='math')
    ordinary = tools.call('get_question',{'question_id':'q'})
    assert 'LATER_SOLUTION' in json.dumps(ordinary)
    with pytest.raises(RuntimeFailure) as bad:
        tools.call('get_exam_outlook',ARGS)
    assert bad.value.code == 'outlook_requires_isolation'


@pytest.mark.parametrize('mode',['strict','paper_year'])
def test_model_cannot_write_future_certainties_into_server_outlook(course, mode):
    args = {**ARGS,'history_mode':mode}
    tools = CourseTools(*course, course_id='math', outlook_args=args)
    tools.call('get_exam_outlook',args)
    malicious = {'paragraphs':[{'kind':'insufficient','text':'明年必考100%。','citations':[]}],
                 'limitations':['明年必考100%。']}
    answer = validate_answer(malicious,tools)
    assert '100%' not in json.dumps(answer,ensure_ascii=False)
    assert answer['exam_outlook']['status'] == ('insufficient' if mode=='strict' else 'ranked')
    if mode=='strict':
        assert answer['evidence'] == [] and answer['paragraphs'][0]['kind'] == 'insufficient'
    else:
        assert answer['evidence'][0]['kind'] == 'exam_topic'
        assert answer['paragraphs'][0]['citations']
@pytest.mark.parametrize('query', ['2025年 SES 考试范围会有哪些知识点？','What will the 2025 SES exam cover?'])
def test_plain_exam_scope_requests_take_the_isolated_path(query):
    from examsage.chat_service import outlook_request
    assert outlook_request(query) == {'target_year':2025,'history_mode':'paper_year','top_k':4}


def test_addressing_examsage_does_not_turn_an_exam_question_into_a_forecast():
    from examsage.chat_service import outlook_request
    assert outlook_request('押题宝，帮我解释2025年真题第一题') is None
