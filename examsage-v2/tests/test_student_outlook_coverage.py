"""Forward recommendations must account for the questions that lack a printed label."""
import json
from io import BytesIO
from pathlib import Path

import pytest

from examsage.exam_outlook import paper_headings
from examsage.plugin_tools import Principal
from examsage.student_import import import_selection
from examsage.student_workspace import StudentWorkspace, student_tools


def test_forward_coverage_and_examples_share_the_authorized_history(tmp_path):
    workspace = StudentWorkspace(tmp_path,Principal('student-a',frozenset()))
    rows = [
        ('2022.txt','exam',2022,'Question 1 on Source criticism\nDiscuss the account.\fQuestion 2\nCompare the witnesses.'),
        ('2023.txt','exam',2023,'Question 1 — Topic: Source criticism\nAnalyse the documents.\fQuestion 2\nCompare two accounts.'),
        ('2024.txt','exam',2024,'第1题 主题：史料批判\n比较两份史料。\f第2题\n分析文献。'),
        ('2025.txt','exam',2025,'Question 1 — Topic: Future-only label\nDiscuss the peace treaty.'),
        ('solutions.txt','exam_solution',2023,'Question 1 — Topic: Solution-only label'),
        ('practice.txt','mock_exam',2023,'Question 1 — Topic: Mock-only label'),
        ('lecture.md','lecture',None,'Question 1 — Topic: Notes-only label')]
    receipt = import_selection(workspace.imports,'History','History',
            [(n,BytesIO(body.encode())) for n,_,_,body in rows],
            materials=[{'filename':n,'kind':kind,'exam_year':year} for n,kind,year,_ in rows],
            record_receipt=True)
    api = student_tools(None,workspace)
    cid = 'upload-'+receipt['id']
    args = dict(course_id=cid,target_year=2025,top_k=6,history_mode='paper_year')
    forecast = api.call('get_exam_outlook',args)
    assert forecast['training_years'] == [2022,2023,2024]
    coverage = forecast['coverage']
    assert (coverage['parent_questions'],coverage['tagged_questions']) == (6,3)
    assert coverage['papers_without_located_questions'] == 0
    assert [(r['topic'],r['years']) for r in forecast['ranking']] == [
        ('Source criticism',[2022,2023]),('史料批判',[2024])]
    assert len(forecast['unlabelled_examples']) == 3
    for ref in forecast['unlabelled_examples']:
        assert ref['question_number']=='2' and ref['page']==2
    for ref in forecast['unlabelled_examples']+[s for row in forecast['ranking'] for s in row['sources']]:
        page = api.call('get_source_page',dict(course_id=cid,document_id=ref['document_id'],page=ref['page']))
        assert ref['source_id']==page['sources'][0]['source_id']
        assert ref['year'] < args['target_year']
    from examsage.api import create_app
    data = workspace.open_import(receipt['id'])
    app = create_app(data,course_id=cid,private_preview_root=tmp_path/'preview')
    open_page = next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/page/{doc_id}/{number}')
    for ref in forecast['unlabelled_examples']:
        opened = open_page(ref['document_id'],ref['page'],source_id=ref['source_id'])
        assert opened['source_id']==ref['source_id'] and opened['bundle'].records[0].refs[0].page==2
    assert 'Future-only' not in json.dumps(forecast) and 'target_questions' not in forecast
    strict = api.call('get_exam_outlook',{**args,'history_mode':'strict'})
    assert strict['status']=='insufficient' and strict['unlabelled_examples']==[]
    with pytest.raises(ValueError):
        student_tools(None,StudentWorkspace(tmp_path,Principal('student-b',frozenset()))).call('get_exam_outlook',args)


@pytest.mark.parametrize(('line','expected'), [
    ('Question 1 — Topic: Urban migration (10 marks)', 'Urban migration'),
    ('Q2 – Topic: Proof by induction','Proof by induction'),
    ('第 3 题 主题：史料批判','史料批判'),
    ('第1题 主题：史料批判（10分）','史料批判'),
    ('第1题 主题：史料批判（20分）','史料批判'),
    ('第1题 主题：史料批判  请根据材料回答问题',None),
    ('第1题 主题：史料批判及请愿运动','史料批判及请愿运动'),
    ('Question 1: Compare sources A and B.',None),
    ('Q2(a) Topic: A subquestion label',None),
    ('Question 1 — Topic: Migration. Explain the graph.',None),
    ('第1题 主题：史料批判。请评价作者的论点。',None)])
def test_only_printed_whole_question_labels_are_added(line,expected):
    headings=paper_headings(line)
    assert [h['topic'] for h in headings] == ([] if expected is None else [expected])

@pytest.mark.parametrize('version',['0.6.3','0.6.4'])
def test_recipient_manifest_and_live_server_report_updated_version(tmp_path,version):
    import os
    import sys
    from examsage.plugin_package import build_package
    from test_student_distribution import run
    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TMP','TEMP') if k in os.environ}
    env['LOCALAPPDATA']=str(tmp_path/'student')
    if version=='0.6.3':
        from zipfile import ZipFile
        folder=tmp_path/'old-release'
        archive=Path(__file__).resolve().parents[1]/'releases/windows-student-pilot-2/ExamSage-Student-Windows.zip'
        with ZipFile(archive) as z:
            z.extractall(folder)
        run([sys._base_executable,'-I','-B',folder/'kit.py','prepare'],env)
        output=folder/'marketplace/examsage-student-courses'
    else:
        output=tmp_path/'student-plugin'
        build_package(output,None,[],Path(sys._base_executable),recipient=True,plugin_name='examsage-student-courses')
    for file in ['plugin.json','.codex-plugin/plugin.json']:
        assert json.loads((output/file).read_bytes())['version']==version
    request = {'jsonrpc':'2.0','method':'initialize','id':1,'params':{'clientInfo':{'name':'qa','version':'1'},
               'capabilities':{},'protocolVersion':'2025-11-25'}}
    srv, = json.loads((output/'.mcp.json').read_bytes())['mcpServers'].values()
    command = [srv['command'], *(a.replace('${PLUGIN_ROOT}',str(output)) for a in srv['args'])]
    reply = run(command,env,stdin=json.dumps(request).encode()+bytes([10]))
    assert json.loads(reply.stdout)['result']['serverInfo']['version']==version

def test_picker_records_mock_sitting_without_using_it_as_exam_history(tmp_path,monkeypatch):
    from importlib.util import module_from_spec, spec_from_file_location
    from unittest.mock import Mock
    from tkinter import filedialog, messagebox, simpledialog
    import tkinter

    entry = Path(__file__).resolve().parents[1]/'student_kit/kit.py'
    spec = spec_from_file_location('student_kit_picker', entry)
    kit = module_from_spec(spec)
    spec.loader.exec_module(kit)
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    paper = tmp_path/'practice.txt'
    paper.write_text('Question 1 on Practice-only theme',encoding='utf8')
    answers = iter(['History','History','模拟卷','2023'])
    monkeypatch.setattr(tkinter,'Tk',Mock())
    monkeypatch.setattr(filedialog,'askopenfilenames',lambda **_: [str(paper)])
    monkeypatch.setattr(simpledialog,'askstring',lambda *a,**k:next(answers))
    monkeypatch.setattr(messagebox,'showinfo',Mock())
    kit.picker()
    workspace = kit.local_workspace(kit.recipient_workspace_root(),[])
    row, = workspace.private_catalog()
    cid=row['slug']
    data=workspace.open_import(cid.removeprefix('upload-'))
    doc,=json.loads((data/'manifest.json').read_bytes())['documents']
    assert (doc['kind'],doc['exam_year'])==('mock_exam',2023)
    outlook=student_tools(None,workspace).call('get_exam_outlook',dict(course_id=cid,target_year=2025,
                                                                      history_mode='paper_year',top_k=3))
    assert outlook['ranking']==[] and outlook['training_years']==[]

def test_previous_heading_index_with_different_mark_allocations_is_read_consistently(tmp_path):
    # Use the actual released parser so this fixture retains its shipped raw pages,
    # title strings, scopes and evidence IDs.
    from zipfile import ZipFile
    from test_student_distribution import PYTHON, run
    from examsage.source_paths import source_path
    import os

    archive = Path(__file__).resolve().parents[1]/'releases/windows-student-pilot-1/ExamSage-Student-Windows.zip'
    old = tmp_path/'v1'
    with ZipFile(archive) as z:
        z.extractall(old)
    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TMP','TEMP') if k in os.environ}
    env['LOCALAPPDATA'] = str(tmp_path/'profile')
    source = r"""from pathlib import Path
import sys,json
sys.path.insert(0, str(Path(sys.argv[1])/'src'))
from examsage.student_import import import_selection
from examsage.student_workspace import local_workspace, recipient_workspace_root
from io import BytesIO
root=local_workspace(recipient_workspace_root(),[]).imports
rows=[(f'{y}.txt',BytesIO(f'第1题【主题：文献辨伪（{points}分）】\n比较资料。\f第2题【主题：材料分析  请根据史料回答问题】\n列出依据。'.encode())) for y,points in [(2022,8),(2023,12)]]
labels=[dict(filename=n,kind='exam',exam_year=int(n[:4])) for n,_ in rows]
print(json.dumps(import_selection(root,'Old','History',rows,materials=labels,record_receipt=True)))
"""
    result = run([PYTHON,'-I','-B','-X','utf8','-c',source,old],env)
    course = 'upload-'+json.loads(result.stdout)['id']
    from examsage.student_workspace import local_workspace
    workspace=local_workspace(source_path(Path(env['LOCALAPPDATA'])/'ExamSage'/'student-workspaces'),[])
    api=student_tools(None,workspace)
    binding,store=api._course(course)
    assert store.metadata(binding.scope)['paper_heading_index']=='original-headings-v1'
    report=api.call('get_exam_outlook',dict(course_id=course,target_year=2025,top_k=3,history_mode='paper_year'))
    assert [(r['topic'],r['years']) for r in report['ranking']]==[('文献辨伪',[2022,2023])]
    assert report['coverage']['parent_questions']==4 and report['coverage']['tagged_questions']==2
    for ref in report['ranking'][0]['sources']:
        page=api.call('get_source_page',dict(course_id=course,document_id=ref['document_id'],page=ref['page']))
        assert ref['source_id']==page['sources'][0]['source_id'] and ref['heading'] in page['records'][0]['text']
