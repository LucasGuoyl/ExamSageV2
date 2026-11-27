"""Student tasks exercised through real Tk widgets, using two isolated example turns."""
import tkinter as tk

import pytest


def post(run, number, label):
    ref = {'document_id':'lesson','page':number,'filename':'lesson.txt'}
    return {'role':'assistant','run_id':run,'content':label,'answer':{
        'paragraphs':[{'text':label,'citations':['E1']}],
        'evidence':[{'id':'E1','refs':[ref]}],'limitations':[]}}


@pytest.fixture(scope='module')
def tk_root():
    root = tk.Tk()
    yield root
    root.destroy()


@pytest.fixture
def workspace_view(monkeypatch,tk_root):
    from examsage import study_view
    messages = [
        {'role':'user','content':'题设是什么？'}, post('first',1,'第一次回答。'),
        {'role':'user','content':'怎样推导？'}, post('second',2,'第二次回答。')]
    class Desk:
        course_id = session_id = run_id = None
        def courses(self): return [{'name':'弹簧实验','slug':'spring'}]
        def select(self, key):
            self.course_id=key
            self.session_id='s'
        def sessions(self): return [{'id':'s','title':'弹簧与回复力'}]
        def messages(self): return messages if self.session_id else []
    pages = ['第一个原文片段，刚度为 200 N/m。','第二个原文片段，由静力平衡得到 x=F/k。']
    def read(desk, run_id, evidence_id, ref_index=0, *, page=None, image=False):
        assert desk.session_id=='s' and evidence_id=='E1' and ref_index in (0,1)
        cited = 1 if run_id=='first' else 2
        page = page or cited
        return dict(filename='lesson.txt',page=page,pages=2,cited_page=cited,text=pages[page-1],
                    highlight=pages[page-1] if page==cited else '',can_previous=page>1,
                    can_next=page<2,image_supported=False)
    monkeypatch.setattr(study_view,'read_citation',read)
    root=tk_root
    root.geometry('1100x700')
    try:
        app=study_view.StudyView(root,Desk(),lambda parent:None)
        root.update()
        yield root,app,pages
    finally:
        root.unbind("<Configure>")
        for widget in root.winfo_children():
            widget.destroy()


def test_returning_student_sees_verbatim_passage_and_can_read_previous_page(workspace_view):
    root,app,pages=workspace_view
    assert pages[1] in app.page_text.get('1.0','end')
    assert pages[1] in app.chat.get('1.0','end')
    app.previous.invoke()
    assert pages[0] in app.page_text.get('1.0','end')
    assert app.previous.instate(['disabled'])
    app.back_to_cite.invoke()
    assert pages[1] in app.page_text.get('1.0','end')


def test_select_earlier_turn_with_keyboard_and_clear_on_new_chat(workspace_view):
    root,app,pages=workspace_view
    app.citations.current(0)
    app.citations.event_generate('<<ComboboxSelected>>')
    assert pages[0] in app.page_text.get('1.0','end')
    app.conversation.current(0)
    app.conversation.event_generate('<<ComboboxSelected>>')
    assert all(s not in app.page_text.get('1.0','end') for s in pages)
    assert not app.citations['values']


def test_narrow_screen_keeps_inline_quote_and_allows_return_to_composer(workspace_view):
    root,app,pages=workspace_view
    root.geometry('600x550');root.update()
    assert app.chat.winfo_viewable() and pages[1] in app.chat.get('1.0','end')
    app.read_tab.invoke();root.update()
    assert app.page_text.winfo_viewable() and pages[1] in app.page_text.get('1.0','end')
    app.chat_tab.invoke();root.update()
    assert app.question.winfo_viewable() and app.send.winfo_viewable()


def test_pending_followup_and_unsourced_answer_never_inherit_old_source(workspace_view):
    _,app,pages = workspace_view
    messages=app.desk.messages()
    messages.append({'role':'user','content':'这句话有根据吗？'})
    app.draw()
    assert '课件原文' not in app.chat.get('1.0','end').split('这句话有根据吗？')[-1]
    assert all(p not in app.page_text.get('1.0','end') for p in pages)
    messages.append({'role':'assistant','run_id':'third','content':'本轮资料不足。','answer':{}})
    app.draw()
    assert '原文' not in app.chat.get('1.0','end').split('本轮资料不足。')[-1]
    assert '本轮' in app.page_text.get('1.0','end')


def test_mouse_link_to_prior_turn_reveals_matching_inline_excerpt(workspace_view):
    root,app,pages=workspace_view
    tag=app.link_tags[0]
    pos=app.chat.tag_ranges(tag)[0]
    app.chat.see(pos)
    root.update()
    x,y,w,h=app.chat.bbox(pos)
    app.chat.event_generate('<Motion>',x=x+1,y=y+h//2)
    app.chat.event_generate('<Button-1>',x=x+1,y=y+h//2)
    root.update()
    assert pages[0] in app.page_text.get('1.0','end')
    transcript=app.chat.get('1.0','end')
    assert pages[0] in transcript.split('怎样推导？')[0]


def test_distinct_sources_with_same_filename_page_each_have_a_mouse_target(workspace_view):
    _,app,_=workspace_view
    answer=app.desk.messages()[-1]['answer']
    answer['evidence'][0]['refs'].append(dict(filename='lesson.txt',page=2,document_id='other'))
    app.draw()
    assert len(set(app.citations['values']))==3
    assert len(app.link_tags)>=3


def test_expired_course_clears_its_transcript_and_reader_on_send(workspace_view):
    _,app,pages=workspace_view
    def revoked(*args):
        raise ValueError('课程已变更')
    def clear():
        app.desk.course_id=app.desk.session_id=None
    app.desk._current=revoked
    app.desk.send=revoked
    app.desk.clear_selection=clear
    app.desk.courses=lambda:[]
    app.send.invoke()
    assert app.desk.course_id is None
    assert not app.citations['values']
    assert pages[1] not in app.page_text.get('1.0','end')
    assert '第二次回答' not in app.chat.get('1.0','end')
    assert '课程已变更' in app.state.get()


def test_selected_excerpt_has_real_paragraph_breaks(workspace_view):
    _,app,pages=workspace_view
    text=app.chat.get('1.0','end')
    assert '第 2 页\n'+pages[1]+'\n' in text
    assert r'\n' not in text


def test_same_calculation_page_does_not_duplicate_a_paragraph_link(workspace_view):
    _,app,_=workspace_view
    ans=app.desk.messages()[-1]['answer']
    direct=ans['evidence'][0]
    ans['evidence'].append({'id':'E2','kind':'calculation','refs':list(direct['refs'])})
    ans['paragraphs'][0]['citations'].append('E2')
    app.draw()
    assert len(app.link_tags)==2
    assert len(app.citations['values'])==3


def test_visual_page_can_be_read_at_full_size_and_return_to_text(workspace_view,monkeypatch):
    from io import BytesIO
    from PIL import Image
    from examsage import study_view
    root,app,_=workspace_view
    real_read=study_view.read_citation
    buf=BytesIO()
    Image.new('RGB',(1080,900),'white').save(buf,format='PNG')
    def read(*args,**kwargs):
        page=real_read(*args,**kwargs)
        return {**page,'image_supported':True,'png':buf.getvalue() if kwargs.get('image') else None}
    monkeypatch.setattr(study_view,'read_citation',read)
    app.open_ref(0)
    app.picture.invoke()
    root.update()
    assert 0<app.photo.width()<1080
    app.zoom.invoke()
    root.update()
    assert app.photo.width()==1080 and app.image_scroll.winfo_ismapped()
    app.picture.invoke()
    assert app.photo is None and not app.image_scroll.winfo_ismapped()


def test_critical_evidence_warning_survives_collapsed_technical_notes(workspace_view):
    _,app,_=workspace_view
    warning='课件不同版本的单位存在冲突。'
    app.desk.messages()[-1]['answer']['limitations']=[warning,'Semantic content not independently reviewed.',
        'Embeddings are not configured; indexed keyword and course-alias retrieval is active.']
    app.draw()
    assert warning in app.chat.get('1.0','end')
    assert 'Embeddings' not in app.chat.get('1.0','end')
    assert '课件解析内容尚未经过独立学术核查。' not in app.chat.get('1.0','end')
    app.details[-1].invoke()
    assert '课件解析内容尚未经过独立学术核查。' in app.chat.get('1.0','end')


def test_history_selector_brings_old_answer_and_excerpt_into_view(workspace_view):
    root,app,pages=workspace_view
    app.desk.messages()[-1]['answer']['paragraphs'][0]['text']='继续计算。\n'*100
    app.draw()
    root.update()
    app.citations.current(0)
    app.citations.event_generate('<<ComboboxSelected>>')
    root.update()
    assert pages[0] in app.page_text.get('1.0','end')
    assert app.chat.bbox('excerpt_start') is not None
    assert app.chat.bbox('excerpt_end-2c') is not None
