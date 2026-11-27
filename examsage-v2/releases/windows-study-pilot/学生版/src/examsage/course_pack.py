"""Explicit, atomic course-pack import. No model, network or library auto-discovery."""
import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from pydantic import Field, model_validator

from .course_profile import AcademicAnnotation, CourseProfile, PackRecordDetails
from .domain import Manifest, Model, Page, Record, Relation, Scope, digest
from .source_reviews import SourceReview, validate_reviews
from .exam_outlook import HEADING_INDEX, ambiguous_exam_documents, paper_headings
from .source_paths import source_path
from .storage import Store


def ref_keys(refs):
    return {(r.document_id, r.page) for r in refs}


class CoursePack(Model):
    schema_version: str = 'course-pack-v1'
    workspace: str = Field(min_length=1, max_length=80)
    profile: CourseProfile
    manifest: Manifest
    records: list[Record]
    relations: list[Relation]
    source_reviews: list[SourceReview] = Field(default_factory=list)

    @model_validator(mode='after')
    def complete_structure(self):
        if self.schema_version != 'course-pack-v1' or self.profile.course_id != self.manifest.course_key:
            raise ValueError('Course identity or schema mismatch')
        docs = {d.id: d for d in self.manifest.documents}
        validate_reviews(self.source_reviews, self.manifest)
        records = {r.id: r for r in self.records}
        if not docs or len(records) != len(self.records) or len({e.id for e in self.relations}) != len(self.relations):
            raise ValueError('Missing sources or duplicate identity')
        def check_refs(refs):
            if any(r.document_id not in docs or r.page > docs[r.document_id].pages for r in refs):
                raise ValueError('Dangling or out-of-bounds source reference')
        for record in self.records:
            check_refs(record.refs)
            PackRecordDetails.model_validate(record.details)
            seen, parent = {record.id}, record
            while parent.parent_id:
                if parent.parent_id not in records or parent.parent_id in seen or len(seen) >= 10:
                    raise ValueError('Invalid parent chain')
                parent = records[parent.parent_id]
                if record.kind in {'question', 'answer'} and parent.kind != record.kind:
                    raise ValueError('Shared question/answer conditions require same-kind parents')
                seen.add(parent.id)
            annotation = record.details.get('academic')
            if record.kind in {'proof', 'claim', 'interpretation', 'rubric'} and not annotation:
                raise ValueError('Academic record needs typed annotation')
            if annotation:
                academic = AcademicAnnotation.model_validate(annotation)
                expected = {'proof': 'derivation', 'claim': 'author_claim', 'interpretation': 'interpretation', 'rubric': 'marking_guide'}
                if record.kind in expected and academic.nature != expected[record.kind]:
                    raise ValueError('Annotation nature conflicts with record kind')
                for step in academic.steps:
                    check_refs(step.refs)
                    if not ref_keys(step.refs) <= ref_keys(record.refs):
                        raise ValueError('Derivation record omits a step source')
                for rid in academic.evidence_record_ids + academic.counter_record_ids:
                    if rid == record.id or rid not in records or not ref_keys(records[rid].refs) <= ref_keys(record.refs):
                        raise ValueError('Missing or unscoped supporting evidence')
        paired_questions, paired_answers = set(), set()
        for edge in self.relations:
            check_refs(edge.refs)
            if edge.source not in records or edge.target not in records:
                raise ValueError('Dangling relation endpoint')
            if edge.kind == 'has_answer':
                if records[edge.source].kind != 'question' or records[edge.target].kind != 'answer':
                    raise ValueError('Answer pairing needs a question and an answer')
                if edge.source in paired_questions or edge.target in paired_answers:
                    raise ValueError('Ambiguous answer pairing')
                paired_questions.add(edge.source)
                paired_answers.add(edge.target)
        if any(r.kind == 'answer' and r.id not in paired_answers for r in self.records):
            raise ValueError('Answer without explicit question pairing')
        for outcome in self.profile.outcomes:
            check_refs(outcome.refs)
            if any(rid not in records for rid in outcome.record_ids):
                raise ValueError('Learning outcome references missing record')
        return self


@dataclass(frozen=True)
class ImportResult:
    scope: Scope
    report: dict


def _publish_directory(folder: Path, output: Path):
    # Windows may briefly hold a just-written SQLite/asset directory. Retry the
    # same non-overwriting rename only; persistent or unrelated errors remain errors.
    for attempt in range(4):
        if output.exists() or output.is_symlink():
            raise FileExistsError('Choose a new course output directory')
        try:
            folder.rename(output)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 3:
                raise
            time.sleep(0.05 * (attempt + 1))


def _index_paper_headings(blocks, layouts):
    for block in blocks:
        if block.visibility != 'visible' or block.details.get('extraction_status') == 'failed':
            continue
        original = block.details['raw_text']
        layout = layouts.get(block.refs[0].page)
        headings = paper_headings(original, layout=layout) if layout else []
        if not headings:
            headings = paper_headings(original)
        if headings:
            block.details['paper_headings'] = headings


def _import_into_staging(pack: CoursePack, source_root: Path, output: Path, *, record_receipt=False) -> ImportResult:
    # Private: caller owns/cleans staging; never use this to publish a library.
    # Revalidate copies: a caller can have mutated nested dictionaries after construction.
    pack = CoursePack.model_validate(pack.model_dump(mode='json'))
    pack_digest = digest(pack.model_dump(mode='json'))
    source_root, output = source_path(source_root), output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Choose a new course output directory')
    sources = []
    for doc in pack.manifest.documents:
        source = (source_root / doc.relative_path).resolve()
        if not source.is_relative_to(source_root) or not source.is_file():
            raise ValueError('Source outside approved root or unavailable')
        if source.suffix.lower() not in {'.txt', '.md', '.pdf', '.pptx'}:
            raise ValueError('Supported sources: UTF-8 TXT/MD, PDF, PPTX')
        raw = source.read_bytes()
        if sha256(raw).hexdigest() != doc.sha256:
            raise ValueError('Source hash mismatch')
        sources.append((doc, source.suffix.lower(), raw))
    # Only the receiving service opts in. Date the batch after every source has
    # been read and verified. Imported text and file timestamps supply no clock.
    received = None
    if record_receipt:
        from datetime import datetime, timezone
        received = datetime.now(timezone.utc).date()
        for doc, _, _ in sources:
            if doc.available_from is None or doc.available_from > received:
                doc.available_from = received
                doc.date_evidence = '项目服务在该 UTC 日期收到并核对了这份文件的完整字节。学校首次发布日待核实。'
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = output
    assets = source_path(folder / 'assets')
    assets.mkdir(parents=True)
    from .ingest import extract_document, page_records
    generated, all_pages = [], []
    index_headings = not pack.records and any(doc.kind == 'exam' for doc,_,_ in sources)
    excluded = ambiguous_exam_documents(pack.manifest.documents, 'exam') if index_headings else set()
    locators = {}
    topic_evidence = {}
    for doc, suffix, raw in sources:
        doc.asset = f'sources/{doc.sha256}{suffix}'
        asset = assets / doc.asset
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(raw)
        if suffix in {'.txt', '.md'}:
            texts = raw.decode('utf-8-sig').split('\f')
            if len(texts) != doc.pages:
                raise ValueError('Declared page count mismatch (TXT/MD uses form-feed separators)')
            pages = [Page(document_id=doc.id, number=i, text=text, status='text_extracted',
                          issues=['Semantic content not independently reviewed.']) for i, text in enumerate(texts, 1)]
        else:
            try:
                pages = extract_document(asset, doc, assets)
            except KeyError as exc:
                # ZIP members and OOXML relationships are part of the source
                # format. Keep this normalization at parsing, not around the
                # entire CLI where it could hide unrelated programming errors.
                raise ValueError('Malformed source document: missing member or relationship') from exc
        all_pages.extend(pages)
        blocks = page_records(pages, doc)
        if index_headings and doc.kind in {'exam','exam_solution'} and doc.exam_year is not None and doc.id not in excluded:
            from .numbered_pages import index_numbered_pages, pdf_layouts
            layouts = pdf_layouts(asset, blocks) if suffix == '.pdf' else {}
            locators[doc.id] = index_numbered_pages(blocks,layouts,question_paper=doc.kind=='exam',page_count=doc.pages)
            if doc.kind == 'exam':
                from .paper_topics import index_paper_topics
                _index_paper_headings(blocks,layouts)
                checked = index_paper_topics(doc, blocks, locators[doc.id])
                if checked:
                    topic_evidence[doc.id] = checked
        generated.extend(blocks)
    visible_pages = {(p.document_id, p.number) for p in all_pages if not p.hidden}
    for note in pack.source_reviews:
        if any((ref.document_id, ref.page) not in visible_pages for ref in note.evidence):
            raise ValueError('Review evidence page is hidden or unavailable')
        targets = ref_keys(note.targets)
        for record in generated:
            if record.visibility == 'visible' and ref_keys(record.refs) & targets:
                record.details.setdefault('source_reviews', []).append(note.model_dump(mode='json'))
    curated = [r.model_copy(deep=True, update={'review': 'candidate'}) for r in pack.records]
    relations = [e.model_copy(deep=True, update={'review': 'candidate'}) for e in pack.relations]
    report = {'schema_version': 'course-import-review-v2', 'course_id': pack.profile.course_id,
              'structure': 'validated', 'semantic_review': 'pending',
              'material_status': pack.profile.material_status,
              'records': len(curated), 'pages': len(all_pages),
              'generated_records': len(generated),
              'notes_records': sum(r.visibility == 'notes' for r in generated),
              'extraction': {'failed_pages': sum(p.status == 'failed' for p in all_pages),
                  'partial_pages': sum(p.status == 'partial' for p in all_pages),
                  'native_text_pages': sum(p.status == 'text_extracted' for p in all_pages),
                  'hidden_pages': sum(p.hidden for p in all_pages),
                  'low_text_pages': sum(len(p.text.strip()) < 30 for p in all_pages)},
              'page_reviews': [{'document_id': p.document_id, 'page': p.number,
                  'status': p.status, 'hidden': p.hidden, 'image_count': p.image_count,
                  'notes_present': bool(p.notes), 'visual_status': p.visual_status,
                  'issues': list(p.issues)} for p in all_pages],
              'unpaired_questions': [r.id for r in curated if r.kind == 'question' and not any(
                  e.kind == 'has_answer' and e.source == r.id for e in relations)],
              'limitations': ['格式、哈希及来源定位已校验；学术正确性、题答逻辑对应与图像尚待独立核查。']}
    metadata = {'mode': 'course_pack', 'course_profile': pack.profile.model_dump(mode='json'),
                'import_report': report, 'source_pack_digest': pack_digest}
    if received is not None:
        metadata['received_on_utc'] = report['received_on_utc'] = received.isoformat()
    if topic_evidence:
        metadata['paper_topic_evidence'] = topic_evidence
    if index_headings:
        from .numbered_pages import NUMBERING_VERSION
        metadata['numbered_page_version'] = NUMBERING_VERSION
        metadata['paper_heading_index'] = HEADING_INDEX
        metadata['ambiguous_paper_documents'] = sorted(excluded)
        metadata['numbered_page_index'] = locators
        metadata['ambiguous_solution_documents'] = sorted(ambiguous_exam_documents(pack.manifest.documents, 'exam_solution'))
    store = Store(folder/'course.sqlite3')
    sid = store.publish(pack.workspace, pack.manifest, generated + curated, relations, metadata)
    scope = Scope(workspace=pack.workspace, course=pack.manifest.course_key, snapshot=sid,
                  allowed_sources=[d.id for d in pack.manifest.documents])
    for name, data in [('current.json', scope.model_dump(mode='json')), ('review.json', report),
                       ('manifest.json', pack.manifest.model_dump(mode='json'))]:
        (folder/name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return ImportResult(scope, report)


def import_pack(pack: CoursePack, source_root: Path, output: Path) -> ImportResult:
    if output.exists() or output.is_symlink():
        raise FileExistsError('Choose a new course output directory')
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.course-import-', dir=output.parent) as temporary:
        folder = Path(temporary) / 'course'
        result = _import_into_staging(pack, source_root, folder)
        _publish_directory(folder, output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    pack = CoursePack.model_validate_json(args.pack.read_text(encoding='utf-8'))
    result = import_pack(pack, args.source_root, args.output)
    print(json.dumps(result.report, ensure_ascii=False))


if __name__ == '__main__':
    main()
