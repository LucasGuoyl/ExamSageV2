from io import BytesIO

import pytest

from examsage.plugin_tools import Principal
from examsage.student_import import import_selection
from examsage.student_workspace import StudentWorkspace, student_tools


@pytest.fixture
def course(tmp_path):
    owner = StudentWorkspace(tmp_path,Principal('student-a',frozenset()))
    rows = [
        ('exam22.txt','exam',2022,'Question 1\nAssume stationary flow.\n(i) Locate the recharge interval.\n(ii) Calculate the hydraulic\fhead gradient between wells.\nPage 2 of 3   © Example University\nQuestion 2\nCompare two tracers.'),
        ('exam23.txt','exam',2023,'Question 1\nExplain recharge and residence time.'),
        ('future.txt','exam',2025,'Question 1\nTarget year exclusive.'),
        ('sol.txt','exam_solution',2022,'Question 1\nUse the official answer only.'),
        ('mock.txt','mock_exam',2023,'Question 1\nA mock paper only.')]
    receipt=import_selection(owner.imports,'Hydrology','Physics',[(n,BytesIO(body.encode())) for n,_,_,body in rows],
        materials=[{'filename':n,'kind':k,'exam_year':y} for n,k,y,_ in rows],record_receipt=True)
    return student_tools(None,owner), {'course_id':'upload-'+receipt['id'],'target_year':2025,'history_mode':'paper_year'}


def browse(api,args):
    offset=0
    questions=[]
    while True:
        result=api.call('browse_exam_questions',{**args,'offset':offset})
        questions.extend(result['questions'])
        offset=result['next_offset']
        if offset is None:
            return questions


def proposal(row,quote,*,page=None,topic='Groundwater'):
    ref=next(s for s in row['excerpts'] if page is None or s['page']==page)
    return {'document_id':row['document_id'],'question_path':row['question_path'],'page':ref['page'],
            'source_id':ref['source_id'],'quote':quote,'topic':topic}


def test_question_specific_quotes_reopen_and_do_not_change_official_ranking(course,tmp_path):
    api,args=course
    prior=api.call('get_exam_outlook',{**args,'top_k':3})
    rows=browse(api,args)
    assert {r['year'] for r in rows}=={2022,2023}
    lookup={(r['year'],r['question_path']):r for r in rows}
    a=lookup[2022,'1.i']; b=lookup[2022,'1.ii']; c=lookup[2023,'1']
    assert a['excerpts'][0]['source_id']==b['excerpts'][0]['source_id']
    assert [s['page'] for s in b['excerpts']]==[1,2]
    for row in rows:
        for ref in row['excerpts']:
            page=api.call('get_source_page',dict(course_id=args['course_id'],document_id=row['document_id'],page=ref['page']))
            assert ref['source_id']==page['sources'][0]['source_id']
    candidates=[proposal(a,'Locate the recharge interval'),proposal(b,'head gradient between wells',page=2),
                proposal(c,'recharge and residence time')]
    review=api.call('prepare_exam_topic_review',{**args,'candidates':candidates})
    assert review['status']=='pending_academic_review' and review['issues']==[]
    assert [(t['topic'],t['years'],t['parent_questions']) for t in review['topics']]==[('Groundwater',[2022,2023],2)]
    assert [r['quote'] for r in review['items']]==[q['quote'] for q in candidates]
    assert api.call('get_exam_outlook',{**args,'top_k':3})==prior
    other=student_tools(None,StudentWorkspace(tmp_path,Principal('student-b',frozenset())))
    with pytest.raises(ValueError):
        other.call('prepare_exam_topic_review',{**args,'candidates':candidates})


def test_sibling_parent_context_footer_future_and_stale_citations_are_rejected(course):
    api,args=course
    rows=browse(api,args)
    b=next(r for r in rows if r['question_path']=='1.ii')
    valid=proposal(b,'Calculate the hydraulic')
    wrong=[{**valid,'quote':'Locate the recharge interval'}, {**valid,'quote':'Assume stationary flow'},
           proposal(b,'Example University',page=2),{**valid,'source_id':'src_'+'0'*64},
           {**valid,'question_path':'1','quote':'Calculate the hydraulic'}]
    binding,store=api._course(args['course_id'])
    for doc in store.manifest(binding.scope).documents:
        if doc.kind!='exam' or doc.exam_year==2025:
            page=api.call('get_source_page',dict(course_id=args['course_id'],document_id=doc.id,page=1))
            wrong.append({**valid,'document_id':doc.id,'question_path':'1','source_id':page['sources'][0]['source_id'],
                          'quote':page['records'][0]['text'].splitlines()[-1]})
    result=api.call('prepare_exam_topic_review',{**args,'candidates':[valid,*wrong]})
    assert len(result['items'])==1 and [i['index'] for i in result['issues']]==list(range(1,1+len(wrong)))
    strict={**args,'history_mode':'strict'}
    assert not browse(api,strict)
    assert not api.call('prepare_exam_topic_review',{**strict,'candidates':[valid]})['items']

def test_mixed_decimal_subquestions_and_noncontent_never_support_parent_topics(tmp_path):
    owner = StudentWorkspace(tmp_path, Principal('student', frozenset()))
    body = ('Question 1\nState the general problem.\n1.1 Calculate the vector flux.\n'
            '1.2 Describe field symmetry.\fGive an example.\nQuestion 2\n'
            'In the printed edition, what does the © copyright notice signify?\nTURN OVER\n'
            'Question 3\nQuestion 4 Explain the final stanza.')
    receipt = import_selection(owner.imports, 'Reading', 'Humanities', [('exam.txt', BytesIO(body.encode()))],
        materials=[{'filename':'exam.txt','kind':'exam','exam_year':2022}], record_receipt=True)
    api = student_tools(None, owner)
    args = {'course_id':'upload-'+receipt['id'], 'target_year':2024, 'history_mode':'paper_year'}
    rows = {r['question_path']:r for r in browse(api,args)}
    doc = rows['1']['document_id']
    refs = {n:api.call('get_source_page',{'course_id':args['course_id'],'document_id':doc,'page':n})['sources'][0]['source_id']
            for n in [1,2]}
    checks = [('1',1,'State the general problem'),('1',1,'Describe field symmetry'),
              ('1',2,'Give an example'),('2',2,'what does the © copyright notice signify'),
              ('2',2,'TURN OVER'),('3',2,'Question 3'),('4',2,'Question 4'),('4',2,'Explain the final stanza')]
    proposals = [{'document_id':doc,'question_path':path,'page':n,'source_id':refs[n],'topic':'Reading','quote':s}
                 for path,n,s in checks]
    result = api.call('prepare_exam_topic_review',{**args,'candidates':proposals})
    assert [r['index'] for r in result['items']] == [0,3,7]
    assert [r['index'] for r in result['issues']] == [1,2,4,5,6]
    assert '3' not in rows


def test_internal_labels_inline_decimal_and_scores_are_not_quotable_as_evidence(tmp_path):
    owner = StudentWorkspace(tmp_path, Principal('student', frozenset()))
    body = ('1. Compare these examples:\n   (a) Energy enters the system.\n   (b) Heat is released.\n'
            '2. Compare two coils. (15 marks)\n'
            '3. Solve the field equations.  3.1 Explain the new boundary condition.\n'
            '4. Use porosity 0.35 to estimate the flow.')
    receipt = import_selection(owner.imports,'Thermal physics','Physics',[('exam.txt',BytesIO(body.encode()))],
        materials=[{'filename':'exam.txt','kind':'exam','exam_year':2022}],record_receipt=True)
    api = student_tools(None,owner)
    args = {'course_id':'upload-'+receipt['id'],'target_year':2024,'history_mode':'paper_year'}
    rows = {r['question_path']:r for r in browse(api,args)}
    checks = [('1','system. Heat is released.'),('1','Heat is released.'),('2','15 marks'),
              ('2','Compare two coils.'),('3','Explain the new boundary condition'),
              ('3','Solve the field equations'),('4','porosity 0.35')]
    result = api.call('prepare_exam_topic_review',{**args,'candidates':[proposal(rows[i],q) for i,q in checks]})
    assert [r['index'] for r in result['items']] == [1,3,5,6]
    assert [r['index'] for r in result['issues']] == [0,2,4]
