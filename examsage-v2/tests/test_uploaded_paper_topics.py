import io

import pytest

from examsage.exam_outlook import evaluate_outlook
from examsage.student_workspace import StudentWorkspace, student_tools
from examsage.plugin_tools import Principal
from examsage.web_intake import import_selection


def upload(space, rows):
    files = [(name, io.BytesIO(text.encode())) for name, kind, year, text in rows]
    labels = [dict(filename=name, kind=kind, exam_year=year) for name, kind, year, text in rows]
    return import_selection(space.imports, 'Energy', 'Physics', files, materials=labels)


def test_declared_roles_same_names_and_only_paper_headings_feed_the_outlook(tmp_path):
    space = StudentWorkspace(tmp_path, Principal('student-a', frozenset()))
    other = student_tools(None, StudentWorkspace(tmp_path, Principal('student-b', frozenset())))
    result = upload(space, [
        ('notes.txt','lecture',None,'Question 1 on NotesOnly'),
        ('exam.txt','exam',2023,'\fQuestion 1 on Heat\nCalculate the load.\nQuestion 2 on Flux'),
        ('exam.txt','exam',2024,'3. Question on Heat\nCompare the factors.\f第4题【主题：光伏】\n估计其输出。'),
        ('solutions.txt','exam_solution',2023,'Question 1 on SolutionOnly'),
        ('mock.txt','mock_exam',2024,'Question 1 on MockOnly'),
        ('future.txt','exam',2025,'Question 1 on HeldOut'),
        ('unknown.txt','unknown',None,'Question 1 on UnknownOnly')])
    cid = 'upload-' + result['id']
    tools = student_tools(None,space)
    binding,store = tools._course(cid)
    docs = store.manifest(binding.scope).documents
    assert [(d.kind,d.exam_year) for d in docs] == [('lecture',None),('exam',2023),('exam',2024),
              ('exam_solution',2023),('mock_exam',2024),('exam',2025),('unknown',None)]
    assert all(d.available_from is None for d in docs)
    args=dict(course_id=cid,target_year=2025,top_k=5,history_mode='paper_year')
    report=tools.call('get_exam_outlook',args)
    assert report['status']=='ranked' and report['training_years']==[2023,2024]
    assert {r['topic'] for r in report['ranking']}=={'Heat','Flux','光伏'}
    assert report['ranking'][0]['years']==[2023,2024]
    for row in report['ranking']:
        for ref in row['sources']:
            assert ref['label_origin']=='paper_heading'
            page=tools.call('get_source_page',dict(course_id=cid,document_id=ref['document_id'],page=ref['page']))
            assert ref['source_id']==page['sources'][0]['source_id']
            assert row['topic'] in page['records'][0]['text']
    assert tools.call('get_exam_outlook',{**args,'history_mode':'strict'})['status']=='insufficient'
    assert evaluate_outlook(store,binding.scope,cid,2025,5,'paper_year')['metrics'] is None
    assert not store.list_records(binding.scope,'answer') and not store.list_records(binding.scope,'question')
    with pytest.raises(ValueError):
        other.call('get_exam_outlook',args)


def test_incomplete_or_conflicting_headings_do_not_inflate_frequency(tmp_path):
    space=StudentWorkspace(tmp_path,Principal('s',frozenset()))
    result=upload(space,[
        ('year.txt','exam',2023,'Question 1 on Heat\nQ2(a) Answer text\fQuestion 1 on Heat\nQuestion 2 on Solar\fQuestion 2 on Archive'),
        ('copy.txt','exam',2023,'Question 1 on Heat\nQ2(a) Answer text\fQuestion 1 on Heat\nQuestion 2 on Solar\fQuestion 2 on Archive'),
        ('unparsed.txt','exam',2024,'Discuss wind energy.\n第3题：请证明上述结果。')])
    report=student_tools(None,space).call('get_exam_outlook',dict(course_id='upload-'+result['id'],
        target_year=2025,top_k=4,history_mode='paper_year'))
    assert [(r['topic'],r['question_count']) for r in report['ranking']]==[('Heat',1)]
    assert report['coverage']['exam_papers']==2
    assert report['coverage']['papers_without_parsed_questions']==1
    assert any('题头' in x for x in report['limitations'])


@pytest.mark.parametrize('labels', [[], [{'filename':'other.txt','kind':'exam','exam_year':2024}],
    [{'filename':'a.txt','kind':'lecture','exam_year':2024}],
    [{'filename':'a.txt','kind':'exam','exam_year':True}],
    [{'filename':'a.txt','kind':'typo','exam_year':None}],
    [{'filename':'a.txt','kind':'exam','exam_year':2024,'available_from':'2010-01-01'}]])
def test_invalid_declarations_are_rejected_before_publish(tmp_path, labels):
    with pytest.raises(ValueError):
        import_selection(tmp_path,'A','B',[('a.txt',io.BytesIO(b'hello'))],materials=labels)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('role,year',[('exam',2025),('mock_exam',2024),('exam_solution',2024)])
def test_distinct_roles_or_sittings_for_identical_paper_require_correction(tmp_path,role,year):
    space=StudentWorkspace(tmp_path,Principal('student',frozenset()))
    content='Question 1 on Revisions'
    with pytest.raises(ValueError,match='相同'):
        upload(space,[('卷1.txt','exam',2024,content),('卷2.txt',role,year,content)])
    assert not space.private_catalog()

def test_layout_headings_must_match_original_page_and_exclude_running_question_text():
    from examsage.exam_outlook import paper_headings
    raw = "Answer ALL Questions   1. Question on Energy Transfer   a) Calculate the load."
    layout = "Answer ALL Questions\n1.   Question on Energy Transfer\na) Calculate the load.\n2. Question on Unrelated"
    assert paper_headings(raw, layout=layout)==[{'number':'1','topic':'Energy Transfer','heading':'1. Question on Energy Transfer'}]
    assert paper_headings("1. Question on Energy Transfer  a) Calculate the load.")==[]

@pytest.mark.parametrize('line', ['1. Question on Heat. Calculate the heat demand.',
    '1. Question on Heat  Calculate the heat demand.',
    'Question 1 on solar panels? Explain how output changes.'])
def test_running_prompt_is_not_an_exam_topic(line):
    from examsage.exam_outlook import paper_headings
    assert paper_headings(line)==[]


def test_trailing_mark_allocation_is_not_part_of_the_topic():
    from examsage.exam_outlook import paper_headings
    refs=paper_headings('1. Question on Migration    (4 marks)')
    assert [r['topic'] for r in refs]==['Migration']


def test_tied_headings_keep_the_same_rank_and_spelling_when_document_ids_change(tmp_path):
    from hashlib import sha256

    from examsage.course_pack import CoursePack, import_pack
    from examsage.course_profile import CourseProfile
    from examsage.domain import Document, Manifest
    from examsage.exam_outlook import exam_outlook
    from examsage.storage import Store

    profile=CourseProfile(course_id='physics',curriculum_system='school',institution=None,stage='school',
        language='en',syllabus_version='sample',disciplines=['physics'],material_status='demonstration')
    results=[]
    for run,(ids,labels) in enumerate([(('a','z'),('alpha','Alpha')), (('z','a'),('alpha','Alpha')),
                                      (('a','z'),('alpha','alpha'))]):
        docs=[]
        for doc_id,year,label in zip(ids,[2023,2024],labels):
            text=f'Paper {year}\nQuestion 1 on {label}\nQuestion 2 on Beta'
            name=f'{year}.txt'
            (tmp_path/name).write_text(text,encoding='utf8')
            docs.append(Document(id=doc_id,kind='exam',exam_year=year,relative_path=name,pages=1,
                sha256=sha256((tmp_path/name).read_bytes()).hexdigest()))
        folder=tmp_path/f'pack-{run}'
        pack=CoursePack(workspace='w',profile=profile,manifest=Manifest(course_key='physics',course_name='P',
            documents=docs),records=[],relations=[])
        scope=import_pack(pack,tmp_path,folder).scope
        report=exam_outlook(Store(folder/'course.sqlite3',read_only=True),scope,'physics',2025,1,'paper_year')
        results.append(report['ranking'][0]['topic'])
    assert results==['Alpha','Alpha','alpha']
