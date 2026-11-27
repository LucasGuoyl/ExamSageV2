from copy import deepcopy

import pytest

from examsage.domain import Scope, Record, Relation
from test_core import example


def api(tmp_path, allowed=('physics', 'history')):
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    bindings = []
    for name in ('physics', 'history'):
        store, manifest, record = example(tmp_path / name)
        manifest.course_key = name
        record.id = 'doc:p1'
        record.text = 'Darcy flux q = K i; this is ' + name
        sid = store.publish('w', manifest, [record], [], {})
        scope = Scope(workspace='w', course=name, snapshot=sid, allowed_sources=['doc'])
        bindings.append(CourseBinding(name, store.path, scope))
    return PluginTools(bindings, Principal('alice', frozenset(allowed)))


def test_catalog_and_queries_enforce_server_side_course_grant(tmp_path):
    tools = api(tmp_path, ('physics',))
    assert [c['course_id'] for c in tools.call('list_courses', {})['courses']] == ['physics']
    with pytest.raises(ValueError):
        tools.call('search_evidence', {'course_id': 'history', 'query': 'Darcy'})


def test_repeated_calls_are_complete_and_citations_do_not_collide(tmp_path):
    tools = api(tmp_path)
    args = {'course_id': 'physics', 'query': 'Darcy'}
    first = tools.call('search_evidence', args)
    for _ in range(12):
        result = tools.call('search_evidence', args)
        assert result['records'] == first['records']
        assert result['sources'] == first['sources']
        assert result['sufficiency'] == 'unassessed'
    other = tools.call('search_evidence', {**args, 'course_id': 'history'})
    assert other['sources'][0]['source_id'] != first['sources'][0]['source_id']
    assert first['sources'][0]['refs'][0]['sha256'] == 'a' * 64


@pytest.mark.parametrize('name,args', [
    ('search_evidence', {'course_id': 'physics', 'query': 'Darcy', 'workspace': 'elsewhere'}),
    ('search_evidence', {'course_id': '../history', 'query': 'Darcy'}),
    ('search_evidence', {'course_id': 'physics', 'query': '  '}),
    ('get_source_page', {'course_id': 'physics', 'document_id': 'doc', 'page': True}),
    ('get_source_page', {'course_id': 'physics', 'document_id': 'doc', 'page': '1'}),
    ('read_file', {'path': 'outside'}),
])
def test_tool_arguments_reject_scope_path_and_type_confusion(tmp_path, name, args):
    with pytest.raises(ValueError):
        api(tmp_path).call(name, args)


def test_calculation_revalidates_citations_across_calls_and_courses(tmp_path):
    tools = api(tmp_path)
    evidence = tools.call('search_evidence', {'course_id': 'physics', 'query': 'Darcy'})
    source = evidence['sources'][0]
    args = {'course_id': 'physics', 'expression': 'q/phi', 'inputs': {'q': 2, 'phi': .25},
            'units': 'm/day', 'sources': [{'source_id': source['source_id'], 'record_id': source['record_id']}]}
    result = tools.call('calculate', args)
    assert result['value'] == 8
    assert result['validation'] == 'arithmetic_only'
    assert result['sources'][0]['refs'] == source['refs']
    with pytest.raises(ValueError):
        tools.call('calculate', {**args, 'course_id': 'history'})
    forged = deepcopy(args)
    forged['sources'][0]['source_id'] = 'src_' + '0' * 64
    with pytest.raises(ValueError):
        tools.call('calculate', forged)


def test_missing_source_answer_and_shared_parent_are_preserved(tmp_path):
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    store, manifest, raw = example(tmp_path)
    parent = Record(id='q', kind='question', title='Question', text='Assume constant density.', refs=raw.refs)
    child = Record(id='qa', kind='question', title='Part a', text='Calculate.', refs=raw.refs, parent_id='q')
    sid = store.publish('w', manifest, [parent, child], [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'])
    tools = PluginTools([CourseBinding('physics', store.path, scope)], Principal('alice', frozenset(['physics'])))
    result = tools.call('get_answer', {'course_id': 'physics', 'question_id': 'qa'})
    assert result['sufficiency'] == 'insufficient'
    assert {r['id'] for r in result['records']} == {'q', 'qa'}
    assert result['limitations']


def test_source_grants_are_not_mutable_after_binding(tmp_path):
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    store, manifest, record = example(tmp_path)
    sid = store.publish('w', manifest, [record], [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=[])
    binding = CourseBinding('physics', store.path, scope)
    scope.allowed_sources.append('doc')
    tools = PluginTools([binding], Principal('alice', frozenset(['physics'])))
    assert tools.call('search_evidence', {'course_id': 'physics', 'query': 'Darcy'})['sources'] == []


def test_citation_identity_survives_search_projection(tmp_path):
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    store, manifest, record = example(tmp_path)
    record.details = {'raw_text': 'Complete original Darcy text', 'source_excerpts': ['Duplicate extract']}
    sid = store.publish('w', manifest, [record], [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'])
    tools = PluginTools([CourseBinding('physics', store.path, scope)], Principal('alice', frozenset(['physics'])))
    result = tools.call('search_evidence', {'course_id': 'physics', 'query': 'Darcy'})
    source = result['sources'][0]
    calculated = tools.call('calculate', {'course_id': 'physics', 'expression': '2^3', 'inputs': {},
        'units': 'dimensionless', 'sources': [{'record_id': source['record_id'], 'source_id': source['source_id']}]})
    assert calculated['value'] == 8
