import io
from datetime import date

from examsage.chat_service import CourseTools
from examsage.plugin_tools import Principal
from examsage.student_workspace import StudentWorkspace, student_tools
from examsage.web_intake import import_selection


def imported(root, kinds=None, extra=()):
    ws = StudentWorkspace(root,Principal('a',frozenset()))
    files = [('one.txt','Question 2 Conditions: initial area 18.\na) Find the rate.\nb) Next task.'),
             ('two.txt','Q2(a) Given the common condition, rate = 6.\nQ2(b) Other result = 81.'),*extra]
    labels = None if kinds is None else [
        dict(filename=name,kind=kind,exam_year=year) for (name,_),(kind,year) in zip(files,kinds)]
    receipt = import_selection(ws.imports,'Existing private course','Physics',
        [(name,io.BytesIO(body.encode())) for name,body in files],materials=labels)
    tools = student_tools(None,ws)
    cid = 'upload-'+receipt['id']
    binding, store = tools._course(cid)
    docs = {d.relative_path.split('/')[-1]:d.id for d in store.manifest(binding.scope).documents}
    return tools,cid,docs,binding,store


def search(tools,cid,query,selection=None):
    args = dict(course_id=cid,query=query)
    if selection is not None:
        args['selection'] = selection
    return tools.call('search_evidence',args)


def test_student_selected_untyped_originals_and_followup(tmp_path):
    tools,cid,docs,bind,store = imported(tmp_path)
    s = dict(paper_id=docs['one.txt'],solution_id=docs['two.txt'],exam_year=2025)
    assert not search(tools,cid,'2025 Q2(a) 答案')['records']
    result = search(tools,cid,'Q2(a) 答案',s)
    assert result['sufficiency']=='unassessed' and result['relations']==[]
    q,a = result['records']
    assert 'area 18' in q['text'] and 'rate = 6' in a['text'] and '81' not in a['text']
    for r in (q,a):
        assert r['details']['selection_basis']=='request_only'
        assert r['details']['source_kind']=='unknown' and r['details']['exam_year'] is None
        assert r['details']['requested_exam_year']==2025
        ref=r['refs'][0]
        page=tools.call('get_source_page',dict(course_id=cid,document_id=ref['document_id'],page=ref['page']))
        assert page['sources'][0]['source_id']==r['source_id']
    assert '81' in search(tools,cid,'Q2(b) 答案',s)['records'][-1]['text']
    assert not search(tools,cid,'2025 Q2(a) 答案')['records']
    assert all(d.kind=='unknown' and d.exam_year is None for d in store.manifest(bind.scope).documents)


def test_selection_never_falls_back_to_unselected_sources(tmp_path):
    tools,cid,docs,bind,store = imported(tmp_path,kinds=[('exam',2025),('exam_solution',2025)])
    paper,solution=docs['one.txt'],docs['two.txt']
    s=dict(paper_id=paper,exam_year=2025)
    partial=search(tools,cid,'Q2(a) 答案',s)
    assert partial['sufficiency']=='insufficient' and [r['details']['locator_role'] for r in partial['records']]==['question']
    p=search(tools,cid,'Q2(a) 不要答案',{**s,'solution_id':solution})
    assert p['sufficiency']=='unassessed' and all(r['details']['locator_role']=='question' for r in p['records'])
    for bad in [dict(paper_id=solution,solution_id=paper),dict(paper_id=paper,solution_id=paper),
                dict(paper_id='unavailable'),dict(exam_year=2024)]:
        r=search(tools,cid,'Q2(a) 答案',{**s,**bad})
        assert r['sufficiency']=='insufficient' and not r['records']
    for query in ['2024 Q2(a) 答案','2024/25 Q2(a) 答案','查找证据']:
        assert not search(tools,cid,query,s)['records']
    restricted=bind.scope.model_copy(update={'strict_history':True,'cutoff':date(2020,1,1)})
    from examsage.search import CourseQueryService
    assert not CourseQueryService(store).search_evidence(restricted,'Q2(a) 答案',selection=s).records


def test_web_chat_tool_accepts_explicit_selection_and_keeps_provenance(tmp_path):
    _,_,docs,bind,store=imported(tmp_path)
    tools=CourseTools(store,bind.scope)
    result=tools.call('search_evidence',{'query':'Q2(a) 答案','selection':{
        'paper_id':docs['one.txt'],'solution_id':docs['two.txt'],'exam_year':2025}})
    assert 'rate = 6' in str(result) and 'request_only' in str(result)


def test_chat_runner_pins_student_choice_and_rechecks_next_subquestion(tmp_path):
    import json
    from examsage.chat_runner import ChatRunner
    from test_chat_runner import wait_run
    from test_chat_service import answer
    _,cid,docs,bind,store=imported(tmp_path/'student')
    selection={'exam_year':2025,'paper_id':docs['one.txt'],'solution_id':docs['two.txt']}
    class Tutor:
        def generate(self, context, specs, tools, cancel, on_status, *, before_send):
            assert {s['name'] for s in specs}=={'search_evidence','calculate'}
            evidence=tools('search_evidence',{'query':'unrelated model suggestion'})
            return answer([evidence['records'][-1]['evidence_ids'][0]])
    runner=ChatRunner(tmp_path/'chat',runtime=Tutor())
    sid=runner.store.create_session(bind.scope)['id']
    for i,question in enumerate(['【选卷查题】'+json.dumps(selection)+'\nQ2(a) 答案','同一卷 Q2(b) 答案']):
        run=runner.submit(store,bind.scope,sid,question,str(i),course_id=cid)
        final=wait_run(runner,bind.scope,run['id'])
        assert final['status']=='completed',final['error']
        row=final['answer']['evidence'][0]
        assert ('rate = 6' if i==0 else '81') in row['text']
        assert final['answer']['selected_paper']['selection']==selection


def test_short_followup_replaces_only_the_roman_leaf_and_preserves_practice_mode():
    from examsage.chat_service import selected_paper_request
    from examsage.search import pilot_question,wants_answer
    s={'paper_id':'p','solution_id':'s','exam_year':2025}
    for previous_query,expected in [('Q3(b)(iv) 答案',True),('Q3(b)(iv) 只给题目',False)]:
        previous={'query':previous_query,'selection':s}
        r=selected_paper_request('那（v）呢？',previous)
        assert r and r['selection']==s and pilot_question(r['query'])==('3','b.v')
        assert wants_answer(r['query']) is expected
        assert selected_paper_request('换个话题，讲讲潮汐。',previous) is None
    assert selected_paper_request('那（v）呢？') is None


def test_numeric_conditions_do_not_change_the_selected_exam_year(tmp_path):
    tools,cid,docs,_,_=imported(tmp_path)
    s={'paper_id':docs['one.txt'],'solution_id':docs['two.txt'],'exam_year':2025}
    for query in ['Q2(a) 条件改为 2000 W 时，请复算答案','Q2(a) check it using 2100 kWh, explain the answer',
                  'Q2(a) 假设 x=2001.5 求答案']:
        assert search(tools,cid,query,s)['sufficiency']=='unassessed'
    for query in ['2024 Q2(a) 答案','Q2(a) on the 2024 paper answer','Q2(a)，按 2024 年原卷核对答案','Q2(a)，我要看 2024 年的答案','2024 年期末考试 Q2(a) 答案',
                  '2023/24 学年 Q2(a) 答案','Q2(a) 2024 答案']:
        assert not search(tools,cid,query,s)['records']


def test_model_cannot_select_unknown_documents_for_an_ordinary_message(tmp_path):
    from examsage.chat_runner import ChatRunner
    from test_chat_runner import wait_run
    from test_chat_service import answer
    _,cid,docs,bind,store=imported(tmp_path/'course')
    class Tutor:
        def generate(self, context, specs, tools, cancel, on_status, *, before_send):
            chosen=tools('search_evidence',{'query':'Q2(a) 答案','selection':{
                'paper_id':docs['one.txt'],'solution_id':docs['two.txt'],'exam_year':2025}})
            return answer([chosen['records'][-1]['evidence_ids'][0]])
    manager=ChatRunner(tmp_path/'chat',runtime=Tutor())
    sid=manager.store.create_session(bind.scope)['id']
    run=manager.submit(store,bind.scope,sid,'2025 Q2(a) 答案','one',course_id=cid)
    final=wait_run(manager,bind.scope,run['id'])
    assert final['status']=='failed' and final['error']['code']=='invalid_paper_selection'


def test_practice_and_missing_selected_answers_need_no_generation(tmp_path):
    import json
    from examsage.chat_runner import ChatRunner
    from test_chat_runner import wait_run
    _,cid,docs,bind,store=imported(tmp_path/'course')
    calls=[]
    class Tutor:
        def generate(self,*args,**kwargs):
            calls.append(True)
            raise AssertionError('no generated answer expected')
    manager=ChatRunner(tmp_path/'chat',runtime=Tutor())
    sid=manager.store.create_session(bind.scope)['id']
    selected={'paper_id':docs['one.txt'],'solution_id':docs['two.txt'],'exam_year':2025}
    for i,text in enumerate(['Q2(a) 只给题目','Q2(f) 答案']):
        run=manager.submit(store,bind.scope,sid,'【选卷查题】'+json.dumps(selected)+'\n'+text,str(i),course_id=cid)
        final=wait_run(manager,bind.scope,run['id'])
        assert final['status']=='completed' and not calls
        assert 'rate = 6' not in final['answer']['text']
        if i==0: assert 'area 18' in final['answer']['text']
        else: assert final['answer']['paragraphs'][-1]['kind']=='insufficient'
    assert not manager.connection['generation_verified']


def test_selected_paper_filters_cross_file_notes_and_preserves_citation(tmp_path):
    from examsage.plugin_tools import CourseBinding,PluginTools
    from examsage.storage import Store
    _,cid,docs,binding,old=imported(tmp_path/'import',extra=[('three.txt','Other reference')])
    orig=binding.scope
    manifest=old.manifest(orig)
    paper,solution,other=[docs[name] for name in ('one.txt','two.txt','three.txt')]
    ref={d.id:{'document_id':d.id,'source_sha256':d.sha256,'page':1} for d in manifest.documents}
    rows=old.list_records(orig)
    row=next(r for r in rows if r.id==paper+':p1')
    notes=[]
    for tag,content,support in [('local','PAPER-ONLY',[paper]),('both','ANSWER-NOTE',[paper,solution]),
                                ('third','THIRD-NOTE',[paper,other])]:
        notes.append({'id':tag,'origin':'user_note','summary':content,
                      'targets':[{'document_id':paper,'page':1}],'evidence':[ref[k] for k in support]})
    row.details['source_reviews']=notes
    st=Store(tmp_path/'review.sqlite3')
    snap=st.publish(orig.workspace,manifest,rows,[],old.metadata(orig))
    scope=orig.model_copy(update={'snapshot':snap})
    tools=PluginTools([CourseBinding(cid,st.path,scope)],Principal('note-owner',frozenset([cid])))
    sel={'paper_id':paper,'solution_id':solution,'exam_year':2025}
    raw=tools.call('get_source_page',{'course_id':cid,'document_id':paper,'page':1})
    for query in ['Q2(a) 只给题目','Q2(a) 答案']:
        selected=search(tools,cid,query,sel)
        assert 'THIRD-NOTE' not in str(selected)
        assert ('ANSWER-NOTE' in str(selected)) == ('答案' in query)
        assert 'PAPER-ONLY' in str(selected)
        assert selected['sources'][0]['source_id']==raw['sources'][0]['source_id']
