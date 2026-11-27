from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import shutil
import time
import uuid

from .domain import Scope
from .ingest import atomic_json
from .storage import Store
from .source_paths import source_path


def inside(root: Path, relative: str) -> Path:
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('asset escapes authorized root')
    return path


def _partial_pack_metadata(original, permitted, records, cutoff=None):
    from .topic_evidence import scoped_topic_evidence
    # A portable database may leave the trusted workspace. Keep only the current
    # visible pack metadata; earlier exports may nest a wider source_metadata.
    result = {k:original[k] for k in ('mode','structure_mode','parser','paper_heading_index','search_index_version','received_on_utc')
              if k in original}
    for key in ('ambiguous_paper_documents','ambiguous_solution_documents'):
        if key in original:
            result[key] = [did for did in original[key] if did in permitted]
    if 'numbered_page_index' in original:
        result['numbered_page_index'] = {did:pages for did,pages in original['numbered_page_index'].items() if did in permitted}
        if 'numbered_page_version' in original:
            result['numbered_page_version'] = original['numbered_page_version']
    evidence = scoped_topic_evidence(original, permitted, cutoff)
    if evidence:
        result['paper_topic_evidence'] = evidence
    ids = {r.id for r in records}
    if 'course_profile' in original:
        profile = original['course_profile']
        result['course_profile'] = {**profile,'outcomes':[o for o in profile.get('outcomes',[])
            if all(r['document_id'] in permitted for r in o['refs']) and set(o['record_ids']) <= ids]}
    if 'import_report' in original:
        report = original['import_report']
        reviews = [p for p in report.get('page_reviews',[]) if p['document_id'] in permitted]
        result['import_report'] = {'records':sum(r.kind!='block' for r in records),'pages':len(reviews),
            'page_reviews':reviews,'semantic_review':report.get('semantic_review','pending')}
    return result


def publish_release(store: Store, scope: Scope, assets: Path, output: Path, extras: dict | None=None, *,
                    evaluation_dir: Path | None=None) -> dict:
    if output.exists():
        raise FileExistsError('Release directory exists; use a new version directory')
    manifest=store.manifest(scope)
    if manifest is None:
        raise ValueError('snapshot does not belong to workspace/course')
    permitted=store.permitted_documents(scope)
    partial = any(d.id not in permitted for d in manifest.documents)
    from .exam_outlook import ambiguous_outlook_documents
    from .topic_evidence import scoped_topic_evidence
    outlook_exclusions = ambiguous_outlook_documents(manifest.documents)
    excluded_papers = {d.id for d in manifest.documents if d.id in outlook_exclusions and d.kind=='exam'}
    manifest.documents=[d for d in manifest.documents if d.id in permitted]
    records=store.list_records(scope)
    original_count=len(records)
    while True:
        retained={r.id for r in records}
        complete=[r for r in records if r.parent_id is None or r.parent_id in retained]
        if len(complete)==len(records):
            break
        records=complete
    if not records:
        raise ValueError('cannot publish empty or unauthorized release')
    edges={e.id:e for r in records for e in store.related(scope,r.id)
           if e.source in retained and e.target in retained}
    paired={e.source for e in edges.values() if e.kind=='has_answer'}
    for record in records:
        if 'has_answer' in record.details:record.details['has_answer']=record.id in paired
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=output.with_name(output.name+'.staging-'+uuid.uuid4().hex[:8])
    stage.mkdir()
    # Publish a new scoped database, never copy unrelated snapshots from a shared DB.
    source_metadata=store.metadata(scope) or {}
    restricted = partial or scope.strict_history or bool(source_metadata.get('restricted_export'))
    outlook_exclusions.update(source_metadata.get('ambiguous_outlook_documents', ()))
    excluded_papers.update(source_metadata.get('ambiguous_paper_documents', ()))
    if source_metadata.get('mode')=='course_pack' and (partial or (scope.strict_history and 'paper_topic_evidence' in source_metadata)):
        source_metadata=_partial_pack_metadata(source_metadata,permitted,records,scope.cutoff if scope.strict_history else None)
    elif partial:
        source_metadata={k:v for k,v in source_metadata.items() if k!='source_metadata'}
    if (partial or scope.strict_history) and 'paper_topic_documents' in source_metadata:
        checked_docs = sorted(permitted.intersection(source_metadata['paper_topic_documents']))
        index = scoped_topic_evidence(source_metadata,checked_docs,scope.cutoff if scope.strict_history else None)
        source_metadata = {k:v for k,v in source_metadata.items()
                           if k not in {'source_metadata','paper_topic_evidence','paper_topic_documents'}}
        source_metadata['paper_topic_documents'] = checked_docs
        if index:
            source_metadata['paper_topic_evidence'] = index
    if outlook_exclusions:
        source_metadata={**source_metadata,'ambiguous_outlook_documents':sorted(outlook_exclusions & permitted)}
    if excluded_papers:
        source_metadata={**source_metadata,'ambiguous_paper_documents':sorted(excluded_papers & permitted)}
    if restricted:
        source_metadata = {**source_metadata, 'restricted_export':True}
    metadata={**source_metadata,'source_snapshot':scope.snapshot,'export_schema':'course-release-v1',
              'source_metadata':source_metadata}
    if 'pilot_records' in metadata:
        metadata.update(pilot_records=sum(bool(r.details.get('pilot_record')) for r in records),
                        pilot_questions=sum(r.kind=='question' and bool(r.details.get('pilot_record')) for r in records),
                        pilot_answer_pairs=len(paired))
    new_store=Store(stage/'course.sqlite3')
    sid=new_store.publish(scope.workspace,manifest,records,list(edges.values()),metadata)
    new_scope=scope.model_copy(update={'snapshot':sid,'allowed_sources':sorted(permitted)})
    atomic_json(stage/'current.json',new_scope.model_dump(mode='json'))
    atomic_json(stage/'manifest.json',manifest.model_dump(mode='json'))
    atomic_json(stage/'provenance.json',metadata)
    required=set()
    for doc in manifest.documents:
        if doc.asset:
            required.add(doc.asset)
    for record in records:
        if record.details.get('supplement'):
            from .supplements import validated_supplement_asset
            doc=next(d for d in manifest.documents if d.id==record.refs[0].document_id)
            if validated_supplement_asset(doc,record.details,assets) is None:
                raise ValueError('Page supplement integrity failure during export')
        if record.details.get('render'):
            from .slides import validated_slide_asset
            doc=next(d for d in manifest.documents if d.id==record.refs[0].document_id)
            if validated_slide_asset(doc,record.details,assets) is None:
                raise ValueError('Slide render integrity failure during export')
        required.update(record.details.get('assets',[]))
    for relative in sorted(required):
        source=inside(source_path(assets),relative)
        dest=inside(stage/'assets',relative)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,dest)
    for kind in ['block','concept','formula','example','question','answer']:
        with (stage/(kind+'s.jsonl')).open('w',encoding='utf-8') as stream:
            for record in records:
                if record.kind==kind:
                    stream.write(record.model_dump_json()+'\n')
    (stage/'relations.jsonl').write_text(''.join(e.model_dump_json()+'\n' for e in edges.values()),encoding='utf-8')
    atomic_json(stage/'issues.json', [{'record_id':r.id,'limitations':r.limitations} for r in records if r.limitations])
    # Extra reports describe this export, not an alternate executable input.
    if not restricted:
        reports = dict(extras or {})
        if evaluation_dir is not None:
            for file in sorted(evaluation_dir.glob('report-*.json')):
                report = json.loads(file.read_text(encoding='utf-8'))
                if isinstance(report,dict) and report.get('snapshot') == scope.snapshot:
                    reports[file.stem] = report
        if reports:
            atomic_json(stage/'quality_reports.json',reports)
    files={p.relative_to(stage).as_posix():sha256(p.read_bytes()).hexdigest() for p in stage.rglob('*') if p.is_file()}
    for doc in manifest.documents:
        if doc.asset and files.get('assets/' + Path(doc.asset).as_posix()) != doc.sha256:
            raise ValueError('source asset integrity failure in staged export')
    report={'schema':'course-release-v1','snapshot':sid,'source_snapshot':scope.snapshot,
            'documents':len(manifest.documents),'records':len(records),'relations':len(edges),
            'omitted_orphan_records':original_count-len(records),
            'human_acceptance':'pending','status':'candidate','files':files,
            'limitations':['Visual review is not complete for all pages.','Curated mappings require independent domain review.',
                           'File-level answer classification does not validate answers to individual questions.',
                           'Not a validated exam prediction product.']}
    atomic_json(stage/'release_manifest.json',report)
    for attempt in range(5):
        if output.exists():
            raise FileExistsError('Release directory exists; use a new version directory')
        try:
            stage.rename(output)
            break
        except PermissionError as exc:
            # Windows may briefly hold a new directory; preserve staging on failure.
            if getattr(exc,'winerror',None) not in {5,32} or attempt==4:
                raise
            time.sleep(.05 * 2**attempt)
    return report
