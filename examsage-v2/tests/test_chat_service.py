import json
import threading

import pytest

from examsage.domain import Scope, Record, SourceRef
from examsage.chat_service import CourseTools, build_context, validate_answer
from examsage.model_runtime import RuntimeFailure
from test_core import example


def setup(tmp_path):
    store, manifest, record = example(tmp_path)
    record.limitations = ['Source has an unresolved unit ambiguity.']
    sid = store.publish('w', manifest, [record], [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'])
    return store, scope


def answer(citations, kind='source'):
    return {'paragraphs': [{'text': 'Darcy 通量与孔隙流速需要区分。', 'kind': kind,
                            'citations': citations}], 'limitations': []}


def test_sources_are_server_bound_and_limitations_cannot_be_dropped(tmp_path):
    store, scope = setup(tmp_path)
    tools = CourseTools(store, scope)
    result = tools.call('search_evidence', {'query': 'Darcy'})
    evidence_id = result['records'][0]['evidence_ids'][0]
    final = validate_answer(answer([evidence_id]), tools)
    assert final['evidence'][0]['refs'][0]['sha256'] == 'a' * 64
    assert final['evidence'][0]['refs'][0]['page'] == 1
    assert 'Source has an unresolved unit ambiguity.' in final['limitations']
    assert final['paragraphs'][0]['citations'] == [evidence_id]


@pytest.mark.parametrize('citations', [['E999'], []])
def test_fabricated_or_missing_citation_rejects_factual_answer(tmp_path, citations):
    store, scope = setup(tmp_path)
    tools = CourseTools(store, scope)
    tools.call('search_evidence', {'query': 'Darcy'})
    with pytest.raises(RuntimeFailure) as error:
        validate_answer(answer(citations), tools)
    assert error.value.code == ('invalid_citation' if citations else 'missing_citation')


def test_insufficient_answer_after_empty_search_is_allowed(tmp_path):
    store, scope = setup(tmp_path)
    tools = CourseTools(store, scope)
    tools.call('search_evidence', {'query': 'absent-topic-9284'})
    final = validate_answer(answer([], 'insufficient'), tools)
    assert final['evidence'] == []


def test_model_reporting_tool_failure_without_any_search_is_not_a_completed_answer(tmp_path):
    store, scope = setup(tmp_path)
    raw = answer([], 'insufficient')
    raw['limitations'] = ['code-mode host is disabled']
    with pytest.raises(RuntimeFailure) as error:
        validate_answer(raw, CourseTools(store, scope))
    assert error.value.code == 'evidence_not_checked'


def test_evidence_limit_reports_failed_operation_and_bytes_without_truncating_sources(tmp_path):
    store, scope = setup(tmp_path)
    tools = CourseTools(store, scope); tools._bytes = 99999
    with pytest.raises(RuntimeFailure) as error:
        tools.call('search_evidence', {'query': 'Darcy'})
    assert error.value.code == 'evidence_limit'
    assert error.value.details['tool'] == 'search_evidence'
    assert error.value.details['used_bytes'] == 99999
    assert error.value.details['requested_bytes'] > 1
    assert error.value.details['limit_bytes'] == 100000
    assert tools.trace == [] and tools.evidence == {}


@pytest.mark.parametrize('name,args', [
    ('read_file', {'path': 'auth.json'}),
    ('search_evidence', {'query': 'Darcy', 'scope': 'other'}),
    ('get_source_page', {'document_id': 'doc', 'page': True}),
    ('calculate', {'expression': "__import__('os')", 'inputs': {}, 'units': '', 'source_ids': []}),
])
def test_untrusted_tool_arguments_are_rejected(tmp_path, name, args):
    store, scope = setup(tmp_path)
    with pytest.raises(RuntimeFailure): CourseTools(store, scope).call(name, args)


def test_scope_filter_applies_before_evidence_assignment(tmp_path):
    store, scope = setup(tmp_path)
    tools = CourseTools(store, scope.model_copy(update={'allowed_sources': []}))
    result = tools.call('search_evidence', {'query': 'Darcy'})
    assert result['records'] == []
    assert tools.evidence == {}


def test_calculation_retains_formula_sources_and_inputs(tmp_path):
    store, scope = setup(tmp_path); tools = CourseTools(store, scope)
    result = tools.call('search_evidence', {'query': 'Darcy'})
    eid = result['records'][0]['evidence_ids'][0]
    calculated = tools.call('calculate', {'expression': 'q / porosity',
        'inputs': {'q': 2, 'porosity': .25}, 'units': 'm/day', 'source_ids': [eid]})
    assert calculated['value'] == 8
    final = validate_answer(answer([calculated['evidence_id']], 'derivation'), tools)
    assert final['evidence'][0]['calculation']['inputs']['porosity'] == .25
    assert final['evidence'][0]['refs'][0]['page'] == 1


def test_decay_calculation_accepts_math_power_and_preserves_source_expression(tmp_path):
    store, scope = setup(tmp_path); tools = CourseTools(store, scope)
    result = tools.call('search_evidence', {'query': 'Darcy'})
    eid = result['records'][0]['evidence_ids'][0]
    calculated = tools.call('calculate', {'expression': '2^(-t/T)',
        'inputs': {'t': 677886.0457341605, 'T': 300000},
        'units': 'dimensionless', 'source_ids': [eid]})
    assert calculated['value'] == pytest.approx(0.2088269547228607)
    source = tools.evidence[calculated['evidence_id']]
    assert source['calculation']['expression'] == '2^(-t/T)'
    assert source['calculation']['source_ids'] == [eid]


def test_long_conversation_keeps_all_user_corrections_and_marks_answers_as_derived():
    messages = [{'role': 'user', 'content': '题设切入风速为3，现改成4 m/s'}]
    for i in range(30):
        messages.extend([{'role': 'assistant', 'content': '旧模型回答，不能作为证据。'},
                         {'role': 'user', 'content': f'第{i}轮追问'}])
    context = build_context(messages, 'c')
    assert '现改成4 m/s' in context and '第29轮追问' in context
    assert '不是证据' in context


def test_long_conditions_are_rejected_instead_of_truncated():
    with pytest.raises(RuntimeFailure) as error:
        build_context([{'role': 'user', 'content': '完整题干' * 20000}], 'c')
    assert error.value.code == 'context_limit'


def test_cross_page_derivation_has_step_specific_citations(tmp_path):
    store, manifest, record = example(tmp_path)
    record = record.model_copy(update={'kind': 'concept', 'details': {'derivation': {
        'steps': [{'title': '一步', 'text': '积分', 'refs': [{'document_id': 'doc', 'page': 1}]},
                  {'title': '二步', 'text': '边界', 'refs': [{'document_id': 'doc', 'page': 2}]}],
        'conditions': ['小挠度'], 'warnings': ['符号需核对']}}})
    sid = store.publish('w', manifest, [record], [], {})
    tools = CourseTools(store, Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc']))
    result = tools.call('get_concept', {'concept_id': 'b'})
    ids = result['records'][0]['evidence_ids']
    assert len(ids) == 2
    assert [e['refs'][0]['page'] for e in tools.evidence.values()] == [1, 2]
    assert '小挠度' in result['records'][0]['details']['derivation']['conditions']


def test_page_hit_can_recover_its_complete_cross_page_derivation(tmp_path):
    store, manifest, page = example(tmp_path)
    chain = Record(id='chain', kind='concept', title='Worked sequence', text='Two steps',
        refs=[SourceRef(document_id='doc', page=1), SourceRef(document_id='doc', page=2)],
        details={'derivation': {'steps': [
            {'title': 'Start', 'text': 'Definition', 'refs': [{'document_id': 'doc', 'page': 1}]},
            {'title': 'Finish', 'text': 'Boundary condition', 'refs': [{'document_id': 'doc', 'page': 2}]}]}})
    sid = store.publish('w', manifest, [page, chain], [], {})
    tools = CourseTools(store, Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc']))
    result = tools.call('search_evidence', {'query': 'Darcy'})
    assert any(r['id'] == 'chain' for r in result['records'])
    assert any(ref['page'] == 2 for e in tools.evidence.values() for ref in e['refs'])


def test_repeated_identical_records_reuse_prior_content_without_resending_it(tmp_path):
    store, scope = setup(tmp_path); tools = CourseTools(store, scope)
    first = tools.call('search_evidence', {'query': 'Darcy'})
    before = tools._bytes
    second = tools.call('search_evidence', {'query': 'Darcy'})
    assert second['records'] == [] and second['evidence'] == []
    assert second['record_references'][0]['id'] == first['records'][0]['id']
    assert second['reused_evidence_ids'] == first['records'][0]['evidence_ids']
    assert tools._bytes - before == len(json.dumps(second, ensure_ascii=False).encode('utf-8'))
    assert len(json.dumps(second, ensure_ascii=False)) < len(json.dumps(first, ensure_ascii=False))
    assert validate_answer(answer(first['records'][0]['evidence_ids']), tools)['evidence']


def test_same_record_id_with_additional_original_details_is_not_discarded(tmp_path, monkeypatch):
    store, scope = setup(tmp_path); tools = CourseTools(store, scope)
    bundle = tools.service.search_evidence(scope, 'Darcy')
    monkeypatch.setattr(tools.service, 'get_source_page', lambda *args, **kwargs: bundle)
    first = tools.call('get_source_page', {'document_id': 'doc', 'page': 1})
    changed = bundle.model_copy(deep=True)
    changed.records[0].details['raw_text'] = 'Original formula with a newly supplied condition.'
    monkeypatch.setattr(tools.service, 'get_source_page', lambda *args, **kwargs: changed)
    second = tools.call('get_source_page', {'document_id': 'doc', 'page': 1})
    assert second['records'][0]['id'] == first['records'][0]['id']
    assert second['records'][0]['details']['raw_text'] == changed.records[0].details['raw_text']


@pytest.mark.parametrize('derivation', [False, True])
def test_wire_references_duplicate_evidence_text_without_losing_content(tmp_path, derivation):
    store, manifest, record = example(tmp_path)
    record.id = 'b' if derivation else 'doc:p1'
    long_text = '完整条件及推导内容abc' * 200
    record.text = long_text if not derivation else 'The complete two-step derivation.'
    record.kind = 'concept' if derivation else 'block'
    if derivation:
        record.details = {'derivation': {'steps': [
            {'title': 'Step 1', 'text': long_text, 'latex': 'M = E h^3 / (12 R)',
             'refs': [{'document_id': 'doc', 'page': 1}]},
            {'title': 'Step 2', 'text': '保留下一页边界条件' * 200,
             'refs': [{'document_id': 'doc', 'page': 2}]}],
            'conditions': ['small slope'], 'warnings': ['source sign conflict']}}
    sid = store.publish('w', manifest, [record], [], {})
    tools = CourseTools(store, Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc']))
    result = tools.call('get_concept', {'concept_id': record.id}) if derivation else tools.call(
        'get_source_page', {'document_id': 'doc', 'page': 1})
    wire = json.dumps(result, ensure_ascii=False)
    assert wire.count(long_text) == 1  # Full record and citation must share this text.
    assert result['records'][0]['text'] == record.text
    assert result['records'][0]['details'] == record.details
    for e in result['evidence']:
        ref = e['text_reference']
        full = next(r for r in result['records'] if r['id'] == e['record_id'] and
                    r['content_hash'] == ref['content_hash'])
        if ref['derivation_step_index'] is None:
            reconstructed = full['text']
        else:
            step = full['details']['derivation']['steps'][ref['derivation_step_index']]
            reconstructed = step.get('text', '') + '\n' + step.get('latex', '')
        assert reconstructed == tools.evidence[e['id']]['text']
        assert e['refs'] == tools.evidence[e['id']]['refs']
    final = validate_answer(answer([e['id'] for e in result['evidence']]), tools)
    assert all('text_reference' not in e and e['text'] for e in final['evidence'])


def test_empty_derivation_step_reference_keeps_whole_record_fallback(tmp_path):
    store, manifest, record = example(tmp_path)
    record.kind = 'concept'; record.text = 'Fallback complete original text. ' * 100
    record.details = {'derivation': {'steps': [{}]}}
    sid = store.publish('w', manifest, [record], [], {})
    tools = CourseTools(store, Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc']))
    result = tools.call('get_concept', {'concept_id': record.id})
    e = result['evidence'][0]; ref = e['text_reference']; full = result['records'][0]
    if ref['derivation_step_index'] is None:
        reconstructed = full['text']
    else:
        step = full['details']['derivation']['steps'][ref['derivation_step_index']]
        reconstructed = step.get('text', '') + '\n' + step.get('latex', '')
    assert reconstructed == record.text == tools.evidence[e['id']]['text']


def test_transmission_budget_counts_final_merged_result_and_reports_remaining_calls(tmp_path):
    store, scope = setup(tmp_path); tools = CourseTools(store, scope)
    first = tools.call('search_evidence', {'query': 'Darcy'})
    assert tools._bytes == len(json.dumps(first, ensure_ascii=False).encode('utf-8'))
    assert first['tool_budget'] == {'used': 1, 'remaining': 5, 'limit': 6}
    second = tools.call('get_source_page', {'document_id': 'doc', 'page': 1})
    assert tools._bytes == sum(len(json.dumps(r, ensure_ascii=False).encode('utf-8')) for r in (first, second))
    assert second['tool_budget']['remaining'] == 4


@pytest.mark.parametrize('extra_byte', [0, 1])
def test_linked_derivation_uses_final_merged_budget_and_rolls_back_only_if_too_large(tmp_path, extra_byte):
    store, manifest, page = example(tmp_path)
    shared_warning = 'Shared source caveat. ' * 40
    page.limitations = [shared_warning]
    chain = Record(id='chain', kind='concept', title='Worked sequence', text='Two steps',
        limitations=[shared_warning], refs=[SourceRef(document_id='doc', page=1)],
        details={'derivation': {'steps': [
            {'title': 'Finish', 'text': 'Boundary condition', 'refs': [{'document_id': 'doc', 'page': 2}]}]}})
    sid = store.publish('w', manifest, [page, chain], [], {})
    scope = Scope(workspace='w', course='c', snapshot=sid, allowed_sources=['doc'])
    full = CourseTools(store, scope).call('search_evidence', {'query': 'Darcy'})
    assert {r['id'] for r in full['records']} == {'b', 'chain'}
    wire_bytes = len(json.dumps(full, ensure_ascii=False).encode('utf-8'))
    tools = CourseTools(store, scope)
    initial_bytes = 100000 - wire_bytes + extra_byte
    tools._bytes = initial_bytes
    result = tools.call('search_evidence', {'query': 'Darcy'})
    assert tools._bytes == initial_bytes + len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    if extra_byte == 0:
        assert {r['id'] for r in result['records']} == {'b', 'chain'}
        assert tools._bytes == 100000
        assert any(e['refs'][0]['page'] == 2 for e in tools.evidence.values())
    else:
        assert [r['id'] for r in result['records']] == ['b']
        assert all(e['record_id'] == 'b' for e in tools.evidence.values())
        assert any('关联推导未能' in warning for warning in result['limitations'])
        tools._bytes = 0
        later = tools.call('get_concept', {'concept_id': 'chain'})
        assert [r['id'] for r in later['records']] == ['chain']
        assert later['record_references'] == []
