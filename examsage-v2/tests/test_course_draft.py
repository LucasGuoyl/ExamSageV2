"""Raw selected files become a portable, explicitly unreviewed course draft."""
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from examsage.cli import main
from examsage.course_library_import import import_course_library
from examsage.course_pack import CoursePack
from examsage.plugin_tools import load_library
from test_course_pack_formats import make_pdf, make_pptx


def ordered_pptx(path, show='0'):
    make_pptx(path)
    with ZipFile(path) as z:
        parts={name:z.read(name) for name in z.namelist()}
    p='http://schemas.openxmlformats.org/presentationml/2006/main'
    r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    rel='http://schemas.openxmlformats.org/package/2006/relationships'
    parts['ppt/presentation.xml']=(f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'
        '<p:sldId id="1" r:id="first"/><p:sldId id="2" r:id="second"/></p:sldIdLst></p:presentation>').encode()
    parts['ppt/_rels/presentation.xml.rels']=(f'<Relationships xmlns="{rel}">'
        '<Relationship Id="first" Target="slides/slide1.xml"/>'
        '<Relationship Id="second" Target="slides/slide2.xml"/></Relationships>').encode()
    parts['ppt/slides/slide2.xml']=parts['ppt/slides/slide2.xml'].replace(b'show="0"',f'show="{show}"'.encode())
    with ZipFile(path,'w') as z:
        for name,content in parts.items():z.writestr(name,content)


def draft(root, output, files, **changes):
    from examsage.course_draft import create_course_draft
    return create_course_draft(root, files, output, course_id='new-course', name='新课程',
                               disciplines=['physics'], **changes)


def test_cli_raw_to_portable_pack_to_query_without_handwritten_json(tmp_path, capsys):
    root = tmp_path / '课件'
    root.mkdir()
    raw = '原始条件：n 为正整数。\f归纳推导：sum = n(n+1)/2。'
    (root / '笔记.md').write_text(raw, encoding='utf-8-sig')
    output = tmp_path / 'draft'
    assert main(['draft-course','--source-root',str(root),'--file','笔记.md','--course-id','new-course',
        '--name','新课程','--discipline','mathematics','--output',str(output)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'draft_requires_review'
    moved = tmp_path / '已搬移'
    output.rename(moved)
    pack = CoursePack.model_validate_json((moved / 'pack.json').read_text(encoding='utf-8'))
    assert pack.profile.course_id == 'new-course'
    assert pack.profile.syllabus_version == 'unspecified'
    assert pack.profile.institution is None
    assert pack.profile.outcomes == [] and pack.records == [] and pack.relations == []
    doc = pack.manifest.documents[0]
    assert doc.pages == 2 and doc.kind == 'unknown'
    assert doc.exam_year is None and doc.available_from is None
    assert (moved / doc.relative_path).read_bytes() == (root / '笔记.md').read_bytes()
    audit = json.loads((moved / 'intake.json').read_text(encoding='utf-8'))
    assert audit['semantic_review'] == 'pending' and audit['model_called'] is False
    assert 'syllabus_version' in audit['metadata_unconfirmed']
    library = tmp_path / 'library'
    import_course_library(moved, ['pack.json'], library)
    tools = load_library(library, ['new-course'])
    page = tools.call('get_source_page', {'course_id':'new-course','document_id':doc.id,'page':2})
    assert page['records'][0]['text'] == raw.split('\f')[1]
    assert page['sources'][0]['refs'][0]['filename'] == '笔记.md'
    assert tools.call('get_answer', {'course_id':'new-course','question_id':'invented'})['sufficiency'] == 'insufficient'


def test_same_names_and_same_bytes_keep_separate_source_identity(tmp_path):
    root = tmp_path / 'input'
    for folder in ('a','b'):
        (root / folder).mkdir(parents=True)
        (root / folder / 'notes.txt').write_text('Shared text from two separately selected source paths.',encoding='utf-8')
    output = tmp_path / 'draft'
    draft(root, output, ['a/notes.txt','b/notes.txt'])
    pack = CoursePack.model_validate_json((output / 'pack.json').read_text(encoding='utf-8'))
    assert len({d.id for d in pack.manifest.documents}) == 2
    assert len({d.relative_path for d in pack.manifest.documents}) == 2
    assert len({d.sha256 for d in pack.manifest.documents}) == 1
    audit = json.loads((output / 'intake.json').read_text(encoding='utf-8'))
    assert len(audit['duplicate_content_groups']) == 1
    assert set(audit['duplicate_content_groups'][0]['documents']) == {d.id for d in pack.manifest.documents}
    assert {d['selected_path'] for d in audit['documents']} == {'a/notes.txt','b/notes.txt'}


def test_pdf_pptx_inventory_keeps_failed_hidden_and_notes_pages(tmp_path):
    root = tmp_path / 'input'
    root.mkdir()
    make_pdf(root / '课堂.pdf')
    ordered_pptx(root / '幻灯片.pptx')
    output = tmp_path / 'draft'
    draft(root,output,['课堂.pdf','幻灯片.pptx'])
    pack = CoursePack.model_validate_json((output/'pack.json').read_text(encoding='utf-8'))
    assert [d.pages for d in pack.manifest.documents] == [2,2]
    index = json.loads((output/'source-index.json').read_text(encoding='utf-8'))
    assert len(index['pages']) == 4
    assert sum(p['status']=='failed' for p in index['pages']) == 1
    assert sum(p['hidden'] for p in index['pages']) == 1
    assert sum(bool(p['notes']) for p in index['pages']) == 2
    assert all(p['visual_status']=='not_reviewed' for p in index['pages'])
    library=tmp_path/'library'
    import_course_library(output,['pack.json'],library)
    tools=load_library(library,['new-course'])
    pdf,pptx=pack.manifest.documents
    assert tools.call('get_source_image',{'course_id':'new-course','document_id':pdf.id,'page':1})['image']['available']
    assert tools.call('get_source_page',{'course_id':'new-course','document_id':pptx.id,'page':2})['records']==[]


def test_pptx_physical_order_follows_presentation_not_numbered_parts(tmp_path):
    root=tmp_path/'input';root.mkdir()
    source=root/'slides.pptx'
    make_pptx(source)
    p='http://schemas.openxmlformats.org/presentationml/2006/main'
    r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    rel='http://schemas.openxmlformats.org/package/2006/relationships'
    with ZipFile(source,'a') as z:
        z.writestr('ppt/presentation.xml',f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst>'
            '<p:sldId id="2" r:id="second"/><p:sldId id="1" r:id="first"/></p:sldIdLst></p:presentation>')
        z.writestr('ppt/_rels/presentation.xml.rels',f'<Relationships xmlns="{rel}">'
            '<Relationship Id="first" Target="slides/slide1.xml"/>'
            '<Relationship Id="second" Target="slides/slide2.xml"/></Relationships>')
    draft(root,tmp_path/'draft',['slides.pptx'])
    index=json.loads((tmp_path/'draft/source-index.json').read_text(encoding='utf-8'))
    assert [p['number'] for p in index['pages']] == [1,2]
    assert [p['hidden'] for p in index['pages']] == [True,False]


@pytest.mark.parametrize('files',['empty','duplicate','traversal','absolute','unsupported'])
def test_bad_selection_publishes_nothing(tmp_path,files):
    root=tmp_path/'input';root.mkdir()
    (root/'x.txt').write_text('hello',encoding='utf-8')
    (root/'x.exe').write_bytes(b'MZ')
    selected={'empty':[],'duplicate':['x.txt','./x.txt'],'traversal':['../input/x.txt'],
        'absolute':[str(root/'x.txt')],'unsupported':['x.exe']}[files]
    with pytest.raises(ValueError):draft(root,tmp_path/'draft',selected)
    assert not (tmp_path/'draft').exists()
    assert not list(tmp_path.glob('.cd-*'))


@pytest.mark.parametrize('bad',['invalid_utf8','bad_pdf','bad_pptx','missing_member','empty_pdf'])
def test_bad_later_source_rolls_back_whole_draft(tmp_path,bad):
    root=tmp_path/'input';root.mkdir()
    (root/'good.txt').write_text('Preserve the first selected source.',encoding='utf-8')
    suffix={'invalid_utf8':'.txt','bad_pdf':'.pdf','bad_pptx':'.pptx','missing_member':'.pptx','empty_pdf':'.pdf'}[bad]
    path=root/('bad'+suffix)
    if bad=='missing_member':
        with ZipFile(path,'w') as z:
            z.writestr('ppt/presentation.xml','<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="1" r:id="missing"/></p:sldIdLst></p:presentation>')
    elif bad=='empty_pdf':
        from pypdf import PdfWriter
        PdfWriter().write(path)
    else:path.write_bytes(b'\xffbroken')
    before={p.name:sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
    with pytest.raises(ValueError):draft(root,tmp_path/'draft',['good.txt',path.name])
    assert not (tmp_path/'draft').exists() and not list(tmp_path.glob('.cd-*'))
    assert before=={p.name:sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}


def test_metadata_no_exam_inference_and_existing_output_protected(tmp_path):
    root=tmp_path/'input';root.mkdir()
    (root/'2025-exam-answers.txt').write_text('A filename is not exam provenance.',encoding='utf-8')
    out=tmp_path/'draft'
    draft(root,out,['2025-exam-answers.txt'],kind='practice',syllabus_version='v2',
          material_status='demonstration',language='en',stage='school',curriculum_system='test')
    pack=CoursePack.model_validate_json((out/'pack.json').read_text(encoding='utf-8'))
    assert pack.profile.material_status=='demonstration'
    assert pack.manifest.documents[0].kind=='practice'
    assert pack.manifest.documents[0].exam_year is None
    before=sha256((out/'pack.json').read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):draft(root,out,['2025-exam-answers.txt'])
    assert sha256((out/'pack.json').read_bytes()).hexdigest()==before


def test_cli_bad_input_has_json_error_without_loading_old_model_path(tmp_path,capsys,monkeypatch):
    from examsage import cli
    def forbidden(*args):raise AssertionError('Legacy model path must not run')
    monkeypatch.setattr(cli,'service_for',forbidden)
    root=tmp_path/'input';root.mkdir()
    assert main(['draft-course','--source-root',str(root),'--file','missing.pdf','--course-id','new-course',
        '--name','新课程','--discipline','history','--output',str(tmp_path/'draft')])==1
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='draft_failed' and result['model_called'] is False


def test_valid_long_final_source_name_survives_draft_staging(tmp_path):
    root=tmp_path/'s';root.mkdir()
    output=tmp_path/'d'
    length=255-len(str((output/'sources/0001').resolve()))-len('/.txt')
    filename='n'*length+'.txt'
    (root/filename).write_text('Long filename, valid final source path.',encoding='utf-8')
    assert len(str((output/'sources/0001'/filename).resolve()))==255
    draft(root,output,[filename])
    assert (output/'sources/0001'/filename).read_bytes()==(root/filename).read_bytes()
    assert not list(tmp_path.glob('.cd-*'))


@pytest.mark.parametrize('show,hidden',[('false',True),('true',False),('0',True),('1',False)])
def test_xml_boolean_visibility_survives_draft_and_import(tmp_path,show,hidden):
    root=tmp_path/'input';root.mkdir()
    ordered_pptx(root/'slides.pptx',show)
    output=tmp_path/'draft'
    draft(root,output,['slides.pptx'])
    index=json.loads((output/'source-index.json').read_text(encoding='utf-8'))
    assert index['pages'][1]['hidden'] is hidden
    import_course_library(output,['pack.json'],tmp_path/'lib')
    tools=load_library(tmp_path/'lib',['new-course'])
    result=tools.call('get_source_page',{'course_id':'new-course',
        'document_id':index['documents'][0]['id'],'page':2})
    assert bool(result['records']) is not hidden


def test_raw_pptx_without_presentation_cannot_claim_physical_page_order(tmp_path):
    root=tmp_path/'input';root.mkdir()
    make_pptx(root/'slides.pptx')  # ZIP has slides but no authoritative order.
    with pytest.raises(ValueError,match='presentation'):
        draft(root,tmp_path/'draft',['slides.pptx'])
    assert not (tmp_path/'draft').exists()


def test_ambiguous_slide_visibility_is_rejected(tmp_path):
    root=tmp_path/'input';root.mkdir()
    ordered_pptx(root/'slides.pptx','maybe')
    with pytest.raises(ValueError,match='visibility'):
        draft(root,tmp_path/'draft',['slides.pptx'])
    assert not (tmp_path/'draft').exists()
