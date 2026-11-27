from copy import deepcopy
import json

import pytest

from test_source_reviews import imported
from examsage.plugin_tools import CourseBinding, PluginTools, Principal


def nodes():
    return [
        {'id':'finite','parent':'','kind':'topic','title':'有限求和','summary':'先确定自变量的范围。',
         'support':[{'document_id':'notes','page':1,'quote':'n is a positive integer'}]},
        {'id':'formula','parent':'finite','kind':'method','title':'闭式','summary':'用闭式计算有限和。',
         'support':[{'document_id':'notes','page':2,'quote':'Sum 1..n = n(n+1)/2.'}]}]


def test_plugin_map_is_scoped_quoted_and_hierarchical(tmp_path):
    _,tools,binding=imported(tmp_path)
    browse=tools.call('browse_course_materials',{'course_id':'demo-math','offset':0})
    assert [(p['document_id'],p['page']) for p in browse['pages']]==[('notes',1),('notes',2),('second',1)]
    assert browse['next_offset'] is None
    result=tools.call('prepare_knowledge_map',{'course_id':'demo-math','nodes':nodes()})
    assert result['snapshot']==binding.scope.snapshot
    assert result['coverage']=={'cited_pages':2,'visible_pages':3}
    child=result['nodes'][1]
    assert child['parent']=='finite'
    ref=child['support'][0]
    page=tools.call('get_source_page',{'course_id':'demo-math','document_id':'notes','page':2})
    assert ref['source_id']==page['sources'][0]['source_id'] and ref['filename']=='notes.txt'
    assert child['limitations'] and any('PRIVATE_REVIEW_TEXT' in s for s in child['limitations'])
    scope=binding.scope.model_copy(update={'allowed_sources':['notes']})
    narrowed=PluginTools([CourseBinding('demo-math',binding.database,scope)],Principal('student',frozenset(['demo-math'])))
    for name,args in [('browse_course_materials',{'offset':0}),('prepare_knowledge_map',{'nodes':nodes()})]:
        data=narrowed.call(name,dict(course_id='demo-math',**args))
        assert 'PRIVATE_REVIEW_TEXT' not in json.dumps(data)
    wrong=nodes();wrong[0]['support']=[{'document_id':'second','page':1,'quote':'Second source condition'}]
    with pytest.raises(ValueError):narrowed.call('prepare_knowledge_map',{'course_id':'demo-math','nodes':wrong})


@pytest.mark.parametrize('bad',['cycle','orphan','duplicate','quote','page','unsupported','empty'])
def test_false_map_rejected(tmp_path,bad):
    _,tools,_=imported(tmp_path); ns=nodes()
    if bad=='cycle':ns[0]['parent']='formula'
    if bad=='orphan':ns[1]['parent']='absent'
    if bad=='duplicate':ns[1]['id']='finite'
    if bad=='quote':ns[1]['support'][0]['quote']='invented statement'
    if bad=='page':ns[1]['support'][0]['page']=1
    if bad=='unsupported':ns[1]['support']=[]
    if bad=='empty':ns=[]
    with pytest.raises(ValueError):tools.call('prepare_knowledge_map',{'course_id':'demo-math','nodes':ns})


def test_web_map_references_survive_history_and_rejected_tool_budget(tmp_path):
    from examsage.chat_service import CourseTools, validate_answer
    from examsage.model_runtime import RuntimeFailure
    from examsage.chat_store import ChatStore
    _,tools,b=imported(tmp_path);_,store=tools._course('demo-math')
    host=CourseTools(store,b.scope)
    host.call('browse_course_materials',{'offset':0})
    result=host.call('prepare_knowledge_map',{'nodes':nodes()})
    raw={'paragraphs':[{'kind':'source','text':'有限求和与条件','citations':[result['evidence_ids'][0]]}]}
    answer=validate_answer(raw,host)
    assert answer['knowledge_map']['nodes'][1]['support'][0]['page']==2
    assert any('PRIVATE_REVIEW_TEXT' in warning for warning in answer['limitations'])
    private=ChatStore(tmp_path/'history.sqlite3')
    session=private.create_session(b.scope,'学习');run=private.begin_run(b.scope,session['id'],'整理','req')
    assert private.finish_run(b.scope,run['id'],answer)
    assert private.messages(b.scope,session['id'])[-1]['answer']['knowledge_map']==answer['knowledge_map']
    host._bytes=99999
    changed=deepcopy(nodes());changed[0]['title']='other'
    with pytest.raises(RuntimeFailure):host.call('prepare_knowledge_map',{'nodes':changed})
    assert validate_answer(raw,host)['knowledge_map']==answer['knowledge_map']
