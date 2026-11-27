from copy import deepcopy
from hashlib import sha256
import json

import pytest


def pack_data(root, discipline='mathematics'):
    root.mkdir(parents=True, exist_ok=True)
    raw = 'Assume n is a positive integer.\fSum 1..n = n(n+1)/2.\n'
    (root / 'notes.txt').write_bytes(raw.encode())
    refs = [{'document_id': 'notes', 'page': 1}, {'document_id': 'notes', 'page': 2}]
    return {'workspace': 'demo', 'profile': {'course_id': 'demo-math', 'curriculum_system': 'demonstration',
        'institution': None, 'stage': 'university', 'language': 'en', 'syllabus_version': '2026-demo',
        'disciplines': [discipline], 'material_status': 'demonstration',
        'outcomes': [{'id': 'sum', 'description': 'Prove the finite sum', 'refs': refs, 'record_ids': ['proof']} ]},
        'manifest': {'course_key': 'demo-math', 'course_name': '原创演示：数学',
            'documents': [{'id': 'notes', 'relative_path': 'notes.txt', 'sha256': sha256(raw.encode()).hexdigest(),
                           'kind': 'lecture', 'pages': 2}]},
        'records': [{'id': 'proof', 'kind': 'proof', 'title': 'Finite sum proof', 'text': 'By induction.',
            'refs': refs, 'review': 'expert_checked', 'details': {'academic': {
                'nature': 'derivation', 'assumptions': ['n is a positive integer'],
                'steps': [{'text': 'Base case n=1.', 'refs': refs[:1]},
                          {'text': 'Inductive step.', 'refs': refs[1:]}]}}}], 'relations': []}


def test_import_preserves_cross_page_proof_and_candidate_status(tmp_path):
    from examsage.course_pack import CoursePack, import_pack
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    source, output = tmp_path / 'source', tmp_path / 'imported'
    pack = CoursePack.model_validate(pack_data(source))
    result = import_pack(pack, source, output)
    tools = PluginTools([CourseBinding('demo-math', output/'course.sqlite3', result.scope)],
                        Principal('alice', frozenset(['demo-math'])))
    record = tools.call('get_record', {'course_id': 'demo-math', 'record_id': 'proof'})['records'][0]
    assert [r['page'] for r in record['refs']] == [1, 2]
    assert record['review'] == 'candidate'
    assert len(record['details']['academic']['steps']) == 2
    assert result.report['semantic_review'] == 'pending'
    assert tools.call('get_source_page', {'course_id': 'demo-math', 'document_id': 'notes', 'page': 2})['records'][0]['text'].startswith('Sum')
    profile = tools.call('get_course_profile', {'course_id': 'demo-math'})
    assert profile['outcomes'][0]['record_ids'] == ['proof']
    assert profile['material_status'] == 'demonstration'
    with pytest.raises(FileExistsError):
        import_pack(pack, source, output)


@pytest.mark.parametrize('mutation', ['dangling_ref', 'missing_step_ref', 'cycle', 'wrong_course',
    'answer_type', 'ambiguous_answer', 'missing_support', 'private_support', 'outcome_record', 'answer_parent'])
def test_import_contract_rejects_incomplete_or_ambiguous_material(tmp_path, mutation):
    from examsage.course_pack import CoursePack
    data = pack_data(tmp_path/'source')
    record = data['records'][0]
    if mutation == 'dangling_ref': record['refs'][0]['page'] = 99
    elif mutation == 'missing_step_ref': record['refs'] = record['refs'][:1]
    elif mutation == 'cycle': record['parent_id'] = 'proof'
    elif mutation == 'wrong_course': data['profile']['course_id'] = 'different'
    elif mutation == 'answer_type':
        data['relations'] = [{'id': 'bad', 'kind': 'has_answer', 'source': 'proof', 'target': 'proof', 'refs': record['refs']}]
    elif mutation == 'ambiguous_answer':
        data['records'] += [dict(id='q', kind='question', title='Q', text='Calculate.', refs=record['refs']),
                            dict(id='a1', kind='answer', title='A1', text='1', refs=record['refs']),
                            dict(id='a2', kind='answer', title='A2', text='2', refs=record['refs'])]
        data['relations'] = [dict(id=a, kind='has_answer', source='q', target=a, refs=record['refs']) for a in ['a1','a2']]
    elif mutation == 'missing_support':
        record['kind'] = 'interpretation'
        record['details']['academic'] = {'nature': 'interpretation', 'evidence_record_ids': ['not-here']}
    elif mutation == 'private_support':
        record['kind'] = 'interpretation'
        record['refs'] = record['refs'][:1]
        record['details']['academic'] = {'nature': 'interpretation', 'evidence_record_ids': ['quote']}
        data['records'] += [dict(id='quote', kind='block', title='Quote', text='Original.', refs=[{'document_id':'notes','page':2}])]
    elif mutation == 'outcome_record': data['profile']['outcomes'][0]['record_ids'] = ['missing']
    elif mutation == 'answer_parent':
        data['records'] += [dict(id='q', kind='question', title='Q', text='Shared condition.', refs=record['refs'], parent_id='proof')]
    with pytest.raises(ValueError): CoursePack.model_validate(data)


@pytest.mark.parametrize('mutation', ['wrong_hash', 'outside', 'page_count'])
def test_bad_source_leaves_no_published_course(tmp_path, mutation):
    from examsage.course_pack import CoursePack, import_pack
    root = tmp_path/'source'
    data = pack_data(root)
    if mutation == 'wrong_hash': (root/'notes.txt').write_text('changed', encoding='utf-8')
    elif mutation == 'outside': data['manifest']['documents'][0]['relative_path'] = '../notes.txt'
    else:
        raw = 'one page'
        (root/'notes.txt').write_text(raw, encoding='utf-8')
        data['manifest']['documents'][0]['sha256'] = sha256(raw.encode()).hexdigest()
    with pytest.raises(ValueError): import_pack(CoursePack.model_validate(data), root, tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_course_profile_does_not_reveal_outcome_from_excluded_source(tmp_path):
    from examsage.course_pack import CoursePack, import_pack
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    data = pack_data(tmp_path/'source')
    result = import_pack(CoursePack.model_validate(data), tmp_path/'source', tmp_path/'output')
    scope = result.scope.model_copy(update={'allowed_sources': []})
    tools = PluginTools([CourseBinding('demo-math', tmp_path/'output/course.sqlite3', scope)],
                        Principal('alice', frozenset(['demo-math'])))
    catalog = tools.call('list_courses', {})
    assert 'Prove the finite sum' not in json.dumps(catalog)
    profile = tools.call('get_course_profile', {'course_id': 'demo-math'})
    assert profile['outcomes'] == []
    assert profile['unavailable_outcomes'] == 1


@pytest.mark.parametrize('field,value', [('audit', {'adjudication': []}), ('supplement', {'ocr': []}),
                                        ('warnings', [1]), ('raw_text', {'unexpected': True})])
def test_import_rejects_reserved_core_details_before_publication(tmp_path, field, value):
    from examsage.course_pack import CoursePack, import_pack
    data = pack_data(tmp_path/'source')
    data['records'][0]['details'][field] = value
    with pytest.raises(ValueError):
        import_pack(CoursePack.model_validate(data), tmp_path/'source', tmp_path/'output')
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('tool_name', ['get_course_profile', 'list_courses'])
def test_profile_cannot_bypass_tool_output_budget(tmp_path, tool_name):
    from examsage.course_pack import CoursePack, import_pack
    from examsage.plugin_tools import CourseBinding, PluginTools, Principal
    data = pack_data(tmp_path/'source')
    original = data['profile']['outcomes'][0]
    if tool_name == 'get_course_profile':
        data['profile']['outcomes'] = [{**original, 'id': 'outcome-'+str(i), 'description': 'x'*2000} for i in range(300)]
    else:
        data['profile']['disciplines'] = ['x'*2000 for _ in range(300)]
    result = import_pack(CoursePack.model_validate(data), tmp_path/'source', tmp_path/'output')
    tools = PluginTools([CourseBinding('demo-math', tmp_path/'output/course.sqlite3', result.scope)],
                        Principal('alice', frozenset(['demo-math'])))
    with pytest.raises(ValueError, match='too large'):
        tools.call(tool_name, {'course_id': 'demo-math'} if tool_name=='get_course_profile' else {})
