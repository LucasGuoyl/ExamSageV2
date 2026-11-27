"""Answer paragraphs link only to authorized, attributable original pages."""
from contextlib import closing
from io import BytesIO
import json
from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from examsage.chat_service import CourseTools
from examsage.student_import import import_selection
from examsage.student_workspace import Principal, StudentWorkspace
from examsage.study_host import Studio
from examsage.study_window import StudyDesk


@pytest.fixture
def space(tmp_path):
    workspace = StudentWorkspace(tmp_path, Principal('learner', frozenset()))
    materials = [
        ('lecture.txt', 'lecture', None, 'An air source heat pump uses electrical work.\fOther units.'),
        ('exam.txt', 'exam', 2024, '1. Consider two large buildings.\na) Calculate the air source heat pump load.\nb) Explain the tariff.\n2. Estimate the air source heat pump efficiency.'),
        ('practice.txt', 'mock_exam', 2025, '1. Calculate the air source heat pump load.'),
        ('other.txt', 'exam', 2023, '1. Consider two large buildings and calculate electrical work.'),
    ]
    result = import_selection(workspace.imports, 'Energy', 'Engineering',
        [(n, BytesIO(t.encode())) for n, _, _, t in materials],
        materials=[{'filename':n,'kind':role,'exam_year':year} for n,role,year,_ in materials])
    with closing(StudyDesk(workspace)) as desk:
        desk.select('upload-'+result['id'])
        desk.session_id = desk.runner.store.create_session(desk._current())['id']
        studio = Studio(desk)
        yield studio


def ask(studio, action, **fields):
    desk = studio.desk
    return studio.request(dict(action=action, course_id=desk.course_id, session_id=desk.session_id,
                               revision=studio.revision, **fields))


def save(studio, *, question=False, restricted=False):
    desk = studio.desk
    scope = desk._current()
    tools = CourseTools(desk.store, scope, course_id=desk.course_id)
    if question:
        path = question if isinstance(question,str) else 'Q1(a)'
        response = tools.call('search_evidence', {'query':f'2024 {path} question only'})
        assert response['records']
    else:
        doc = next(d for d in desk.store.manifest(scope).documents if PurePosixPath(d.relative_path).name=='lecture.txt')
        tools.call('get_source_page', {'document_id':doc.id,'page':1})
    evidence = list(tools.evidence.values())
    paragraphs = [{'kind':'source','text':'The air source heat pump is the device.', 'citations':[evidence[0]['id']]},
                  {'kind':'assumption','text':'An unrelated assumption.', 'citations':[]}]
    answer = {'text':'Explanation', 'paragraphs':paragraphs,'evidence':evidence}
    if restricted:
        answer['selected_paper'] = {'selection':{'paper_id':'other'}}
    chats = desk.runner.store
    rid = chats.begin_run(scope, desk.session_id, 'How?', uuid4().hex)['id']
    assert chats.finish_run(scope, rid, answer)
    return rid


@pytest.mark.parametrize('question', [False, True])
def test_paragraph_links_cited_and_related_question_or_lecture(space, question):
    rid = save(space, question=question)
    def lookup(action, index=0, **args):
        return ask(space, action, run_id=rid, paragraph_index=index, **args)
    items = lookup('paragraph_sources')['items']
    assert {i['filename'] for i in items} == {'lecture.txt','exam.txt'}
    exam = next(i for i in items if i['kind']=='exam')
    assert (exam['question'], exam['exam_year'], exam['page']) == ('Q1(a)',2024,1)
    assert (exam['relationship']=='cited') == question
    assert 'air source heat pump' in exam['quote']
    assert 'tariff' not in exam['quote']
    assert lookup('linked_page',key=exam['key'])['highlight']==exam['quote']
    assert lookup('paragraph_sources',1)['items']==[]
    for index,key in [(1,exam['key']), (0,'unbound')]:
        with pytest.raises(ValueError):
            lookup('linked_page',index,key=key)
    with pytest.raises(ValueError):
        lookup('paragraph_sources',-1)
    space.desk.session_id = space.desk.runner.store.create_session(space.desk._current())['id']
    with pytest.raises(ValueError):
        lookup('paragraph_sources')


def test_selected_paper_answer_does_not_expand_reading_scope(space):
    rid=save(space,restricted=True)
    items=ask(space,'paragraph_sources',run_id=rid,paragraph_index=0)['items']
    assert items and all(i['relationship']=='cited' for i in items)


def test_distinct_questions_on_one_page_both_link_to_their_own_passage(space):
    rid = save(space)
    items = ask(space,'paragraph_sources',run_id=rid,paragraph_index=0)['items']
    related = {i['question']:i for i in items if i['relationship']=='related'}
    assert set(related) == {'Q1(a)','Q2'}
    assert 'load' in related['Q1(a)']['quote']
    assert 'efficiency' in related['Q2']['quote']
    assert related['Q2']['key'] != related['Q1(a)']['key']


def test_answer_overview_uses_only_target_subquestions_own_text(space,monkeypatch):
    from examsage import study_links
    rid=save(space,question='Q1(b)')
    monkeypatch.setattr(study_links,'_related',lambda *a:pytest.fail('overview searched for extra sources'))
    paragraphs=ask(space,'answer_sources',run_id=rid)['paragraphs']
    assert [p['paragraph_index'] for p in paragraphs]==[0,1] and paragraphs[1]['items']==[]
    (item,)=paragraphs[0]['items']
    assert item['quote']=='b) Explain the tariff.' and item['question']=='Q1(b)'
    assert item['relationship']=='cited'


def test_context_page_without_verified_leaf_does_not_claim_question_number(space,monkeypatch):
    from examsage import study_links
    rid=save(space,question='Q1(a)')
    # The parent page is saved as supporting context but the locator found no leaf there.
    monkeypatch.setattr(study_links, 'own_question_excerpts', lambda *args: [])
    item,=ask(space,'answer_sources',run_id=rid)['paragraphs'][0]['items']
    assert item['question'] is None and item['quote']=='' and 'Q1(a)' in item['basis']


def test_existing_older_ui_is_reported_without_opening_it(tmp_path, monkeypatch):
    from examsage import study_host
    from examsage.chat_store import StudentServerBusy
    marker = tmp_path/'instance.json'
    instance='b'*32
    marker.write_text(json.dumps({'port':45123,'capability':'a'*43,'instance':instance}))
    class Connection:
        def request(self, method, path):
            assert (method,path)==('GET','/instance')
        def getresponse(self):
            class Response:
                status=200
                def read(self, size):
                    return json.dumps({'instance':instance}).encode()
            return Response()
        def close(self):
            pass
    monkeypatch.setattr(study_host,'HTTPConnection',lambda *args,**kw:Connection())
    opened=[]
    with pytest.raises(StudentServerBusy,match='旧版'):
        study_host._reopen(marker,opened.append)
    with pytest.raises(StudentServerBusy,match='Start ExamSage.bat'):
        study_host._reopen(marker,opened.append,language='en')
    assert not opened and marker.exists()

def test_table_preview_matches_values_in_one_unambiguous_literal_row():
    from examsage.study_links import _table_row
    raw = 'Well distance head\n1 20 150\n2 20,000 140\n3 30,000 135\n'
    assert _table_row(raw, 'Well 3 is 30000 m away and its head is 135 m.') == '3 30,000 135'
    assert not _table_row(raw, 'Distance 30,000 m. The head is not given.')
    assert not _table_row(raw, 'Distance 20,000 m, head 135 m')
    assert not _table_row(raw + '4 30,000 135\n', '30,000 m and 135 m')
    assert not _table_row(raw, 'Distance 30,000 m, head −135 m')
