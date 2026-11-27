import pytest
from test_core import example

def test_natural_chinese_query_indexes_audited_derivation_content(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope
    store,m,r=example(tmp_path);r.kind='concept';r.title='Plate';r.text='跨页导读'
    r.details={'derivation':{'steps':[{'title':'弯矩','text':'悬臂的左端固定，右端受到竖向力。'}]}}
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    assert CourseQueryService(store).search_evidence(scope,'请解释悬臂左端固定时的竖向力').records[0].id==r.id


def test_keyword_search_scope_and_fts_input(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    service=CourseQueryService(store)
    assert service.search_evidence(scope,'Darcy').records[0].id=='b'
    assert service.search_evidence(scope,'" OR Darcy* --').records
    assert not service.search_evidence(scope.model_copy(update={'allowed_sources':[]}), 'Darcy').records
    assert service.search_evidence(scope,'不存在的核聚变问题').limitations


def test_chinese_aliases_and_parent_context(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope, Record
    store,m,r=example(tmp_path)
    r.kind='concept';r.aliases=['孔隙度'];r.title='Porosity';r.text='Porosity is pore volume fraction'
    parent=Record(id='q',kind='question',title='2024 Q1',text='Shared table',refs=r.refs,details={'exam_year':2024,'number':'1','answer_status':'not_provided'})
    child=Record(id='qi',kind='question',title='2024 Q1(i)',text='Find pore volume fraction',refs=r.refs,parent_id='q')
    sid=store.publish('w',m,[r,parent,child],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    service=CourseQueryService(store)
    assert any(x.id=='b' for x in service.search_evidence(scope,'孔隙度是什么意思').records)
    bundle=service.get_question(scope,'qi')
    assert {x.id for x in bundle.records}=={'q','qi'}
    assert service.search_evidence(scope,'2024 官方答案').sufficiency=='insufficient'


def test_relations_do_not_leak_filtered_sources(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Document,Record,Relation,SourceRef,Scope
    store,m,r=example(tmp_path)
    m.documents.append(Document(id='private',relative_path='b.pdf',sha256='b'*64,pages=1,kind='exam',exam_year=2024))
    q=Record(id='q',kind='question',title='Private question',text='Private',refs=[SourceRef(document_id='private',page=1)])
    edge=Relation(id='e',source='q',target='b',kind='assesses',refs=r.refs+q.refs)
    sid=store.publish('w',m,[r,q],[edge],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    assert not CourseQueryService(store).get_related_questions(scope,'b').records


def test_budget_reports_omission_instead_of_cutting_formula(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope
    store,m,r=example(tmp_path)
    r.text='Darcy '+ 'condition '*1000
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    b=CourseQueryService(store).search_evidence(scope,'Darcy',max_chars=200)
    assert not b.records and any('budget' in x for x in b.limitations)


def test_semantic_retrieval_uses_only_matching_route_and_scope(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope
    from examsage.embeddings import VectorIndex
    store,m,r=example(tmp_path)
    sid=store.publish('w',m,[r],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    index=VectorIndex(tmp_path/'vectors.sqlite3','test-model')
    index.replace(sid, {'b':[1.0,0.0]})
    service=CourseQueryService(store,index,lambda query:[1.0,0.0])
    assert service.search_evidence(scope,'unrelated synonym').mode=='hybrid'
    assert service.search_evidence(scope,'unrelated synonym').records[0].id=='b'
    assert not service.search_evidence(scope.model_copy(update={'allowed_sources':[]}), 'unrelated synonym').records
    other=VectorIndex(tmp_path/'vectors.sqlite3','different-model')
    assert not other.rank(sid,[1,0],{'b'})


def test_exact_question_search_brings_linked_formula_even_with_low_lexical_overlap(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope,Record,Relation
    store,m,r=example(tmp_path)
    q=Record(id='q',kind='question',title='2024 Q1',text='Find groundwater time',refs=r.refs,details={'exam_year':2024,'number':'1'})
    f=Record(id='f',kind='formula',title='Unusually named law',text='q = Kh dh/dx',refs=r.refs)
    edge=Relation(id='e',source='q',target='f',kind='uses_formula',refs=r.refs)
    sid=store.publish('w',m,[q,f],[edge],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    result=CourseQueryService(store).search_evidence(scope,'2024 Q1')
    assert {x.id for x in result.records}=={'q','f'}


def test_related_subquestion_includes_shared_parent(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope,Record,Relation
    store,m,r=example(tmp_path)
    r.kind='concept'
    parent=Record(id='q',kind='question',title='Q1',text='Shared measurement table',refs=r.refs)
    child=Record(id='qi',kind='question',title='Q1(i)',text='Use the table',refs=r.refs,parent_id='q')
    edge=Relation(id='e',source='qi',target=r.id,kind='assesses',refs=r.refs)
    sid=store.publish('w',m,[r,parent,child],[edge],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    assert {x.id for x in CourseQueryService(store).get_related_questions(scope,r.id).records}=={'q','qi'}


def test_search_defers_duplicate_page_text_and_prioritizes_linked_formula(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope,Record,Relation
    store,m,r=example(tmp_path)
    q=Record(id='q',kind='question',title='2024 Q1',text='Shared table',refs=r.refs,details={'exam_year':2024,'number':'1'})
    children=[Record(id=f'q{i}',kind='question',title=f'2024 Q1({i})',text='Use table',refs=r.refs,parent_id='q',details=q.details) for i in range(10)]
    f=Record(id='f',kind='formula',title='Decay formula',text='N = N0 exp(-lambda t)',refs=r.refs,
             details={'source_excerpts':[{'page':1,'text':'Original entire page '*5000}]})
    edge=Relation(id='e',source='q',target='f',kind='uses_formula',refs=r.refs)
    sid=store.publish('w',m,[q,f,*children],[edge],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    result=CourseQueryService(store).search_evidence(scope,'2024 Q1',max_chars=4000)
    formula=next(x for x in result.records if x.id=='f')
    assert formula.text==f.text and formula.refs==f.refs
    assert 'source_excerpts' not in formula.details
    assert formula.details['source_text_deferred'] is True
    assert store.get(scope,'f').details==f.details
    assert sum(len(x.model_dump_json()) for x in result.records)<=4000


@pytest.mark.parametrize('query',['2023 Q1 groundwater','2023年Q1地下水年龄','2023年第1题','2023年真题试卷','Question 1 in 2023','比较 2023 Q1 和 2024 Q1'])
def test_missing_exam_year_never_silently_falls_back_to_other_years(tmp_path,query):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope,Record
    store,m,r=example(tmp_path)
    m.documents[0].kind='exam';m.documents[0].exam_year=2024
    q=Record(id='q',kind='question',title='2024 Q1 groundwater',text='groundwater age',refs=r.refs,details={'exam_year':2024,'number':'1'})
    sid=store.publish('w',m,[q],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    result=CourseQueryService(store).search_evidence(scope,query)
    assert result.sufficiency=='insufficient' and not result.records
    assert any('year' in x for x in result.limitations)


@pytest.mark.parametrize('query',['2024 Q99 groundwater','2024 Q100 groundwater'])
def test_missing_question_number_does_not_fall_back_or_match_number_prefix(tmp_path,query):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope,Record
    store,m,r=example(tmp_path)
    m.documents[0].kind='exam';m.documents[0].exam_year=2024
    q=Record(id='q10',kind='question',title='2024 Q10 groundwater',text='groundwater',refs=r.refs,details={'exam_year':2024,'number':'10'})
    sid=store.publish('w',m,[q],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    result=CourseQueryService(store).search_evidence(scope,query)
    assert result.sufficiency=='insufficient' and not result.records
    assert any('question' in x.lower() for x in result.limitations)


def test_exact_subquestion_preserves_raw_transcription_and_parent(tmp_path):
    from examsage.search import CourseQueryService
    from examsage.domain import Scope,Record
    store,m,r=example(tmp_path)
    q=Record(id='q',kind='question',title='2024 Q1',text='Shared context',refs=r.refs,details={'exam_year':2024,'number':'1','part':None})
    children=[Record(id='q.'+part,kind='question',title='2024 Q1('+part+')',text='Checked equation',refs=r.refs,parent_id='q',details={**q.details,'part':part,'raw_text':'Original uncorrected equation'}) for part in ['i','ii']]
    sid=store.publish('w',m,[q,*children],[],{})
    scope=Scope(workspace='w',course='c',snapshot=sid,allowed_sources=['doc'])
    service=CourseQueryService(store)
    result=service.search_evidence(scope,'2024 Q1(ii)')
    assert result.records[0].id=='q.ii'
    assert {x.id for x in result.records}=={'q','q.ii'}
    assert result.records[0].details['raw_text']=='Original uncorrected equation'
    assert not service.search_evidence(scope,'2024 Q1(iv)').records
