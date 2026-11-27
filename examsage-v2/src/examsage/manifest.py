from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

from .domain import Document, Manifest


def describe_document(path: Path, root: Path, course: str, kind: str, pages: int) -> Document:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    content_hash = sha256(path.read_bytes()).hexdigest()
    identity = sha256(f"{course}\0{relative}\0{content_hash}".encode()).hexdigest()[:24]
    return Document(id="doc_" + identity, relative_path=relative, sha256=content_hash, kind=kind, pages=pages)


def build_manifest(source_root: Path, audit_path: Path, folder: str = "grt", config: dict | None = None) -> Manifest:
    audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    mapping = {"verified_past_exam": "exam", "formula_data_sheet_not_exam": "formula_sheet",
               "lecture_or_revision": "lecture", "practice_or_answer": "tutorial_feedback",
               "practice_not_past_exam": "practice", "mock_exam_not_dated_past_exam": "mock_exam",
               "exam_guidance_examples_not_past_exam": "exam_guidance", "model_answers_and_marking_feedback": "exam_solution"}
    config = config or {'key':'imperial:70151','name':'Geological Reactive Transport',
                        'aliases':["GRT", "ESE70151", "EART70151", "地质反应运移"]}
    documents = []
    for item in audit["files"]:
        if item["course_folder"] != folder:
            continue
        relative = Path(item["relative_path"].replace("\\", "/"))
        path = source_root.joinpath(*relative.parts[1:])
        doc = describe_document(path, source_root, config['key'], mapping.get(item["document_type"], "unknown"), item["pages_or_slides"])
        if doc.sha256 != item["sha256"]:
            raise ValueError(f"Source changed since audit: {relative}")
        if doc.kind == "exam" and folder == 'grt':
            # Cover dates independently checked in the source audit. Publication time remains unknown.
            if "May-22" in path.name:
                doc.exam_year, doc.document_date = 2022, "2022-05-19"
            elif "May-24" in path.name:
                doc.exam_year, doc.document_date = 2024, "2024-05-15"
            doc.date_evidence = "Exam date on cover page 1; this is NOT proof of pre-exam availability."
        documents.append(doc)
    if not documents:
        raise ValueError("No matching audited course documents")
    return Manifest(course_key=config['key'], course_name=config['name'], aliases=config.get('aliases',[]), documents=documents)
