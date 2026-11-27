from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile
import pytest


def make_slides(path):
    with ZipFile(path, "w") as z:
        z.writestr("ppt/slides/slide1.xml", '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" show="0"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Darcy</a:t></a:r><a:r><a:t> flux</a:t></a:r></a:p></p:txBody></p:sp><p:pic><a:blip r:embed="rId1"/></p:pic></p:spTree></p:cSld></p:sld>''')
        z.writestr("ppt/slides/_rels/slide1.xml.rels", '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/></Relationships>''')
        z.writestr("ppt/media/image1.png", b"image-bytes")


def test_pptx_keeps_inline_runs_hidden_and_images(tmp_path):
    from examsage.ingest import extract_document, page_records
    from examsage.manifest import describe_document
    p = tmp_path / "sample.pptx"
    make_slides(p)
    doc = describe_document(p, tmp_path, "c", "lecture", 1)
    pages = extract_document(p, doc, tmp_path / "assets")
    assert pages[0].text == "Darcy flux"
    assert pages[0].hidden
    assert pages[0].image_count == 1
    assert pages[0].status == "partial"
    assert pages[0].visual_status == "not_reviewed"
    assert (tmp_path / "assets" / pages[0].assets[0]).exists()
    assert all(r.visibility == "hidden" for r in page_records(pages, doc))


def test_notes_excluded_from_visible_blocks_and_original_preserved():
    from examsage.domain import Page, Document
    from examsage.ingest import page_records
    doc = Document(id="d", relative_path="a.pptx", sha256="a"*64, pages=1, kind="lecture")
    page = Page(document_id="d", number=1, text="q = K i\nK: conductivity", notes="Possible exam question")
    records = page_records([page], doc)
    assert records[0].text == page.text
    assert records[0].details["raw_text"] == page.text
    assert records[1].visibility == "notes"
    assert all(r.refs[0].page == 1 for r in records)


def test_ingest_cached_hash_checked_and_resumes(tmp_path):
    from examsage.ingest import ingest
    from examsage.domain import Manifest
    from examsage.manifest import describe_document
    source = tmp_path / "source"
    source.mkdir()
    p = source / "a.pptx"
    make_slides(p)
    doc = describe_document(p, source, "c", "lecture", 1)
    manifest = Manifest(course_key="c", course_name="C", documents=[doc])
    first = ingest(source, manifest, tmp_path / "data")
    second = ingest(source, manifest, tmp_path / "data")
    assert first["processed"] == 1 and second["cached"] == 1
    assert first["pages"] == second["pages"]
    p.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        ingest(source, manifest, tmp_path / "data")


def test_archive_traversal_does_not_escape_asset_directory(tmp_path):
    from examsage.ingest import safe_member
    with pytest.raises(ValueError):
        safe_member("ppt/slides/slide1.xml", "../../../../evil.png")


def test_pdf_page_count_and_failed_visual_work_are_visible(tmp_path):
    from pypdf import PdfWriter
    from examsage.ingest import extract_document
    from examsage.manifest import describe_document
    p = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(str(p))
    doc = describe_document(p, tmp_path, "c", "lecture", 1)
    pages = extract_document(p, doc, tmp_path / "assets")
    assert len(pages) == 1
    assert pages[0].status == "partial"
    assert "little_or_no_native_text" in pages[0].issues


def test_old_cache_cannot_restore_incorrect_visibility_after_parser_fix(tmp_path):
    from examsage.domain import Manifest, Page, digest
    from examsage.ingest import ingest
    from examsage.manifest import describe_document
    source=tmp_path/'source';source.mkdir()
    p=source/'slides.pptx'
    with ZipFile(p,'w') as z:
        z.writestr('ppt/slides/slide1.xml','<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" show="false"><p:cSld/></p:sld>')
    doc=describe_document(p,source,'c','lecture',1)
    data=tmp_path/'data';(data/'cache').mkdir(parents=True)
    cache=data/'cache'/(digest([doc.id,doc.sha256,'native-layout-v2.2'])+'.json')
    cache.write_text(json.dumps([Page(document_id=doc.id,number=1,text='Old visible text',hidden=False).model_dump()]),encoding='utf-8')
    result=ingest(source,Manifest(course_key='c',course_name='C',documents=[doc]),data)
    assert result['processed']==1 and result['cached']==0
    assert result['pages'][0].hidden is True
    assert result['records'][0].visibility=='hidden'
