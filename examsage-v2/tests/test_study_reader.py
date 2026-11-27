"""Verify the desktop reader against actual imported pages and saved turns."""
from contextlib import closing
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from examsage.student_import import import_selection
from examsage.student_workspace import Principal, StudentWorkspace
from examsage.study_window import StudyDesk


PAGES = ['Hooke\nLinear range.  Use k=200 N/m.', 'Balance\nF=kx.  x=0.05 m.']


def test_pdf_decoder_placeholders_do_not_become_citable_text(tmp_path, monkeypatch):
    from pypdf import PageObject
    from examsage.domain import Manifest
    from examsage.ingest import ingest
    from examsage.knowledge_map import extracted_text
    from examsage.manifest import describe_document
    from test_course_pack_formats import make_pdf
    import json

    source = tmp_path / "source"
    source.mkdir()
    pdf = source / "reading.pdf"
    make_pdf(pdf)
    doc = describe_document(pdf, source, "c", "lecture", 2)
    manifest = Manifest(course_key="c", course_name="Course", documents=[doc])
    valid = "Water \ufffd pressure"
    damaged = "\ufffd \ufffd\n\ufffd"
    monkeypatch.setattr(PageObject, "extract_text", lambda page: valid if page.page_number == 0 else damaged)
    data = tmp_path / "data"
    first = ingest(source, manifest, data)
    assert [(p.text, p.status) for p in first["pages"]] == [(valid, "partial"), ("", "failed")]

    # A previous import could already have saved the undecodable text as partial.
    cache, = (data / "cache").glob("*.json")
    stored = json.loads(cache.read_bytes())
    stored[1].update(text=damaged, status="partial", issues=[])
    cache.write_text(json.dumps(stored), encoding="utf-8")
    second = ingest(source, manifest, data)
    assert second["processed"] == 1 and second["pages"][1].status == "failed"
    old_record = second["records"][1].model_copy(deep=True)
    old_record.details.update(raw_text=damaged, extraction_status="partial")
    assert extracted_text(old_record) == ""


@pytest.fixture
def desk(tmp_path):
    workspace = StudentWorkspace(tmp_path, Principal('test-reader', frozenset()))
    result = import_selection(workspace.imports, 'Course', 'Physics',
                              [('lesson.txt', BytesIO('\f'.join(PAGES).encode()))])
    with closing(StudyDesk(workspace)) as desk:
        desk.select('upload-'+result['id'])
        desk.session_id = desk.runner.store.create_session(desk._current())['id']
        yield desk


def save_turn(desk, refs, *, text='Model paraphrase.', **fields):
    scope = desk._current()
    chats = desk.runner.store
    run_id = chats.begin_run(scope, desk.session_id, 'Explain', uuid4().hex)['id']
    answer = {'text': 'Assistant interpretation.', 'evidence': [
        {'id':'E1', 'snapshot':scope.snapshot, 'text':text, 'refs':refs, **fields}]}
    assert chats.finish_run(scope, run_id, answer)
    return run_id


def ref(desk, page):
    doc, = desk.store.manifest(desk._current()).documents
    return dict(document_id=doc.id, sha256=doc.sha256, filename=PurePosixPath(doc.relative_path).name, page=page)


def test_same_number_in_different_turns_resolves_originals_and_reopens(desk):
    from examsage.study_reader import read_citation
    first = save_turn(desk, [ref(desk, 1)], text='Use k=200 N/m.')
    second = save_turn(desk, [ref(desk, 2)])
    course, session = desk.course_id, desk.session_id
    desk.select(course)
    assert desk.session_id == session
    result = read_citation(desk, first, 'E1')
    assert (result['filename'], result['page'], result['text'], result['highlight']) == (
        'lesson.txt', 1, PAGES[0], 'Use k=200 N/m.')
    assert result['can_next'] and not result['can_previous']
    assert read_citation(desk, second, 'E1')['text'] == PAGES[1]
    other = read_citation(desk, first, 'E1', page=2)
    assert other['cited_page'] == 1 and other['can_previous'] and not other['can_next']
    assert other['text'] == PAGES[1] and other['highlight'] == ''
    with pytest.raises(ValueError):
        read_citation(desk, first, 'E1', page=3)
    desk.session_id = desk.runner.store.create_session(desk._current())['id']
    with pytest.raises(ValueError):
        read_citation(desk, first, 'E1')


def test_original_page_does_not_display_computed_evidence_as_a_quote(desk):
    from examsage.study_reader import read_citation
    run = save_turn(desk, [ref(desk, 1), ref(desk, 2)], kind='calculation', text='0.05')
    first = read_citation(desk, run, 'E1')
    second = read_citation(desk, run, 'E1', 1)
    assert first['text'] == PAGES[0] and second['text'] == PAGES[1]
    assert second['highlight'] == ''
    with pytest.raises(ValueError):
        read_citation(desk, run, 'E1', -1)


def test_unavailable_and_changed_references_fail_closed(desk):
    from examsage.study_reader import read_citation
    doc_ref = ref(desk, 1)
    for run in [save_turn(desk, [{**doc_ref,'sha256':'f'*64}]),
                save_turn(desk, [{**doc_ref,'filename':'other.txt'}]),
                save_turn(desk, [{**doc_ref,'document_id':'not-granted'}]),
                save_turn(desk, [doc_ref],snapshot='old-snapshot')]:
        with pytest.raises(ValueError):
            read_citation(desk, run, 'E1')
    legacy = save_turn(desk, [{'filename':'lesson.txt','page':2}])
    assert read_citation(desk, legacy, 'E1')['text'] == PAGES[1]
    receipt = desk.workspace.imports/desk.course_id.removeprefix('upload-')/'import.json'
    receipt.rename(receipt.with_suffix('.withdrawn'))
    with pytest.raises(ValueError):
        read_citation(desk, legacy, 'E1')


@pytest.mark.parametrize('kind', ['pdf', 'pptx'])
def test_read_image_or_identify_unavailable_render_without_exposing_hidden_pages(tmp_path, kind):
    from examsage.study_reader import read_citation
    from test_course_pack_formats import make_pdf
    from test_course_draft import ordered_pptx
    workspace = StudentWorkspace(tmp_path/'student', Principal('reader', frozenset()))
    source = tmp_path/('slides.'+kind)
    (make_pdf if kind == 'pdf' else ordered_pptx)(source)
    result = import_selection(workspace.imports, 'Figures', 'Science', [(source.name, BytesIO(source.read_bytes()))])
    with closing(StudyDesk(workspace)) as desk:
        desk.select('upload-'+result['id'])
        desk.session_id = desk.runner.store.create_session(desk._current())['id']
        run = save_turn(desk, [ref(desk, 1)])
        page = read_citation(desk, run, 'E1', image=True)
        assert page['image_supported'] and 'Teacher note' not in page['text']
        if kind == 'pdf':
            assert page['png'].startswith(b'\x89PNG') and page['can_next']
            assert 'Assume x is positive' in page['text']
            damaged = read_citation(desk, run, 'E1', page=2)
            assert damaged['text'] == ''
        else:
            assert page['png'] is None and page['image_reason']
            assert 'Example formula' in page['text'] and not page['can_next']
            with pytest.raises(ValueError):
                read_citation(desk, run, 'E1', page=2, image=True)
