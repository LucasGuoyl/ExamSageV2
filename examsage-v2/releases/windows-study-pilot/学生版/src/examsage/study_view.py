"""Local Tk study workspace with citations scoped to the answer that produced them."""
from dataclasses import dataclass
from io import BytesIO
import re
import sqlite3
import tkinter as tk
from tkinter import ttk

from .study_reader import read_citation
from .study_window import readable_math


INK = '#192d36'
MUTED = '#49616a'
TEAL = '#00675e'
WHITE = '#ffffff'
GROUND = '#eaf0f1'
PAPER = '#fffcf3'
FONT = 'Microsoft YaHei UI'
ERRORS = (OSError, ValueError, LookupError, RuntimeError, sqlite3.Error)
RETRIEVAL_NOTES = {
    'Semantic content not independently reviewed.': '课件解析内容尚未经过独立学术核查。',
    'Embeddings are not configured; indexed keyword and course-alias retrieval is active.': '本次使用关键词和课程别名检索。',
    '请一次指定一个明确的题号或小问编号。': '查找试卷题目时，可提供题号或小问编号。',
    '计算由受限算术工具复算；公式适用性和单位解释仍需核对。': '计算工具已复算数值；公式前提和单位仍需核对。',
}


@dataclass(frozen=True)
class Citation:
    run: str
    key: str
    index: int
    filename: str
    page: int
    turn: int
    part: str
    document: str
    calculated: bool

    @property
    def label(self):
        return f'第 {self.turn} 轮  ·  {self.filename}  ·  第 {self.page} 页  ({self.key}{self.part})'


def label(parent, text, size=10, *, weight='normal', bg=WHITE, fg=INK, **options):
    return tk.Label(parent, text=text, font=(FONT,size,weight), bg=bg, fg=fg,
                    anchor='w', justify='left', **options)


def text_area(parent, name, *, background, size=11):
    frame=tk.Frame(parent,bg=background)
    frame.rowconfigure(0,weight=1)
    frame.columnconfigure(0,weight=1)
    text=tk.Text(frame,name=name,wrap='word',padx=16,pady=12,spacing3=4,font=(FONT,size),
                 fg=INK,bg=background,relief='flat',borderwidth=0,state='disabled',
                 highlightthickness=0,selectbackground='#badedc',takefocus=True,width=1,height=1)
    bar=ttk.Scrollbar(frame,orient='vertical',command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.grid(row=0,column=0,sticky='nsew')
    bar.grid(row=0,column=1,sticky='ns')
    return frame,text


class StudyView:
    def __init__(self,root,desk,picker):
        self.root,self.desk,self.picker=root,desk,picker
        self.drafts={}
        self.links=[]
        self.link_tags=[]
        self.selected=None
        self.page_data=None
        self.image_view=False
        self.full_size=False
        self.photo=None
        self.narrow=None
        self.tab='chat'
        self.anchors={}
        self.details=[]
        self.busy=False
        self.state=tk.StringVar()
        self._styles()
        root.configure(bg=GROUND)
        root.columnconfigure(0,weight=1)
        root.rowconfigure(2,weight=1)
        self._header()
        self.panes=tk.Frame(root,bg=GROUND)
        self.panes.grid(row=2,column=0,sticky='nsew',padx=12,pady=(0,12))
        self.panes.rowconfigure(0,weight=1)
        self._chat_pane()
        self._reader_pane()
        self.refresh()
        self.layout(root.winfo_width() if root.winfo_width()>1 else 1080)
        root.bind('<Configure>',self._resize,add='+')
        root.bind('<Alt-r>',lambda e:self.show_tab('reader',focus=True))
        root.bind('<Alt-q>',lambda e:self.show_tab('chat',focus=True))

    def _styles(self):
        style=ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.',font=(FONT,10))
        style.configure('TButton',padding=(8,4),foreground=INK,background=WHITE,borderwidth=1)
        style.map('TButton',background=[('active','#e4eeed')])
        style.configure('Primary.TButton',background=TEAL,foreground=WHITE,padding=(16,5))
        style.map('Primary.TButton',background=[('disabled','#d9e4e2'),('active','#004e48')],
                  foreground=[('disabled','#536766')])
        style.configure('TCombobox',padding=3,arrowsize=14)
        style.map('TCombobox',fieldbackground=[('readonly',WHITE)],foreground=[('readonly',INK)])

    def _header(self):
        header=tk.Frame(self.root,bg='#19363e',padx=16,pady=9)
        header.grid(row=0,column=0,sticky='ew')
        label(header,'押题宝',16,weight='bold',fg=WHITE,bg='#19363e').pack(side='left')
        label(header,'学习工作台',10,fg='#c2d8db',bg='#19363e').pack(side='left',padx=14)
        self.add=ttk.Button(header,text='导入课件',command=lambda:self.guard(self.import_course))
        self.add.pack(side='right')
        self.sample=ttk.Button(header,text='试用弹簧课件',command=lambda:self.guard(self.example))
        self.sample.pack(side='right',padx=6)
        self.bar=tk.Frame(self.root,bg=GROUND,padx=14,pady=9)
        self.bar.grid(row=1,column=0,sticky='ew')
        self.bar.columnconfigure(1,weight=2)
        self.bar.columnconfigure(3,weight=3)
        self.course_label=label(self.bar,'课程',bg=GROUND,fg=MUTED)
        self.course_label.grid(row=0,column=0,padx=(0,5))
        self.chooser=ttk.Combobox(self.bar,state='readonly',width=12)
        self.chooser.grid(row=0,column=1,sticky='ew',padx=(0,12))
        self.thread_label=label(self.bar,'对话',bg=GROUND,fg=MUTED)
        self.thread_label.grid(row=0,column=2,padx=(0,5))
        self.conversation=ttk.Combobox(self.bar,state='readonly',width=12)
        self.conversation.grid(row=0,column=3,sticky='ew')
        self.chooser.bind('<<ComboboxSelected>>',lambda e:self.guard(self.choose))
        self.conversation.bind('<<ComboboxSelected>>',lambda e:self.guard(self.switch_session))
        self.tabs=tk.Frame(self.bar,bg=GROUND)
        self.chat_tab=ttk.Button(self.tabs,text='学习对话',command=lambda:self.show_tab('chat',focus=True))
        self.read_tab=ttk.Button(self.tabs,text='课件原文',command=lambda:self.show_tab('reader',focus=True))
        self.chat_tab.pack(side='left');self.read_tab.pack(side='left',padx=4)

    def _chat_pane(self):
        self.left=tk.Frame(self.panes,bg=WHITE,highlightbackground='#c7d6d7',highlightthickness=1)
        self.left.columnconfigure(0,weight=1)
        self.left.rowconfigure(1,weight=1)
        top=tk.Frame(self.left,bg=WHITE,padx=15,pady=7)
        top.grid(row=0,column=0,sticky='ew')
        label(top,'学习对话',15,weight='bold').pack(side='left')
        self.new=ttk.Button(top,text='新对话',command=lambda:self.guard(self.new_session))
        self.new.pack(side='right')
        frame,self.chat=text_area(self.left,'transcript',background=WHITE)
        frame.grid(row=1,column=0,sticky='nsew')
        for tag,opts in {
            'student':dict(foreground=MUTED,font=(FONT,9,'bold'),spacing1=8),
            'question':dict(foreground=INK,font=(FONT,12,'bold'),spacing3=8),
            'assistant':dict(foreground=TEAL,font=(FONT,10,'bold'),spacing1=9),
            'body':dict(spacing3=5),
            'cite':dict(foreground=TEAL,font=(FONT,10,'underline'),spacing3=7),
            'source_title':dict(foreground=TEAL,font=(FONT,9,'bold'),spacing1=6),
            'quote':dict(background='#eaf5f0',foreground='#184e3d',lmargin1=9,lmargin2=9,spacing3=5),
            'meta':dict(foreground=MUTED,font=(FONT,9)),
        }.items(): self.chat.tag_configure(tag,**opts)
        self.chat.tag_bind('cite','<Enter>',lambda e:self.chat.configure(cursor='hand2'))
        self.chat.tag_bind('cite','<Leave>',lambda e:self.chat.configure(cursor='xterm'))
        composer=tk.Frame(self.left,bg='#f5f8f8',padx=12,pady=8)
        composer.grid(row=2,column=0,sticky='ew')
        composer.columnconfigure(0,weight=1)
        heading=tk.Frame(composer,bg='#f5f8f8')
        heading.grid(row=0,column=0,sticky='ew')
        label(heading,'你的问题',10,weight='bold',bg='#f5f8f8').pack(side='left')
        label(heading,'Ctrl + Enter 发送',9,bg='#f5f8f8',fg=MUTED).pack(side='right')
        self.question=tk.Text(composer,name='question',width=1,height=2,wrap='word',undo=True,
                    font=(FONT,11),bg=WHITE,fg=INK,relief='flat',highlightthickness=1,
                    highlightbackground='#a6bcbe',highlightcolor=TEAL,padx=8,pady=5)
        self.question.grid(row=1,column=0,sticky='ew',pady=(3,5))
        actions=tk.Frame(composer,bg='#f5f8f8')
        actions.grid(row=2,column=0,sticky='ew')
        actions.columnconfigure(0,weight=1)
        self.status=label(actions,'',9,bg='#f5f8f8',fg=MUTED,textvariable=self.state,wraplength=260)
        self.status.grid(row=0,column=0,sticky='ew')
        actions.bind('<Configure>',lambda e:self.status.configure(wraplength=max(95,e.width-self.send.winfo_reqwidth()-self.stop.winfo_reqwidth()-14)))
        self.stop=ttk.Button(actions,text='停止',width=5,command=lambda:self.guard(self.desk.stop))
        self.stop.grid(row=0,column=1,padx=(2,5))
        self.send=ttk.Button(actions,text='发送问题',style='Primary.TButton',command=lambda:self.guard(self.ask))
        self.send.grid(row=0,column=2)
        def shortcut(event):
            self.send.invoke()
            return 'break'
        self.question.bind('<Control-Return>',shortcut)

    def _reader_pane(self):
        self.right=tk.Frame(self.panes,bg=PAPER,highlightbackground='#d2cdbb',highlightthickness=1)
        self.right.columnconfigure(0,weight=1)
        self.right.rowconfigure(3,weight=1)
        title=tk.Frame(self.right,bg=PAPER,padx=15,pady=8)
        title.grid(row=0,column=0,sticky='ew')
        label(title,'课件原文',15,weight='bold',bg=PAPER).pack(side='left')
        self.folio=label(title,'',10,fg='#755e2c',bg=PAPER)
        self.folio.pack(side='right')
        self.citations=ttk.Combobox(self.right,state='readonly',width=12)
        self.citations.grid(row=1,column=0,sticky='ew',padx=14,pady=(0,8))
        self.citations.bind('<<ComboboxSelected>>',lambda e:self.open_ref(self.citations.current(),reveal=True))
        self.citations.bind('<Home>',lambda e:self.choose_boundary(0))
        self.citations.bind('<End>',lambda e:self.choose_boundary(len(self.links)-1))
        self.filename=label(self.right,'',12,weight='bold',bg=PAPER)
        self.filename.grid(row=2,column=0,sticky='ew',padx=15,pady=(3,0))
        page_frame,self.page_text=text_area(self.right,'source',background=PAPER,size=12)
        page_frame.grid(row=3,column=0,sticky='nsew')
        self.image_scroll=ttk.Scrollbar(page_frame,orient='horizontal',command=self.page_text.xview)
        self.page_text.configure(xscrollcommand=self.image_scroll.set)
        self.page_text.configure(spacing1=3,spacing3=9)
        self.page_text.tag_configure('match',background='#fae9a8',foreground='#322f24')
        nav=tk.Frame(self.right,bg='#f5f1e4',padx=8,pady=8)
        nav.grid(row=4,column=0,sticky='ew')
        self.previous=ttk.Button(nav,text='上一页',width=6,command=lambda:self.navigate(-1))
        self.next=ttk.Button(nav,text='下一页',width=6,command=lambda:self.navigate(1))
        self.back_to_cite=ttk.Button(nav,text='回到引文',width=8,command=lambda:self.load_page())
        self.picture=ttk.Button(nav,text='看原图',width=7,command=self.toggle_image)
        self.zoom=ttk.Button(title,text='原尺寸',width=7,command=self.toggle_zoom)
        for button in (self.previous,self.next,self.back_to_cite,self.picture):
            button.pack(side='left',padx=2)

    def _resize(self,event):
        if event.widget is self.root:
            self.layout(event.width)

    def layout(self,width):
        compact=width<860
        if compact==self.narrow:
            return
        self.narrow=compact
        if compact:
            self.tabs.grid(row=1,column=0,columnspan=4,sticky='w',pady=(6,0))
        else:
            self.tabs.grid_remove()
        self.place_panes()

    def place_panes(self):
        self.left.grid_remove();self.right.grid_remove()
        self.panes.columnconfigure(0,weight=6,uniform='columns' if not self.narrow else '')
        self.panes.columnconfigure(1,weight=0 if self.narrow else 5,uniform='' if self.narrow else 'columns')
        if not self.narrow or self.tab=='chat':
            self.left.grid(row=0,column=0,sticky='nsew',padx=(0,8 if not self.narrow else 0))
        if not self.narrow or self.tab=='reader':
            self.right.grid(row=0,column=int(not self.narrow),sticky='nsew')
        for btn,tab in [(self.chat_tab,'chat'),(self.read_tab,'reader')]:
            btn.configure(style='Primary.TButton' if self.tab==tab else 'TButton')

    def show_tab(self,tab,focus=False):
        self.tab=tab
        self.place_panes()
        if tab=='reader' and self.selected is not None:
            page=self.page_data['page'] if self.page_data else None
            self.load_page(page)
        if focus:
            (self.citations if tab=='reader' else self.question).focus_set()
        return 'break'

    def clear_reader(self,message='回答中的引用会在这里显示原文。'):
        self.page_data=None
        self.photo=None
        self.full_size=False
        self.zoom.pack_forget()
        self.image_scroll.grid_remove()
        self.filename.configure(text='')
        self.folio.configure(text='')
        self.write_page(message)
        for b in (self.next,self.previous,self.back_to_cite,self.picture):
            b.state(['disabled'])
        self.picture.configure(text='看原图')

    def write_page(self,text,highlight=''):
        box=self.page_text
        box.configure(state='normal')
        box.delete('1.0','end')
        box.configure(wrap='char' if re.search(r'[一-龥]',text) else 'word')
        box.insert('end',text)
        where=text.find(highlight) if highlight else -1
        if where>=0:
            start=f'1.0+{where}c'
            box.tag_add('match',start,f'{start}+{len(highlight)}c')
            box.see(start)
        box.configure(state='disabled')

    def choose_boundary(self,index):
        self.open_ref(index,reveal=True)
        return 'break'

    def open_ref(self,index,switch=False,*,reveal=False):
        if not 0<=index<len(self.links):return
        self.selected=index
        self.citations.current(index)
        self.image_view=False
        self.full_size=False
        if switch:
            self.tab='reader'
            self.place_panes()
        self.load_page()
        if self.page_data:
            self.show_excerpt(ref=self.links[index],data=self.page_data)
            if reveal and 'excerpt_end' in self.chat.mark_names():
                self.chat.see('excerpt_end-1c')
                self.chat.see('excerpt_start')

    def navigate(self,step):
        if self.page_data:
            self.load_page(self.page_data['page']+step)

    def toggle_image(self):
        self.image_view=not self.image_view
        self.full_size=False
        if self.page_data:
            self.load_page(self.page_data['page'])

    def toggle_zoom(self):
        if self.page_data and self.image_view:
            self.full_size=not self.full_size
            self.load_page(self.page_data['page'])

    def load_page(self,page=None):
        if self.selected is None:return
        ref=self.links[self.selected]
        try:
            result=read_citation(self.desk,ref.run,ref.key,ref.index,page=page,image=self.image_view)
        except ERRORS as exc:
            self.clear_reader(str(exc))
            self.clear_excerpt()
            self.handle_error(exc)
            return
        self.page_data=result
        context = '' if result['page']==result['cited_page'] else f"   ·   引文在第 {result['cited_page']} 页"
        self.filename.configure(text=result['filename']+context)
        self.folio.configure(text=f"第 {result['page']} / {result['pages']} 页")
        text=result['text'] or '此页没有可读取的原文文字。'
        self.write_page(text,result.get('highlight') or '')
        self.photo=None
        self.zoom.pack_forget()
        self.image_scroll.grid_remove()
        if self.image_view and result.get('png'):
            from PIL import Image,ImageTk
            with Image.open(BytesIO(result['png'])) as im:
                if not self.full_size:
                    im.thumbnail((max(200,self.right.winfo_width()-36),max(200,self.page_text.winfo_height()-18)))
                self.photo=ImageTk.PhotoImage(im,master=self.root)
            self.zoom.configure(text='适应窗口' if self.full_size else '原尺寸')
            self.zoom.pack(side='right',padx=6)
            self.page_text.configure(state='normal',wrap='none')
            self.page_text.delete('1.0','end')
            self.page_text.image_create('1.0',image=self.photo)
            self.page_text.configure(state='disabled')
            if self.full_size:
                self.image_scroll.grid(row=1,column=0,sticky='ew')
        elif self.image_view:
            self.write_page('此页原图暂不可用。\n\n'+text)
        for button,enabled in ((self.previous,result['can_previous']),(self.next,result['can_next']),
                (self.back_to_cite,result['page']!=result['cited_page']),(self.picture,result['image_supported'])):
            button.state(['!disabled' if enabled else 'disabled'])
        self.picture.configure(text='读文字' if self.image_view else '看原图')

    def clear_excerpt(self):
        chat=self.chat
        if 'excerpt_start' in chat.mark_names():
            chat.configure(state='normal')
            chat.delete('excerpt_start','excerpt_end')
            chat.mark_unset('excerpt_start','excerpt_end')
            chat.configure(state='disabled')

    def show_excerpt(self,ref,data):
        self.clear_excerpt()
        anchor=self.anchors.get(ref.run)
        if not anchor:return
        chat=self.chat
        quote=data.get('highlight') or data['text']
        if not quote:
            quote='这页没有可读文字，可在原文栏查看原图。' if data['image_supported'] else '这页没有可读文字。'
        caption='引用原文' if data.get('highlight') else '原页节选'
        excerpt=quote[:180]+('…' if len(quote)>180 else '')
        chat.configure(state='normal')
        chat.mark_set('excerpt_start',anchor)
        chat.mark_gravity('excerpt_start','left')
        chat.mark_set('excerpt_end',anchor)
        chat.mark_gravity('excerpt_end','right')
        chat.insert('excerpt_end',f'{caption} · {ref.filename} 第 {ref.page} 页\n','source_title')
        chat.insert('excerpt_end',excerpt+'\n','quote')
        chat.configure(state='disabled')

    def _link(self,index,title):
        tag=f'link_{len(self.link_tags)}'
        self.link_tags.append(tag)
        self.chat.insert('end',title,('cite',tag))
        self.chat.tag_bind(tag,'<Button-1>',lambda e:self.open_ref(index,True))

    def add_notes(self,box,turn,notes):
        detail=ttk.Button(box,text=f'回答说明（{len(notes)}）')
        self.details.append(detail)
        box.window_create('end',window=detail,pady=4)
        box.insert('end','\n')
        mark=f'notes_{turn}'
        box.mark_set(mark,'end-1c')
        box.mark_gravity(mark,'left')
        def toggle():
            box.configure(state='normal')
            end=mark+'_end'
            if end in box.mark_names():
                box.delete(mark,end)
                box.mark_unset(end)
                detail.configure(text=f'回答说明（{len(notes)}）')
            else:
                box.mark_set(end,mark)
                box.mark_gravity(end,'right')
                for note in notes:
                    box.insert(end,note+'\n','meta')
                detail.configure(text='收起回答说明')
            box.configure(state='disabled')
        detail.configure(command=toggle)

    def draw(self):
        self.selected=None
        self.image_view=False
        self.links=[]
        self.clear_reader()
        for button in self.details:
            button.destroy()
        self.details.clear()
        for anchor in self.anchors.values():
            self.chat.mark_unset(anchor)
        self.anchors={}
        box=self.chat
        box.configure(state='normal')
        box.delete('1.0','end')
        for tag in self.link_tags:box.tag_delete(tag)
        self.link_tags=[]
        for mark in box.mark_names():
            if mark.startswith(('excerpt_', 'notes_')):box.mark_unset(mark)
        messages=self.desk.messages()
        turn=0
        default=None
        for msg in messages:
            default=None
            if msg['role']=='user':
                turn+=1
                box.insert('end','你\n','student')
                box.insert('end',msg['content']+'\n','question')
                continue
            answer=msg.get('answer') or {}
            box.insert('end','押题宝\n','assistant')
            by_key={}
            for ev in answer.get('evidence',[]):
                for i,ref in enumerate(ev.get('refs',[])):
                    part=f'/{i+1}' if len(ev['refs'])>1 else ''
                    link=Citation(msg.get('run_id',''),ev['id'],i,ref['filename'],ref['page'],turn,part,
                                  ref.get('document_id',''),ev.get('kind')=='calculation')
                    if default is None or ev.get('kind')!='calculation':default=len(self.links)
                    by_key.setdefault(link.key,[]).append(len(self.links))
                    self.links.append(link)
            used=set()
            def put_links(indices):
                wrote=False
                ordered=list(dict.fromkeys(indices))
                direct={(r.document,r.page) for i in ordered if (r:=self.links[i]).document and not r.calculated}
                visible=[i for i in ordered if not (self.links[i].calculated and
                         (self.links[i].document,self.links[i].page) in direct)]
                used.update(ordered)
                for idx in visible:
                    link=self.links[idx]
                    ambiguous=sum(self.links[n].page==link.page for n in visible)>1
                    suffix=f' · {link.key}{link.part}' if ambiguous else ''
                    self._link(idx,f'查看第 {link.page} 页{suffix} ↗   ')
                    wrote=True
                if wrote:box.insert('end','\n')
            for para in answer.get('paragraphs',[]):
                box.insert('end',readable_math(para['text'])+'\n','body')
                put_links(idx for key in para['citations'] for idx in by_key.get(key,[]))
            if not answer.get('paragraphs'):box.insert('end',msg['content']+'\n','body')
            for row in (answer.get('exam_outlook') or {}).get('ranking',[]):
                box.insert('end',row['topic']+' · '+'、'.join(map(str,row['years']))+'\n','body')
            put_links(i for indices in by_key.values() for i in indices if i not in used)
            if by_key:
                anchor=f'after_answer_{turn}'
                box.mark_set(anchor,'end-1c')
                box.mark_gravity(anchor,'left')
                self.anchors[msg['run_id']]=anchor
            if answer.get('subscription_verified'):
                box.insert('end','本轮已使用 ChatGPT 套餐\n','meta')
            notes=answer.get('limitations',[])
            for note in notes:
                if note not in RETRIEVAL_NOTES:
                    box.insert('end',note+'\n','meta')
            technical=[RETRIEVAL_NOTES[note] for note in notes if note in RETRIEVAL_NOTES]
            if technical:
                self.add_notes(box,turn,technical)
        if not messages:
            prompt='选择「试用弹簧课件」，或导入你自己的学习资料。' if not self.desk.course_id else '输入课程问题，回答会附上可打开的课件原文。'
            box.insert('end',prompt,'body')
        self.citations.set('')
        self.citations.configure(values=[r.label for r in self.links],state='readonly' if self.links else 'disabled')
        if default is not None:
            self.open_ref(default)
        elif messages:
            self.clear_reader('本轮尚无可查看的引用。可从以前的回答打开原文。')
        box.configure(state='disabled')
        box.see('end')

    def set_busy(self,busy):
        self.busy=busy
        for b in (self.sample,self.add,self.new):
            b.state(['disabled' if busy else '!disabled'])
        self.chooser.configure(state='disabled' if busy else 'readonly')
        self.conversation.configure(state='disabled' if busy else 'readonly')
        self.send.state(['disabled' if busy or not self.desk.course_id else '!disabled'])
        self.stop.state(['!disabled' if busy else 'disabled'])

    def save_draft(self):
        if self.desk.course_id:
            key=(self.desk.course_id,self.desk.session_id)
            self.drafts[key]=self.question.get('1.0','end-1c')
        self.question.delete('1.0','end')
        self.question.edit_reset()

    def restore_draft(self):
        self.question.insert('1.0',self.drafts.get((self.desk.course_id,self.desk.session_id),''))
        self.question.edit_reset()

    def refresh(self,chosen=None):
        self.courses=self.desk.courses()
        names=[c['name'] for c in self.courses]
        self.chooser.configure(values=[n if names.count(n)==1 else n+' · '+c['slug'][-8:] for n,c in zip(names,self.courses)])
        self.chooser.set('')
        if self.courses:
            self.chooser.current(next((i for i,c in enumerate(self.courses) if c['slug']==chosen),0))
        self.choose()

    def show_sessions(self):
        self.sessions=self.desk.sessions()
        self.conversation.configure(values=['新对话']+[s['title'] for s in self.sessions])
        self.conversation.current(next((i+1 for i,s in enumerate(self.sessions) if s['id']==self.desk.session_id),0))
        self.draw()

    def choose(self):
        self.save_draft()
        if self.chooser.current()>=0:
            self.desk.select(self.courses[self.chooser.current()]['slug'])
        self.show_sessions()
        self.restore_draft()
        self.set_busy(False)
        self.state.set('本机 Codex 会发送问题、相关对话和课件片段。' if self.desk.course_id else '先选择一门课')
        self.question.focus_set()

    def switch_session(self):
        self.save_draft()
        i=self.conversation.current()
        self.desk.session_id=self.sessions[i-1]['id'] if i>0 else None
        self.draw()
        self.restore_draft()
        self.show_tab('chat',focus=True)

    def new_session(self):
        self.conversation.current(0)
        self.switch_session()

    def import_course(self):
        result=self.picker(self.root)
        if result:self.refresh('upload-'+result['id'])

    def example(self):
        self.refresh(self.desk.spring_example())

    def ask(self):
        if self.busy:return
        key=(self.desk.course_id,self.desk.session_id)
        run=self.desk.send(self.question.get('1.0','end-1c'))
        self.drafts.pop(key,None)
        self.question.delete('1.0','end')
        self.question.edit_reset()
        self.set_busy(True)
        self.state.set('正在连接 ChatGPT 套餐…')
        self.draw()
        self.root.after(120,lambda:self.poll(run))

    def poll(self,run):
        try:
            result=self.desk.result(run)
        except ERRORS as exc:
            self.guard(self.refresh)
            self.state.set(str(exc))
            return
        if result['status']=='running':
            phases={'connecting':'核验套餐连接…','thinking':'正在分析问题…','retrieving':'正在查找课件…','validating':'正在核对出处…'}
            self.state.set(phases.get(result['phase'],'正在处理问题…'))
            self.root.after(250,lambda:self.poll(run))
            return
        self.set_busy(False)
        self.show_sessions()
        self.state.set(result['error']['message'] if result['error'] else
                       '已停止' if result['status']=='cancelled' else '已保存 · 可以继续追问')
        self.question.focus_set()

    def guard(self,action):
        try:action()
        except ERRORS as exc:
            self.handle_error(exc)

    def handle_error(self,exc):
        if self.desk.course_id:
            try:
                self.desk._current()
            except ERRORS:
                self.desk.clear_selection()
        if not self.desk.course_id:
            self.question.delete('1.0','end')
            self.question.edit_reset()
            self.chooser.set('')
            self.conversation.set('')
            self.conversation.configure(values=[])
            self.courses=self.desk.courses()
            self.chooser.configure(values=[c['name'] for c in self.courses])
            self.draw()
            self.set_busy(False)
        self.state.set(str(exc))
