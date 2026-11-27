import pytest


def test_catalog_does_not_promote_administration_or_merge_different_concepts():
    from examsage.curriculum import build_catalog
    from examsage.domain import Document, Manifest, Page
    doc = Document(id="d", relative_path="notes.pdf", sha256="a"*64, pages=1, kind="lecture")
    m = Manifest(course_key="c", course_name="C", documents=[doc])
    p = Page(document_id="d", number=1, text="Darcy flux q; pore velocity v; lecturer email.")
    recipe = {"source": "notes.pdf", "items": [
        {"key":"flux","kind":"concept","title":"Darcy flux","topic":"flow","pages":[1],"summary":"flux","aliases":[]},
        {"key":"velocity","kind":"concept","title":"Pore velocity","topic":"flow","pages":[1],"summary":"velocity","aliases":[]}]}
    records, edges = build_catalog(m, [p], recipe)
    assert len(records) == 2 and len({x.id for x in records}) == 2
    assert all(r.review == "candidate" for r in records)
    recipe["items"][0]["title"] = "Lecturer email"
    with pytest.raises(ValueError, match="administrative"):
        build_catalog(m, [p], recipe)


def test_exam_parts_keep_shared_stem_marks_and_no_official_answers():
    from examsage.questions import parse_exam
    from examsage.domain import Document, Page
    doc = Document(id="exam", relative_path="exam.pdf", sha256="a"*64, pages=3, kind="exam", exam_year=2024)
    pages = [Page(document_id="exam", number=1, text="EXAM 2024"),
             Page(document_id="exam", number=2, text="1. Groundwater age\nShared table and porosity 0.35\ni) Select isotope. (15 marks)\nii) Find concentration. (5 marks)\n2. Dolomitisation\nFind velocity and water rock ratio. (20 marks)"),
             Page(document_id="exam", number=3, text="3. Other topic\nQuestion. (15 marks)")]
    questions = parse_exam(doc, pages, "course")
    parents = [q for q in questions if q.parent_id is None]
    parts = [q for q in questions if q.parent_id]
    assert len(parents) == 3 and len(parts) == 2
    assert parents[0].details["marks"] == 20
    assert parts[0].details["marks"] == 15
    assert "Shared table" in parts[0].details["shared_stem"]
    assert all(q.details["answer_status"] == "not_provided" for q in questions)
    assert parts[0].refs[0].page == 2


def test_missing_mark_not_guessed_and_cross_year_ids_differ():
    from examsage.questions import parse_exam
    from examsage.domain import Document, Page
    doc = Document(id="a", relative_path="exam.pdf", sha256="a"*64, pages=1, kind="exam", exam_year=2022)
    p = [Page(document_id="a", number=1, text="1. Explain Darcy.\n(i) Explain permeability.\n(ii) Explain porosity.")]
    first = parse_exam(doc, p, "c")
    assert all(q.details["marks"] is None for q in first)
    second = parse_exam(doc.model_copy(update={"exam_year":2024}), p, "c")
    assert {x.id for x in first}.isdisjoint(x.id for x in second)


def test_catalog_rejects_unavailable_evidence():
    from examsage.curriculum import build_catalog
    from examsage.domain import Manifest
    m = Manifest(course_key="c", course_name="C", documents=[])
    with pytest.raises(ValueError, match="source"):
        build_catalog(m, [], {"source":"missing.pdf", "items":[]})
