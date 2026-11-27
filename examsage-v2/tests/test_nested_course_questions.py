import pytest

from examsage.domain import Record, Relation, Scope
from examsage.search import CourseQueryService
from test_core import example


def nested_course(tmp_path):
    store, manifest, raw = example(tmp_path)
    records = []
    for rid, part, parent in [('q', None, None), ('qa', 'a', 'q'),
                              ('qai', 'a.i', 'qa'), ('qaii', 'a.ii', 'qa')]:
        records.append(Record(id=rid, kind='question', title=rid, text='Compute '+rid,
            refs=raw.refs, parent_id=parent, details={'exam_year': 2024, 'number': '1', 'part': part}))
    # The answer deliberately has no query words: exact pairing must drive lookup.
    records.append(Record(id='ai', kind='answer', title='结果值', text='17', refs=raw.refs))
    edges = [Relation(id='pair', source='qai', target='ai', kind='has_answer', refs=raw.refs)]
    sid = store.publish('w', manifest, records, edges, {'mode': 'course_pack'})
    scope = Scope(workspace='w', course=manifest.course_key, snapshot=sid, allowed_sources=['doc'])
    return CourseQueryService(store), scope


@pytest.mark.parametrize('query', ['2024 Q1(a)(i) answer', '2024 Q1(a.i) 答案',
                                 '2024 Q1 a.i solution', '2024 第1题第a.i小问答案'])
def test_exact_nested_question_uses_pairing_and_preserves_all_parents(tmp_path, query):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, query)
    assert {r.id for r in result.records} == {'q', 'qa', 'qai', 'ai'}
    assert result.records[0].id == 'qai'
    assert [r.id for r in result.relations] == ['pair']


@pytest.mark.parametrize('query', ['2024 Q1(a)(ix) answer', '2024 Q1(a.ix) 答案',
                                 '2024 Q1(a)(i) and (ii) answer', '2024 Q1(a)(i) 和 Q2 答案'])
def test_missing_or_ambiguous_nested_question_does_not_fall_back(tmp_path, query):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, query)
    assert result.records == []
    assert result.sufficiency == 'insufficient'


@pytest.mark.parametrize('limit,max_chars', [(3, 24000), (8, 100)])
def test_nested_answer_and_conditions_are_budgeted_as_one_group(tmp_path, limit, max_chars):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, '2024 Q1(a)(i) answer', limit=limit, max_chars=max_chars)
    assert result.records == []
    assert result.sufficiency == 'insufficient'


def test_nested_missing_answer_is_explicit_and_keeps_question(tmp_path):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, '2024 Q1(a)(ii) answer')
    assert {r.id for r in result.records} == {'q', 'qa', 'qaii'}
    assert result.sufficiency == 'insufficient'


@pytest.mark.parametrize('separator', [',', '，', '/', '&', ';', '；', '+', 'vs', 'versus', '与', '或', 'to', '以及', '到'])
def test_multiple_part_request_cannot_silently_answer_only_first(tmp_path, separator):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, f'2024 Q1(a)(i) {separator} (ii) answer')
    assert result.records == []
    assert result.sufficiency == 'insufficient'


@pytest.mark.parametrize('suffix', [', explain the answer', ' answer, I think 17', ' with x and y = 17',
    ', I think the answer is 17', ', x = 17, answer', ', I believe the answer is 17',
    ' answer, explain this part of the solution', ', i think the answer is 17'])
def test_punctuation_before_ordinary_prose_is_not_an_ambiguous_part(tmp_path, suffix):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, '2024 Q1(a)(i)'+suffix+' answer')
    assert {r.id for r in result.records} == {'q', 'qa', 'qai', 'ai'}


@pytest.mark.parametrize('suffix', ['and ii answer', 'or b solution', ', b.ii answer', '/ ii', '与 ii 答案',
    '和 ii 的答案', 'and ii how do I calculate the answer', 'and ii show all working', 'and b\'s answer'])
def test_explicit_bare_secondary_part_is_ambiguous(tmp_path, suffix):
    service, scope = nested_course(tmp_path)
    result = service.search_evidence(scope, '2024 Q1(a)(i) '+suffix)
    assert result.records == []
    assert result.sufficiency == 'insufficient'


@pytest.mark.parametrize('part', ['a.i', None])
def test_same_exam_path_from_two_variants_requires_disambiguation(tmp_path, part):
    store, manifest, raw = example(tmp_path)
    questions = [Record(id=rid, kind='question', title='Same number, different paper',
        text='Compute '+rid, refs=raw.refs, details={'exam_year':2024,'number':'1','part':part})
        for rid in ['q-one', 'q-two']]
    answers = [Record(id='a-'+q.id, kind='answer', title='Result', text=str(i), refs=raw.refs)
               for i, q in enumerate(questions)]
    pairs = [Relation(id='pair-'+q.id, kind='has_answer', source=q.id, target=a.id, refs=raw.refs)
             for q, a in zip(questions, answers)]
    sid = store.publish('w', manifest, questions+answers, pairs, {'mode':'course_pack'})
    scope = Scope(workspace='w', course=manifest.course_key, snapshot=sid, allowed_sources=['doc'])
    service = CourseQueryService(store)
    query = '2024 Q1'+('(a)(i)' if part else '')+' answer'
    result = service.search_evidence(scope, query)
    assert result.records == []
    assert result.sufficiency == 'insufficient'
    assert 'ambiguous' in ' '.join(result.limitations).lower()
    # Explicit identity still lets a caller choose the correct source variant.
    assert {r.id for r in service.get_answer(scope,'q-one').records} == {'q-one','a-q-one'}
