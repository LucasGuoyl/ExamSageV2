import json

import pytest

from examsage.chat_api import SendMessage
from examsage.chat_runner import ChatRunner
from examsage.chat_service import CourseTools, build_context, validate_answer
from examsage.library import create_library_app
from examsage.plugin_tools import load_library
from test_chat_api import endpoint
from test_chat_runner import wait_run
from test_knowledge_map import nodes
from test_source_reviews import imported


class MapTutor:
    def __init__(self, submit_map):
        self.submit_map = submit_map

    def generate(self, context, specs, call, cancel, phase, *, before_send):
        before_send()
        if self.submit_map:
            call('browse_course_materials', {'offset': 0})
            result = call('prepare_knowledge_map', {'nodes': nodes()})
            return {'paragraphs': [{'kind': 'source', 'text': '有限求和', 'citations': [result['evidence_ids'][0]]}]}
        call('get_source_page', {'document_id': 'notes', 'page': 1})
        return {'paragraphs': [{'kind': 'assumption', 'text': '知识结构已整理。'}]}


def test_explicit_map_run_needs_a_validated_map_and_remains_available_after_reopening(tmp_path):
    _, plugin, binding = imported(tmp_path)
    _, store = plugin._course('demo-math')
    runtime = MapTutor(False)
    runner = ChatRunner(tmp_path / 'chat', runtime=runtime)
    scope = binding.scope
    question = '【课程知识结构】请根据课件生成知识结构。'
    try:
        session = runner.store.create_session(scope)
        def run(request_id):
            started = runner.submit(store, scope, session['id'], question, request_id)
            return wait_run(runner, scope, started['id'])

        failed = run('incomplete')
        assert failed['status'] == 'failed'
        assert failed['error']['code'] == 'knowledge_map_missing'
        assert all(m['role'] == 'user' for m in runner.store.messages(scope, session['id']))
        runtime.submit_map = True
        done = run('with-map')
        assert done['status'] == 'completed'
        answer = runner.store.messages(scope, session['id'])[-1]['answer']
        graph = answer['knowledge_map']
        assert graph['coverage'] == {'visible_pages': 3, 'cited_pages': 2}
        for node in graph['nodes']:
            ref = node['support'][0]
            evidence = next(e for e in answer['evidence'] if e['id'] == ref['evidence_id'])
            assert evidence['text'] == ref['quote']
            assert evidence['refs'][0]['page'] == ref['page']
    finally:
        runner.close()


def test_calculation_citing_a_map_quote_preserves_the_original_pages_review(tmp_path):
    _, plugin, binding = imported(tmp_path)
    _, store = plugin._course('demo-math')
    tools = CourseTools(store, binding.scope)
    graph = tools.call('prepare_knowledge_map', {'nodes': nodes()})['knowledge_map']
    quote = graph['nodes'][1]['support'][0]
    result = tools.call('calculate', {'expression': 'n*(n+1)/2', 'inputs': {'n': 10},
                                      'units': 'count', 'source_ids': [quote['evidence_id']]})
    answer = validate_answer({'paragraphs': [{'kind':'derivation', 'text':'55',
        'citations':[result['evidence_id']]}]}, tools)
    assert answer['evidence'][0]['source_reviews'][0]['id'] == 'review-1'


@pytest.mark.parametrize('primary', [True, False])
def test_mounted_chat_and_native_plugin_issue_same_source_id_for_registry_alias(tmp_path, primary):
    _, _, binding = imported(tmp_path)
    entries = [{'slug': 'math-alias', 'data': 'course', 'name': 'Math'}]
    default = tmp_path / 'course'
    if not primary:
        _, _, binding = imported(tmp_path / 'other')
        entries[0]['data'] = 'other/course'
        entries.append({'slug': 'default', 'data': 'course', 'name': 'Default'})
    (tmp_path/'library.json').write_text(json.dumps({'courses': entries}), encoding='utf8')
    runner = ChatRunner(tmp_path/'chats', runtime=MapTutor(True))
    try:
        library = create_library_app(default, import_root=tmp_path/'uploads', chat_runner=runner)
        mounted_path = '' if primary else '/courses/math-alias'
        app = next(r.app for r in library.routes if r.path == mounted_path)
        scope = binding.scope
        session = runner.store.create_session(scope)
        request = SendMessage(text='【课程知识结构】', client_request_id='mapped')
        run = endpoint(app, '/api/chat/sessions/{session_id}/messages', 'POST')(session['id'], request, scope)
        result = wait_run(runner, scope, run['id'])
        assert result['status'] == 'completed'
        graph = result['answer']['knowledge_map']
        assert graph['course_id'] == 'math-alias'
        native = load_library(tmp_path, ['math-alias'])
        actual = native.call('get_source_page', {'course_id': 'math-alias', 'document_id': 'notes', 'page': 1})
        assert graph['nodes'][0]['support'][0]['source_id'] == actual['sources'][0]['source_id']
        status = endpoint(app, '/api/chat/status')(scope)
        assert 'prepare_knowledge_map' in status['course_tools']
    finally:
        runner.close()


def test_history_locates_nodes_in_rendered_order_without_reusing_quotes_or_evidence_ids():
    def node(key, parent, page):
        return {'id':key, 'parent':parent, 'title':key, 'summary':'old answer',
                'support':[{'document_id':'notes', 'page': page, 'quote':'secret old quote', 'evidence_id':'E999'}]}
    graph = {'schema_version':'knowledge-map-v1', 'nodes':[node('b','a',2), node('a','',1), node('c','',3)]}
    graph['nodes'][0]['support'].append({'document_id':'other', 'page':8,'quote':'secret old quote'})
    messages = [{'role':'assistant', 'content':'已生成。', 'answer':{'knowledge_map':graph}}]
    messages += [{'role':'assistant', 'content':'其他追问'}] * 4
    messages += [{'role':'user', 'content':'第一个主题的子节点在哪一页？'}]
    context = build_context(messages, 'demo-math')
    rows = json.loads(context)['last_knowledge_map_context_not_evidence']['nodes']
    assert [(n['title'], n['parent'], n['sources'][0]['page']) for n in rows] == [('a','',1),('b','a',2),('c','',3)]
    assert rows[1]['sources'][1] == {'document_id':'other','page':8}
    assert 'secret old quote' not in context and 'E999' not in context and 'old answer' not in context


def test_large_previous_map_cannot_displace_complete_user_conditions():
    graph = {'schema_version':'knowledge-map-v1','nodes':[
        {'id': str(i), 'parent':'', 'title':'主题'*80, 'support':[{'document_id':'notes','page':i+1}]}
        for i in range(30)]}
    messages = [{'role':'assistant','content':'历史','answer':{'knowledge_map':graph}}]
    conditions = ['a'*3900 + str(i) for i in range(11)]
    messages += [{'role':'user','content':text} for text in conditions]
    context = json.loads(build_context(messages, 'demo'))
    assert [m['text'] for m in context['user_turns_in_order']] == conditions
    assert 'omitted' in context['last_knowledge_map_context_not_evidence']
