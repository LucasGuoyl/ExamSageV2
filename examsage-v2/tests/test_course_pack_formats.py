from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest

from examsage.course_pack import CoursePack, import_pack
from examsage.plugin_tools import CourseBinding, PluginTools, Principal


def make_pdf(path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 100 Td (Assume x is positive.) Tj ET')
    for damaged in [False, True]:
        page = writer.add_blank_page(width=300, height=200)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            NumberObject(3) if damaged else DictionaryObject({NameObject('/F1'): font})})
        page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(path)


def make_pptx(path):
    from PIL import Image
    p = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    r = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    rel = 'http://schemas.openxmlformats.org/package/2006/relationships'
    with ZipFile(path, 'w') as archive:
        for i, visible in [(1, '1'), (2, '0')]:
            archive.writestr(f'ppt/slides/slide{i}.xml',
                f'<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{r}" show="{visible}"><p:cSld><p:spTree>'
                '<p:sp><p:txBody><a:p><a:r><a:t>Example formula with original conditions.</a:t></a:r></a:p></p:txBody></p:sp>'
                '<p:pic><a:blip r:embed="image"/></p:pic></p:spTree></p:cSld></p:sld>')
            archive.writestr(f'ppt/slides/_rels/slide{i}.xml.rels',
                f'<Relationships xmlns="{rel}"><Relationship Id="notes" Type="{r}/notesSlide" Target="../notesSlides/notesSlide{i}.xml"/>'
                f'<Relationship Id="image" Type="{r}/image" Target="../media/image.png"/></Relationships>')
            archive.writestr(f'ppt/notesSlides/notesSlide{i}.xml',
                f'<p:notes xmlns:p="{p}" xmlns:a="{a}"><p:sp><p:txBody><a:p><a:r><a:t>Teacher note.</a:t></a:r></a:p></p:txBody></p:sp></p:notes>')
        buffer = BytesIO()
        Image.new('RGB', (1, 1), 'white').save(buffer, format='PNG')
        archive.writestr('ppt/media/image.png', buffer.getvalue())


def import_source(tmp_path, source):
    pack = CoursePack.model_validate({'workspace': 'format-test', 'profile': {
        'course_id': 'formats', 'curriculum_system': 'demo', 'institution': None, 'stage': 'demo',
        'language': 'en', 'syllabus_version': 'v1', 'disciplines': ['physics'], 'material_status': 'demonstration'},
        'manifest': {'course_key': 'formats', 'course_name': 'Import example', 'documents': [{
            'id': 'source', 'relative_path': source.name, 'sha256': sha256(source.read_bytes()).hexdigest(),
            'kind': 'lecture', 'pages': 2}]}, 'records': [], 'relations': []})
    result = import_pack(pack, source.parent, tmp_path/'imported')
    tools = PluginTools([CourseBinding('formats', tmp_path/'imported/course.sqlite3', result.scope)],
                        Principal('student', frozenset(['formats'])))
    return result, tools


def test_pptx_report_counts_slides_separately_from_notes_and_lists_review_pages(tmp_path):
    source = tmp_path/'slides.pptx'
    make_pptx(source)
    result, tools = import_source(tmp_path, source)
    report = result.report
    assert report['pages'] == 2
    assert report['generated_records'] == 4 and report['notes_records'] == 2
    assert report['extraction']['partial_pages'] == 2
    assert report['extraction']['hidden_pages'] == 1
    assert [p['page'] for p in report['page_reviews']] == [1, 2]
    assert all(p['image_count'] == 1 for p in report['page_reviews'])
    assert all('embedded_equations_may_require_visual_review' in p['issues'] for p in report['page_reviews'])
    assert tools.call('get_source_page', {'course_id':'formats','document_id':'source','page':2})['records'] == []


def test_real_pdf_extraction_failure_is_visible_in_report_and_tool_status(tmp_path):
    source = tmp_path/'damaged-page.pdf'
    make_pdf(source)
    result, tools = import_source(tmp_path, source)
    assert result.report['extraction']['failed_pages'] == 1
    assert result.report['page_reviews'][1]['status'] == 'failed'
    assert any(x.startswith('native_extraction_failed:') for x in result.report['page_reviews'][1]['issues'])
    response = tools.call('get_source_page', {'course_id':'formats','document_id':'source','page':2})
    assert response['sufficiency'] == 'insufficient'
    assert response['records'][0]['details']['extraction_status'] == 'failed'
    assert response['records'][0]['review'] == 'candidate'
    direct = tools.call('get_record', {'course_id':'formats','record_id':'source:p2'})
    assert direct['sufficiency'] == 'insufficient'


def test_course_profile_exposes_scoped_source_review_without_excluded_pages(tmp_path):
    source = tmp_path/'damaged.pdf'
    make_pdf(source)
    result, tools = import_source(tmp_path, source)
    profile = tools.call('get_course_profile', {'course_id':'formats'})
    assert profile['source_review']['pages'] == 2
    assert profile['source_review']['failed_pages'] == 1
    binding, _ = tools._course('formats')
    denied = PluginTools([CourseBinding('formats', binding.database,
        result.scope.model_copy(update={'allowed_sources':[]}))], Principal('student',frozenset(['formats'])))
    narrowed = denied.call('get_course_profile', {'course_id':'formats'})
    assert narrowed['source_review']['pages'] == 0
    assert narrowed['source_review']['page_reviews'] == []


def test_empty_native_page_is_not_presented_as_available_text_evidence(tmp_path):
    from pypdf import PdfWriter
    source = tmp_path/'blank.pdf'
    writer = PdfWriter()
    for _ in range(2): writer.add_blank_page(width=300, height=200)
    writer.write(source)
    result, tools = import_source(tmp_path, source)
    assert result.report['extraction']['low_text_pages'] == 2
    response = tools.call('get_source_page', {'course_id':'formats','document_id':'source','page':1})
    assert response['sufficiency'] == 'insufficient'


def make_image_pdf(path):
    from PIL import Image
    Image.new('RGB', (20, 20), 'white').save(path, 'PDF', save_all=True,
        append_images=[Image.new('RGB', (20,20), 'black')])


def test_image_only_pdf_counts_embedded_images_without_claiming_text_evidence(tmp_path):
    source = tmp_path/'scan.pdf'
    make_image_pdf(source)
    result, tools = import_source(tmp_path, source)
    assert [p['image_count'] for p in result.report['page_reviews']] == [1, 1]
    response = tools.call('get_source_page', {'course_id':'formats','document_id':'source','page':1})
    assert response['records'][0]['details']['image_count'] == 1
    assert response['sufficiency'] == 'insufficient'


def test_unreadable_pdf_image_inventory_is_unknown_and_keeps_native_text(tmp_path, monkeypatch):
    from pypdf import PageObject
    def unavailable(_): raise ValueError('Unreadable image resource')
    monkeypatch.setattr(PageObject, 'images', property(unavailable))
    source = tmp_path/'text.pdf'
    make_pdf(source)
    result, tools = import_source(tmp_path, source)
    assert all(p['image_count'] is None for p in result.report['page_reviews'])
    assert all('image_inventory_failed:ValueError' in p['issues'] for p in result.report['page_reviews'])
    response = tools.call('get_source_page', {'course_id':'formats','document_id':'source','page':1})
    assert 'Assume x is positive.' in response['records'][0]['text']


@pytest.mark.parametrize('text,status', [('', 'failed'), ('', 'partial'), ('Potentially damaged text', 'failed')])
def test_file_level_answer_search_flags_unusable_extracted_page(tmp_path, text, status):
    from examsage.domain import Scope
    from examsage.search import CourseQueryService
    from test_core import example
    store, manifest, raw = example(tmp_path)
    manifest.documents[0].kind = 'exam_solution'
    raw.text = text
    raw.details = {'extraction_status':status}
    sid = store.publish('w',manifest,[raw],[],{'structure_mode':'source_pages'})
    scope = Scope(workspace='w',course=manifest.course_key,snapshot=sid,allowed_sources=['doc'])
    response = CourseQueryService(store).search_evidence(scope,'official answer')
    assert [r.id for r in response.records] == [raw.id]
    assert response.sufficiency == 'insufficient'
    assert any('text' in limitation for limitation in response.limitations)
