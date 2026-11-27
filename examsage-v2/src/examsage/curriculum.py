from __future__ import annotations

import re

from .domain import Manifest, Page, Record, Relation, SourceRef, digest


def build_catalog(manifest: Manifest, pages: list[Page], recipe: dict) -> tuple[list[Record], list[Relation]]:
    docs = [d for d in manifest.documents if d.relative_path.endswith(recipe["source"])]
    if len(docs) != 1:
        raise ValueError("catalog source must uniquely match a document")
    doc = docs[0]
    source_pages = {p.number: p for p in pages if p.document_id == doc.id}
    records, edges = [], []
    for item in recipe["items"]:
        if re.search(r"lecturer|office hours|email|housekeeping", item["title"], re.I):
            raise ValueError("administrative content is not a knowledge concept")
        refs = [SourceRef(document_id=doc.id, page=n, block_id=f"{doc.id}:p{n}") for n in item["pages"]]
        if not refs or any(s.page not in source_pages or source_pages[s.page].hidden for s in refs):
            raise ValueError("catalog references missing or hidden source pages")
        record_id = f"{manifest.course_key}:{item['kind']}:{item['key']}"
        details = dict(item.get("details", {}))
        details.update(key=item["key"], provenance="curated_course_recipe", recipe_version=recipe.get("version", "1"),
                       source_excerpts=[{"page": ref.page, "text": source_pages[ref.page].text} for ref in refs])
        records.append(Record(id=record_id, kind=item["kind"], title=item["title"], text=item["summary"],
                              aliases=item.get("aliases", []), topic=item["topic"], refs=refs, details=details,
                              review="candidate", limitations=item.get("limitations", []) +
                              ["Curated interpretation; independent human/domain review is pending. Open source pages to verify."]))
    by_key = {r.details["key"]: r for r in records}
    for relationship in recipe.get("relations", []):
        a, b = by_key[relationship[0]], by_key[relationship[1]]
        edges.append(Relation(id="rel_" + digest([a.id,b.id,relationship[2]])[:24], source=a.id, target=b.id,
                              kind=relationship[2], refs=a.refs+b.refs, origin="inferred"))
    return records, edges


def map_questions(questions: list[Record], catalog: list[Record], recipe: dict) -> list[Relation]:
    by_key = {r.details["key"]: r for r in catalog}
    edges = []
    for question in questions:
        year, number = str(question.details["exam_year"]), question.details["number"]
        selector = number + ("." + question.details["part"] if question.details.get("part") else "")
        mapping = recipe.get("question_map", {}).get(year, {})
        keys = mapping.get(selector, mapping.get(number, []))
        for key in keys:
            concept = by_key[key]
            kind = "uses_formula" if concept.kind == "formula" else "assesses"
            edges.append(Relation(id="rel_"+digest([question.id,concept.id,kind])[:24], source=question.id,
                                  target=concept.id, kind=kind, refs=question.refs+concept.refs, origin="inferred"))
    return edges
