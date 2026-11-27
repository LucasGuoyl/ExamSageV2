import io

from examsage.domain import Scope
from examsage.plugin_tools import Principal
from examsage.search import CourseQueryService
from examsage.student_workspace import StudentWorkspace, student_tools
from examsage.web_intake import import_selection

PAPER = ('Question 3 on Heat\na) Calculate the loss.\nb) A house has area 100 m².\n'
         'i) Use 20 degrees.\fii) Compute the result.\n'
         'iii) Change the outside temperature.\nQuestion 4 on Storage\na) Unrelated.')
SOL = '3.b.i) Earlier result ONLY\n3.b.ii) Demand = 7.5\fUnit: kW.\n3.b.iii) Neighbor answer ONLY'


def course(root, extra=(), solution=SOL, paper=PAPER):
    workspace=StudentWorkspace(root,Principal('a',frozenset()))
    rows=[('paper.txt','exam',2025,paper),('solution.txt','exam_solution',2025,solution),*extra]
    labels=[dict(filename=name,kind=kind,exam_year=year) for name,kind,year,_ in rows]
    files=[(name,io.BytesIO(content.encode())) for name,_,_,content in rows]
    receipt=import_selection(workspace.imports,'Heat','Physics',files,materials=labels)
    return student_tools(None,workspace),'upload-'+receipt['id']


def ask(tools,cid,query):
    return tools.call('search_evidence',dict(course_id=cid,query=query))


def test_numbered_answer_returns_own_excerpt_and_previous_question_conditions(tmp_path):
    tools,cid=course(tmp_path)
    data=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    assert data['mode']=='numbered_source_pages' and data['sufficiency']=='unassessed'
    question=[r for r in data['records'] if r['details']['locator_role']=='question']
    answer=[r for r in data['records'] if r['details']['locator_role']=='answer_candidate']
    assert [r['refs'][0]['page'] for r in question]==[1,2]
    assert [r['refs'][0]['page'] for r in answer]==[1,2]
    assert 'area 100' in question[0]['text'] and 'Compute the result' in question[1]['text']
    assert 'outside temperature' not in question[1]['text'] and 'Earlier result' not in str(answer)
    assert '7.5' in answer[0]['text'] and 'kW' in answer[1]['text'] and 'Neighbor answer' not in str(answer)
    for r in data['records']:
        ref=r['refs'][0]
        page=tools.call('get_source_page',dict(course_id=cid,document_id=ref['document_id'],page=ref['page']))
        assert r['source_id']==page['sources'][0]['source_id']
        assert r['text'] in page['records'][0]['text']
    assert data['relations']==[] and any('候选' in w for w in data['limitations'])
    assert all(r['details']['locator_role']=='question' for r in ask(tools,cid,'2025 Q3(b)(ii)')['records'])


def test_multiple_solution_editions_or_missing_leaf_preserve_only_question(tmp_path):
    tools,cid=course(tmp_path,extra=[('alt.txt','exam_solution',2025,'3.b.ii) Different sitting')])
    data=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    assert data['sufficiency']=='insufficient' and data['records']
    assert all(r['details']['locator_role']=='question' for r in data['records'])
    assert not ask(tools,cid,'2025 Q3(b)(viii) 答案')['records']
    tools,cid=course(tmp_path/'missing',solution='3.b.v) Label does not match.')
    response=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    assert response['sufficiency']=='insufficient' and 'Label does not match' not in str(response)


def test_source_scope_does_not_reveal_answers_or_confuse_numbers(tmp_path):
    tools,cid=course(tmp_path)
    binding,store=tools._course(cid)
    doc=next(d for d in store.manifest(binding.scope).documents if d.kind=='exam')
    service=CourseQueryService(store)
    narrowed=binding.scope.model_copy(update={'allowed_sources':[doc.id]})
    result=service.search_evidence(narrowed,'2025 Q3(b)(ii) 答案')
    assert result.records and result.sufficiency=='insufficient'
    assert all(r.refs[0].document_id==doc.id for r in result.records)
    assert '7.5' not in result.model_dump_json()
    insufficient=service.search_evidence(binding.scope,'2025 Q3(b)(ii) 答案',max_chars=100)
    assert insufficient.sufficiency=='insufficient' and not insufficient.records


def test_relative_solution_path_spans_pages_and_does_not_fill_mislabelled_roman(tmp_path):
    solution=('Question 3 on Heat\na) Limits.\nb) A house.\ni) Earlier.\fii) Select a unit.\f7.5 kW.\niii) Other.')
    tools,cid=course(tmp_path,solution=solution)
    result=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    answer=[r for r in result['records'] if r['details']['locator_role']=='answer_candidate']
    assert [r['refs'][0]['page'] for r in answer]==[2,3] and '7.5' in answer[-1]['text']
    assert 'Other' not in str(answer)
    tools,cid=course(tmp_path/'missing',solution=solution.replace('ii) Select','iv) Select'))
    assert ask(tools,cid,'2025 Q3(b)(ii) 答案')['sufficiency']=='insufficient'


def test_question_or_answer_gap_returns_insufficient_without_a_partial_answer(tmp_path):
    tools,cid=course(tmp_path,solution='3.b.ii) estimate\f\f7.5 kW.\n3.b.iii) Other.')
    data=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    assert data['sufficiency']=='insufficient' and data['records']
    assert not any(r['details']['locator_role']=='answer_candidate' for r in data['records'])


def test_common_alternative_number_boundaries_do_not_append_a_neighbor(tmp_path):
    for ix,boundary in enumerate(['3.b.iii.','Q4.','(iii)','Part C','Q3(b)(iii):','3(b)(iii)','(iii)Wrong','3. (c)']):
        tools,cid=course(tmp_path/str(ix),solution='3.b.ii) SELECTED\n'+boundary+' NEIGHBOR')
        result=ask(tools,cid,'2025 Q3(b)(ii) 答案')
        assert 'NEIGHBOR' not in str(result['records'])


def test_contradictory_solution_dates_cannot_supply_an_answer(tmp_path):
    tools,cid=course(tmp_path,extra=[('other.txt','exam_solution',2024,SOL)])
    result=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    assert result['sufficiency']=='insufficient' and 'Earlier result' not in str(result)
    assert all(r['details']['locator_role']=='question' for r in result['records'])


def test_explicit_parent_is_not_dropped_when_a_short_roman_follows(tmp_path):
    tools,cid=course(tmp_path,paper='Q3(b) Buildings.\ni) Earlier.\nii) Compute.',
        solution='3.ii) WRONG LEVEL\n3.b.ii) CORRECT LEVEL')
    match=ask(tools,cid,'2025 Q3(b)(ii) 答案')
    assert 'CORRECT LEVEL' in str(match['records']) and 'WRONG LEVEL' not in str(match['records'])
    assert not ask(tools,cid,'2025 Q3(ii) 答案')['records']


def test_scoped_release_keeps_only_allowed_locators_even_on_second_export(tmp_path):
    from examsage.release import publish_release
    from examsage.storage import Store
    tools,cid=course(tmp_path/'student')
    binding,store=tools._course(cid)
    papers=store.manifest(binding.scope).documents
    scope=binding.scope.model_copy(update={'allowed_sources':[papers[0].id]})
    for sub in ['one','two']:
        out=tmp_path/sub
        publish_release(store,scope,store.path.parent/'assets',out)
        assert papers[1].id not in (out/'provenance.json').read_text(encoding='utf8')
        scope=Scope.model_validate_json((out/'current.json').read_bytes())
        store=Store(out/'course.sqlite3',read_only=True)
        result=CourseQueryService(store).search_evidence(scope,'2025 Q3(b)(ii) 答案')
        assert result.records and result.sufficiency=='insufficient'


def test_qualified_parent_retains_both_section_and_letter(tmp_path):
    tools,cid=course(tmp_path,paper='Q3(a)(b) Shared.\ni) One.\nii) Two.',
        solution='Q3(a)(b)(ii) Correct.\nQ3(b)(ii) Wrong.')
    assert 'Correct.' in str(ask(tools,cid,'2025 Q3(a)(b)(ii) 答案')['records'])
    assert not ask(tools,cid,'2025 Q3(b)(ii) 答案')['records']
