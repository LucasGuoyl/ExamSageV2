from __future__ import annotations

import re

from .domain import Document, Page, Record, SourceRef

MAIN = re.compile(r"(?m)^\s*(\d{1,2})\.\s+(?=\S)")
PART = re.compile(r"(?m)^\s*\(?([ivx]+)\)\s+", re.I)
MARK = re.compile(r"\(\s*(\d+)\s+marks?\s*\)", re.I)


def parse_exam(doc: Document, pages: list[Page], course: str) -> list[Record]:
    if doc.kind != "exam" or doc.exam_year is None:
        raise ValueError("Only verified dated formal exams can be parsed as exams")
    selected = sorted((p for p in pages if p.document_id == doc.id), key=lambda p: p.number)
    spans, text = [], ""
    for page in selected:
        start = len(text)
        text += page.text + "\n"
        spans.append((start, len(text), page.number))

    def references(start, end):
        return [SourceRef(document_id=doc.id, page=n, block_id=f"{doc.id}:p{n}") for a,b,n in spans if a < end and b > start]

    matches = list(MAIN.finditer(text))
    result = []
    for index, match in enumerate(matches):
        end = matches[index+1].start() if index+1 < len(matches) else len(text)
        start, number = match.start(), match[1]
        body = text[match.end():end].strip()
        parent_id = f"{course}:exam:{doc.exam_year}:{doc.id}:q{number}"
        # Match a first '(i)' immediately following the main question number too.
        parts = list(PART.finditer(body))
        marks = [int(x) for x in MARK.findall(body)]
        total = sum(marks) if marks else None
        shared = body[:parts[0].start()].strip() if parts else ""
        title_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
        details = {"exam_year":doc.exam_year, "number":number, "part":None, "marks":total,
                   "answer_status":"not_provided", "numbered_parts":len(parts), "shared_stem":shared}
        result.append(Record(id=parent_id, kind="question", title=f"{doc.exam_year} Q{number} · {title_line[:100]}",
                             text=body, refs=references(start,end), details=details, review="machine_checked",
                             limitations=["No official exam solution supplied.", "Formula/figure layout requires original-page verification."]))
        for part_index, part in enumerate(parts):
            part_end = parts[part_index+1].start() if part_index+1<len(parts) else len(body)
            content = body[part.end():part_end].strip()
            values = [int(x) for x in MARK.findall(content)]
            # The body is stripped, so compute its offset explicitly rather than assuming whitespace size.
            offset = text.find(body, match.end(), end)
            refs = references(offset+part.start(), offset+part_end)
            result.append(Record(id=f"{parent_id}.{part[1].lower()}", kind="question",
                                 title=f"{doc.exam_year} Q{number}({part[1].lower()})", text=content,
                                 parent_id=parent_id, refs=refs, review="machine_checked",
                                 details={**details,"part":part[1].lower(),"marks":sum(values) if values else None,
                                          "numbered_parts":0}, limitations=["No official exam solution supplied."]))
    return result
