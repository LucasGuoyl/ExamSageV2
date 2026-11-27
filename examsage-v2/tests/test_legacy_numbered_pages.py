from hashlib import sha256

from examsage.search import CourseQueryService
from examsage.storage import Store
from test_numbered_source_pages import course, SOL


def legacy_store(root, *, paper=None, solution=SOL, extra=(), hide=(), absent_index=True, untyped=False):
    kwargs = {'paper': paper} if paper is not None else {}
    tools, cid = course(root, solution=solution, extra=extra, **kwargs)
    binding, source = tools._course(cid)
    metadata = dict(source.metadata(binding.scope))
    metadata.pop('ambiguous_solution_documents')
    if absent_index:
        metadata.pop('numbered_page_index')
    else:
        metadata['numbered_page_index'] = {}
    manifest = source.manifest(binding.scope)
    rows = source.list_records(binding.scope)
    exam = next(doc for doc in manifest.documents if doc.kind == 'exam')
    if untyped:
        for doc in manifest.documents:
            doc.kind, doc.exam_year = 'unknown', None
    for row in rows:
        if row.refs[0].document_id == exam.id and row.refs[0].page in hide:
            row.visibility = 'hidden'
    target = Store(root/'legacy.sqlite3')
    snapshot = target.publish(binding.scope.workspace, manifest, rows, [], metadata)
    scope = binding.scope.model_copy(update={'snapshot':snapshot})
    return CourseQueryService(Store(target.path, read_only=True)), scope, manifest


def test_existing_snapshot_search_keeps_source_identity_and_never_writes(tmp_path):
    service, scope, docs = legacy_store(tmp_path)
    before = sha256(service.store.path.read_bytes()).digest()
    result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
    assert result.sufficiency == 'unassessed' and result.snapshot == scope.snapshot
    assert [r.details['locator_role'] for r in result.records] == ['question']*2 + ['answer_candidate']*2
    for row in result.records:
        original = service.store.get(scope, row.id)
        assert original.refs == row.refs and row.text in original.details['raw_text']
    exam = next(doc for doc in docs.documents if doc.kind == 'exam')
    narrow = scope.model_copy(update={'allowed_sources':[exam.id]})
    restricted = service.search_evidence(narrow, '2025 Q3(b)(ii) 答案')
    assert restricted.sufficiency == 'insufficient' and restricted.records
    assert all(r.details['locator_role'] == 'question' for r in restricted.records)
    assert sha256(service.store.path.read_bytes()).digest() == before


def test_legacy_hidden_physical_page_breaks_relative_numbering(tmp_path):
    service, scope, _ = legacy_store(tmp_path, paper='Q3(b) Parent.\fi) Hidden.\fii) WRONG relative parent.', hide=[2])
    result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
    assert result.sufficiency == 'insufficient' and not result.records


def test_old_solution_with_conflicting_year_is_excluded_even_with_a_narrow_grant(tmp_path):
    service, scope, docs = legacy_store(tmp_path, extra=[('other.txt','exam_solution',2024,SOL)])
    allowed = [doc.id for doc in docs.documents if doc.exam_year == 2025]
    result = service.search_evidence(scope.model_copy(update={'allowed_sources':allowed}), '2025 Q3(b)(ii) 答案')
    assert result.sufficiency == 'insufficient' and result.records
    assert all(r.details['locator_role'] == 'question' for r in result.records)


def test_existing_empty_index_stays_authoritative(tmp_path):
    service, scope, _ = legacy_store(tmp_path, absent_index=False)
    result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
    assert result.sufficiency == 'insufficient' and not result.records

def test_old_untyped_upload_explains_missing_material_declarations(tmp_path):
    service, scope, _ = legacy_store(tmp_path, untyped=True)
    result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
    assert result.sufficiency == 'insufficient' and not result.records
    assert '考年' in ''.join(result.limitations) and '资料类型' in ''.join(result.limitations)


def test_inline_adjacent_answer_is_never_returned_as_the_requested_answer(tmp_path):
    service, scope, _ = legacy_store(tmp_path, solution='3.b.ii) Demand = 7.5 kW.  3.b.iii) Supply = 280 kW.')
    result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
    assert '280 kW' not in ''.join(r.text for r in result.records)
    assert result.sufficiency == 'insufficient' or any('7.5 kW' in r.text for r in result.records)


def test_qualified_leaf_cannot_repair_a_gap_in_parent_conditions(tmp_path):
    service, scope, _ = legacy_store(tmp_path, hide=[2],
        paper='Question 3 Conditions.\fPrice on hidden page.\fQ3(b)(ii) Using the price above, compute net value.\nQ3(b)(iii) Other.')
    result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
    assert result.sufficiency == 'insufficient' and not any(r.details['locator_role']=='answer_candidate' for r in result.records)


def test_missing_or_ambiguous_exam_year_does_not_reveal_an_answer_page(tmp_path):
    service, scope, _ = legacy_store(tmp_path)
    for query in ('Q3(b)(ii) 答案', '2024/25 Q3(b)(ii) 答案', '2024 和 2025 Q3(b)(ii) 答案'):
        result = service.search_evidence(scope, query)
        assert result.sufficiency == 'insufficient' and not result.records
        notice = ''.join(result.limitations)
        assert '考年' in notice and '0 年' not in notice


def test_question_only_keeps_solution_hidden_for_a_student_practising(tmp_path):
    service, scope, _ = legacy_store(tmp_path)
    for query in ('2025 Q3(b)(ii) 不要答案，只给题目', '2025 Q3(b)(ii) without the solution'):
        result = service.search_evidence(scope, query)
        assert result.records and all(r.details['locator_role']=='question' for r in result.records)


def test_spelled_out_first_label_and_numeric_inline_sibling(tmp_path):
    for i, head in enumerate(('Question 3(b)(ii)', 'Q 3(b)(ii)')):
        service, scope, _ = legacy_store(tmp_path/str(i), solution=head+' Demand = 7.5 kW.')
        result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
        assert any('7.5 kW' in r.text for r in result.records if r.details['locator_role']=='answer_candidate')
    for i, line in enumerate(('3.b.ii) Demand = 7.5 kW.  (iii) 280 kW.', '3.b.ii) 7.5 kW   (iii) 280 kW.')):
        service, scope, _ = legacy_store(tmp_path/('s'+str(i)), solution=line)
        result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
        assert '280 kW' not in ''.join(r.text for r in result.records)


def test_inline_numbered_value_with_any_spacing_stays_out_of_answer(tmp_path):
    for i, (space, label, value) in enumerate([(' ', '(iii)', '280'), ('  ', 'iii)', '+280'),
                                                ('   ', '(c)', '−280'), (' ', '(iii)', '.280')]):
        line = '3.b.ii) Demand = 7.5 kW'+space+label+' '+value+' kW.'
        service, scope, _ = legacy_store(tmp_path/str(i), solution=line)
        result = service.search_evidence(scope, '2025 Q3(b)(ii) 答案')
        assert '280' not in ''.join(r.text for r in result.records)
