from datetime import date
import json
import pytest


def test_manifest_distinguishes_supplement_and_unknown_dates(tmp_path):
    from examsage.manifest import describe_document
    p = tmp_path / "70151_SupplementaryInformationSheet.pdf"
    p.write_bytes(b"formula reference")
    doc = describe_document(p, tmp_path, "course", "formula_sheet", 3)
    assert doc.kind == "formula_sheet"
    assert doc.available_from is None
    assert doc.exam_year is None
    assert len(doc.sha256) == 64


def test_missing_reference_rejected():
    from examsage.domain import Record
    with pytest.raises(ValueError):
        Record(id="fact", kind="concept", title="Porosity", text="pore volume fraction", refs=[])


def test_bad_locations_and_made_up_review_rejected():
    from examsage.domain import SourceRef, Record
    with pytest.raises(ValueError):
        SourceRef(document_id="doc", page=0)
    with pytest.raises(ValueError):
        SourceRef(document_id="doc", page=1, bbox=[0, 0, 2, 1])
    with pytest.raises(ValueError):
        Record(id="x", kind="concept", title="x", text="x", refs=[SourceRef(document_id="doc", page=1)], review="human_checked")


def example(tmp_path):
    from examsage.domain import Document, Manifest, Record, SourceRef
    from examsage.storage import Store
    doc = Document(id="doc", relative_path="a.pdf", sha256="a"*64, kind="lecture", pages=2)
    manifest = Manifest(course_key="c", course_name="Course", documents=[doc])
    store = Store(tmp_path / "course.sqlite3")
    record = Record(id="b", kind="block", title="Darcy", text="Darcy flux and porosity", refs=[SourceRef(document_id="doc", page=1)])
    return store, manifest, record


def test_snapshot_is_immutable_and_scope_is_enforced(tmp_path):
    from examsage.domain import Scope
    store, manifest, record = example(tmp_path)
    sid = store.publish("w", manifest, [record], [], {"parser": "v1"})
    assert sid == store.publish("w", manifest, [record], [], {"parser": "v1"})
    scope = Scope(workspace="w", course="c", snapshot=sid, allowed_sources=["doc"])
    assert store.get(scope, "b").text == record.text
    assert store.get(scope.model_copy(update={"allowed_sources": []}), "b") is None
    assert store.get(scope.model_copy(update={"workspace": "another"}), "b") is None
    assert store.get(scope.model_copy(update={"course": "another"}), "b") is None
    changed = record.model_copy(update={"text": "updated"})
    sid2 = store.publish("w", manifest, [changed], [], {"parser": "v1"})
    assert sid != sid2
    assert store.get(scope, "b").text == record.text


def test_strict_history_excludes_unknown_and_future_and_hidden(tmp_path):
    from examsage.domain import Scope
    store, manifest, record = example(tmp_path)
    hidden = record.model_copy(update={"id": "hidden", "visibility": "hidden"})
    sid = store.publish("w", manifest, [record, hidden], [], {})
    scope = Scope(workspace="w", course="c", snapshot=sid, allowed_sources=["doc"])
    assert store.get(scope, "hidden") is None
    historical = scope.model_copy(update={"strict_history": True, "cutoff": date(2024, 1, 1)})
    assert store.get(historical, "b") is None
    manifest.documents[0].available_from = date(2026, 1, 1)
    sid2 = store.publish("w", manifest, [record], [], {})
    assert store.get(historical.model_copy(update={"snapshot": sid2}), "b") is None


def test_publish_rejects_dangling_reference_and_relation(tmp_path):
    from examsage.domain import SourceRef, Relation
    store, manifest, record = example(tmp_path)
    bad = record.model_copy(update={"refs": [SourceRef(document_id="missing", page=1)]})
    with pytest.raises(ValueError):
        store.publish("w", manifest, [bad], [], {})
    relation = Relation(id="edge", source="b", target="missing", kind="assesses", refs=record.refs)
    with pytest.raises(ValueError):
        store.publish("w", manifest, [record], [relation], {})


def test_all_sources_of_composite_record_must_be_authorized(tmp_path):
    from examsage.domain import Document, SourceRef, Scope
    store, manifest, record = example(tmp_path)
    manifest.documents.append(Document(id="secret", relative_path="secret.pdf", sha256="b"*64, kind="lecture", pages=1))
    record.refs.append(SourceRef(document_id="secret", page=1))
    sid = store.publish("w", manifest, [record], [], {})
    scope = Scope(workspace="w", course="c", snapshot=sid, allowed_sources=["doc"])
    assert store.get(scope, "b") is None
