"""Run the downloadable application's study flow without using a personal account."""
from contextlib import closing
from io import BytesIO
import json
import time
from zipfile import ZipFile

import pytest

from examsage.student_import import import_selection
from examsage.student_workspace import Principal, StudentWorkspace
from test_model_runtime import Wire, completed
from test_student_distribution import ROOT, PYTHON, run


def test_release_contains_direct_chat_without_registration(tmp_path):
    import os
    env = {k:os.environ[k] for k in ('WINDIR','SystemRoot','TEMP','TMP') if k in os.environ}
    env['LOCALAPPDATA'] = str(tmp_path/'fresh-profile')
    archive = tmp_path/'download.zip'
    run([PYTHON,'-I','-B',ROOT/'tools/build_student_kit.py',archive],env)
    unpacked = tmp_path/'学生 download'
    with ZipFile(archive) as z:
        assert '开始学习.bat' in z.namelist()
        assert 'kit.py" study' in z.read('开始学习.bat').decode('ascii')
        z.extractall(unpacked)
    probe = """import sys,runpy
from pathlib import Path
d=Path(sys.argv[1]);sys.path[:0]=[str(d/'src'),str(d)]
from examsage.model_runtime import SubscriptionRuntime
from examsage.study_window import StudyDesk
import examsage.study_host as ui
called=[]
ui.open_studio=lambda: called.append(True)
sys.argv=[str(d/'kit.py'),'study'];runpy.run_path(sys.argv[0],run_name='__main__')
assert called==[True] and not (d/'marketplace').exists()
"""
    run([PYTHON,'-I','-B','-c',probe,unpacked],env)


def test_study_course_roundtrip_cites_actual_page_and_reopens(tmp_path):
    from examsage.model_runtime import SubscriptionRuntime
    from examsage.study_window import StudyDesk, format_history
    owner = StudentWorkspace(tmp_path,Principal('A',frozenset()))
    ids = []
    for name in ['甲课','乙课']:
        result = import_selection(owner.imports,name,'Physics',[('lesson.txt',BytesIO(b'Hooke spring stiffness is 200 N/m.'))])
        ids.append('upload-'+result['id'])
    other = StudentWorkspace(tmp_path,Principal('B',frozenset()))
    with closing(StudyDesk(other)) as empty:
        assert empty.courses()==[]
        with pytest.raises(ValueError):
            empty.select(ids[0])
    event = {'id':'call1','method':'item/tool/call','params':{'threadId':'t1','turnId':'u1','callId':'c1',
             'tool':'search_evidence','arguments':{'query':'Hooke spring'}}}
    answer = json.dumps({'paragraphs':[{'text':'The stated stiffness is 200 N/m.','kind':'source','citations':['E1']}],'limitations':[]})
    wires=[Wire(events=[event,*completed(answer)]) for _ in range(2)]
    def fake_runtime(folder):
        return SubscriptionRuntime(folder,transport_factory=lambda:wires.pop(0))
    with closing(StudyDesk(owner,runtime_factory=fake_runtime)) as desk:
        desk.select(ids[0])
        for question in ['What stiffness is stated?', 'What were its units?']:
            run_id=desk.send(question)
            for _ in range(500):
                status=desk.result(run_id)
                if status['status']!='running':
                    break
                time.sleep(.01)
            assert status['status']=='completed',status.get('error')
        rendered=format_history(desk.messages())
        assert 'lesson.txt' in rendered and '第 1 页' in rendered and '200 N/m' in rendered
        assert len(desk.messages())==4 and not wires
        desk.select(ids[1])
        assert desk.messages()==[]
    with closing(StudyDesk(owner)) as reopened:
        reopened.select(ids[0])
        assert len(reopened.messages())==4
        with pytest.raises(ValueError):
            reopened.select('unknown-course')
        assert not reopened.messages() and reopened.course_id is None

def test_revoked_course_recovers_in_same_window(tmp_path):
    import threading
    from examsage.study_window import StudyDesk
    from examsage.model_runtime import RuntimeFailure
    started = threading.Event()
    class WaitingRuntime:
        def __init__(self, folder): pass
        def generate(self, context, specs, call, cancel, phase, *, before_send):
            started.set()
            cancel.wait(5)
            raise RuntimeFailure('cancelled','stopped')
    owner = StudentWorkspace(tmp_path,Principal('A',frozenset()))
    ids = [import_selection(owner.imports,name,'History',[('lecture.txt',BytesIO(b'Some historical facts.'))])['id'] for name in ('A','B')]
    with closing(StudyDesk(owner,runtime_factory=WaitingRuntime)) as desk:
        desk.select('upload-'+ids[0])
        run_id = desk.send('Explain the lecture.')
        assert started.wait(2)
        receipt = owner.imports/ids[0]/'import.json'
        receipt.rename(receipt.with_suffix('.withdrawn'))
        with pytest.raises(ValueError):
            desk.result(run_id)
        assert not desk.run_id and not desk.messages()
        desk.select('upload-'+ids[1])
        assert desk.messages()==[]


def test_bundled_spring_uses_exact_two_pages_and_reopens_for_the_same_student(tmp_path):
    from hashlib import sha256
    from pathlib import Path
    from examsage.study_window import StudyDesk

    owner = StudentWorkspace(tmp_path, Principal('A', frozenset()))
    title = '物理示例 · 线性弹簧'
    collision = import_selection(owner.imports, title, '物理', [('lesson.txt', BytesIO(b'Different content'))])
    with closing(StudyDesk(owner)) as desk:
        example = desk.spring_example()
        assert example != 'upload-' + collision['id']
        desk.select(example)
        doc, = desk.store.manifest(desk.binding.scope).documents
        original = (ROOT/'examples/course-packs/physics/lesson.txt').read_bytes()
        assert (Path(doc.relative_path).name, doc.sha256, doc.kind, doc.pages) == (
            'lesson.txt', sha256(original).hexdigest(), 'lecture', 2)
    with closing(StudyDesk(owner)) as reopened:
        assert reopened.spring_example() == example
        assert len(reopened.courses()) == 2
    other = StudentWorkspace(tmp_path, Principal('B', frozenset()))
    with closing(StudyDesk(other)) as independent:
        assert independent.courses() == []
        assert independent.spring_example() != example


def test_history_labels_per_answer_subscription_and_sources():
    from examsage.study_window import format_history

    message = {'role': 'assistant', 'content': '', 'answer': {
        'paragraphs': [{'text':'伸长 0.05 m。', 'citations':['E1']}],
        'evidence': [{'id': 'E1', 'refs':[{'filename': 'lesson.txt', 'page': 2}]}]}}
    legacy = format_history([message])
    assert '课件出处' in legacy and '[E1] lesson.txt 第 2 页' in legacy
    assert '本轮已使用 ChatGPT 套餐' not in legacy
    message['answer']['subscription_verified'] = True
    assert '本轮已使用 ChatGPT 套餐' in format_history([message])


def test_transcript_makes_delimited_spring_math_readable_without_changing_the_answer():
    from examsage.study_window import format_history

    calculation = r'\(x=F/k=(10\,\mathrm{N})/(200\,\mathrm{N/m})=0.05\,\mathrm{m}\)'
    original = calculation + r'，\[F_s=-kx\]，\(x^{2}\)，\(\frac{F}{k}\)。原样 x_{2}。'
    paragraph = {'text': original, 'citations': ['E1']}
    rendered = format_history([{'role':'assistant', 'answer':{'paragraphs':[paragraph]}}])
    assert 'x=F/k=(10 N)/(200 N/m)=0.05 m' in rendered
    assert 'Fₛ=-kx' in rendered and 'x²' in rendered and r'\frac{F}{k}' in rendered
    assert '原样 x_{2}。 [E1]' in rendered and paragraph['text'] == original


def test_spring_button_and_shortcut_use_the_normal_course_and_send_flow(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    import examsage.study_window as ui

    owner = StudentWorkspace(tmp_path, Principal('ui-test', frozenset()))
    private = import_selection(owner.imports, '自己的课', '物理', [('my.txt', BytesIO(b'My private class.'))])
    monkeypatch.setattr(ui, 'recipient_workspace_root', lambda: tmp_path)
    monkeypatch.setattr(ui, 'local_workspace', lambda *args: owner)
    sent = []
    def capture(desk, question):
        sent.append((desk.course_id, question))
        desk.run_id = 'pending'
        return desk.run_id
    monkeypatch.setattr(ui.StudyDesk, 'send', capture)
    monkeypatch.setattr(ui.StudyDesk, 'stop', lambda self: None)
    bindings = {}
    bind = tk.Misc.bind
    def remember_binding(widget, sequence=None, func=None, add=None):
        if sequence == '<Control-Return>' and func:
            bindings[widget] = func
        return bind(widget, sequence, func, add)
    monkeypatch.setattr(tk.Misc, 'bind', remember_binding)
    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)
    def exercise(root):
        root.withdraw()
        widgets = list(descendants(root))
        buttons = {w.cget('text'): w for w in widgets if isinstance(w, ttk.Button)}
        assert '试用弹簧课件' in buttons
        composer = next(w for w in widgets if isinstance(w, tk.Text) and w.cget('state')=='normal')
        assert composer.bind('<Control-Return>')
        composer.insert('1.0','自己的未发问题')
        buttons['试用弹簧课件'].invoke()
        assert composer.get('1.0','end-1c') == ''
        chooser = next(w for w in widgets if isinstance(w, ttk.Combobox) and '自己的课' in w.cget('values'))
        chooser.current(chooser.cget('values').index('自己的课'))
        chooser.event_generate('<<ComboboxSelected>>')
        assert composer.get('1.0','end-1c') == '自己的未发问题'
        buttons['试用弹簧课件'].invoke()
        composer.insert('1.0','原题的伸长是多少？')
        root.update_idletasks()
        assert bindings[composer](None) == 'break'
        assert bindings[composer](None) == 'break'
        course, = [c for c in owner.private_catalog() if c['slug'] != 'upload-'+private['id']]
        assert sent == [(course['slug'], '原题的伸长是多少？')]
        assert buttons['停止'].instate(['!disabled'])
    monkeypatch.setattr(tk.Tk, 'mainloop', exercise)
    ui.open_window(lambda parent: None)


def test_unit_fonts_in_saved_spring_turn_render_as_plain_units():
    from examsage.study_window import readable_math
    assert readable_math(r'\(x=F/k=10\,\mathrm N/(200\,\mathrm{N/m})=0.05\,\mathrm m\)') == (
        'x=F/k=10 N/(200 N/m)=0.05 m')
    assert readable_math(r'\(\mathrm{kg}\unknown\)') == r'\(\mathrm{kg}\unknown\)'
