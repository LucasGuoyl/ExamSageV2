from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3

from .domain import Manifest, Record, Relation, Scope, digest
from .lexical import index_body
from .source_paths import source_path, sqlite_readonly_uri
from .source_reviews import scoped_reviews


def scoped_details(record: Record, permitted: set[str], *, strict_history=False) -> Record:
    # Standalone source corrections have no verified historical availability.
    # Keep the contemporary textbook text, with the same scope at every read entry.
    audit = record.details.get('audit')
    if strict_history and isinstance(audit, dict) and set(audit) == {'adjudication'}:
        summary = audit['adjudication'].get('summary')
        record = record.model_copy(update={
            'details': {k:v for k,v in record.details.items() if k!='audit'},
            'limitations': [line for line in record.limitations if line!=summary],
        })
    if 'source_reviews' in record.details:
        details = dict(record.details)
        details['source_reviews'] = scoped_reviews(record, permitted)
        record = record.model_copy(update={'details': details})
    # A question's comparison audit also depends on its paired answer source.
    # Keep the question available, but never expose that audit through a narrower scope.
    evidence=[];assessment=record.details.get('audit',{})
    while isinstance(assessment,dict) and assessment:
        evidence.extend(assessment.get('adjudication',{}).get('evidence',[]))
        assessment=assessment.get('previous_assessment')
    missing_evidence=any(e['document_id'] not in permitted for e in evidence)
    if missing_evidence or (record.details.get('paired_document_id') and record.details['paired_document_id'] not in permitted):
        details={k:v for k,v in record.details.items() if k not in {'audit','warnings','mapping_evidence'}}
        details['audit_unavailable']='本次可访问来源不包含全部配对或补充证据，条件与答案的联合核查内容未返回。'
        details['mapping_status']='paired_source_unavailable'
        if record.kind=='question':details['has_answer']=False
        text=record.text
        if missing_evidence:
            text=record.details.get('source_only_text') or '复核导读所需来源不完整，请查看本条原页。'
        elif record.kind=='question':
            text=record.details.get('source_only_text') or record.details.get('source_question_text') or '本题联合导读依赖当前不可访问的配对资料。请打开下方原卷页查看题干。'
        return record.model_copy(update={'details':details,'text':text})
    return record


class Store:
    """Atomic immutable course snapshots. All reads require explicit scope."""

    def __init__(self, path: Path, *, read_only: bool = False):
        self.path = Path(path)
        self.read_only = read_only
        if read_only:
            if not source_path(self.path).is_file():
                raise FileNotFoundError('Course database is unavailable')
            # Opening a plugin must never create or migrate a course database.
            with self.connect() as db:
                db.execute('SELECT id FROM snapshots LIMIT 1')
            return
        source_path(self.path.parent).mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, workspace TEXT, course TEXT,
                    manifest TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS records(snapshot TEXT, id TEXT, kind TEXT, visibility TEXT,
                    parent_id TEXT, payload TEXT, PRIMARY KEY(snapshot,id),
                    FOREIGN KEY(snapshot) REFERENCES snapshots(id));
                CREATE TABLE IF NOT EXISTS record_sources(snapshot TEXT, record_id TEXT, document_id TEXT,
                    page INTEGER, PRIMARY KEY(snapshot,record_id,document_id,page));
                CREATE INDEX IF NOT EXISTS source_lookup ON record_sources(snapshot,document_id,record_id);
                CREATE INDEX IF NOT EXISTS kind_lookup ON records(snapshot,kind);
                CREATE INDEX IF NOT EXISTS parent_lookup ON records(snapshot,parent_id);
                CREATE TABLE IF NOT EXISTS relations(snapshot TEXT, id TEXT, source TEXT, target TEXT, payload TEXT,
                    PRIMARY KEY(snapshot,id));
                CREATE INDEX IF NOT EXISTS relation_source ON relations(snapshot,source);
                CREATE INDEX IF NOT EXISTS relation_target ON relations(snapshot,target);
                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(snapshot UNINDEXED,
                    record_id UNINDEXED, title, body, tokenize='unicode61');
            """)

    @contextmanager
    def connect(self):
        target = sqlite_readonly_uri(self.path) if self.read_only else source_path(self.path)
        db = sqlite3.connect(target, timeout=30, uri=self.read_only)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if self.read_only:
            db.execute('PRAGMA query_only=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def publish(self, workspace: str, manifest: Manifest, records: list[Record], relations: list[Relation], metadata: dict) -> str:
        if self.read_only:
            raise PermissionError('Read-only course database')
        metadata={**metadata,'search_index_version':'cjk-pairs-and-derivations-v1'}
        docs = {d.id: d for d in manifest.documents}
        ids = {r.id for r in records}
        if len(ids) != len(records) or len({r.id for r in relations}) != len(relations):
            raise ValueError("duplicate record/relation ID")
        for obj in [*records, *relations]:
            for ref in obj.refs:
                if ref.document_id not in docs or ref.page > docs[ref.document_id].pages:
                    raise ValueError("dangling or out-of-bounds source reference")
        for r in records:
            if r.parent_id and r.parent_id not in ids:
                raise ValueError("dangling parent")
        for r in relations:
            if r.source not in ids or r.target not in ids:
                raise ValueError("dangling relation endpoint")
        serialized = [r.model_dump(mode="json") for r in sorted(records, key=lambda x: x.id)]
        edges = [r.model_dump(mode="json") for r in sorted(relations, key=lambda x: x.id)]
        sid = "snap_" + digest([workspace, manifest.model_dump(mode="json"), serialized, edges, metadata])[:32]
        with self.connect() as db:
            if db.execute("SELECT 1 FROM snapshots WHERE id=?", (sid,)).fetchone():
                return sid
            db.execute("INSERT INTO snapshots(id,workspace,course,manifest,metadata) VALUES(?,?,?,?,?)",
                       (sid, workspace, manifest.course_key, manifest.model_dump_json(), json.dumps(metadata, ensure_ascii=False)))
            for r in records:
                db.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", (sid, r.id, r.kind, r.visibility, r.parent_id, r.model_dump_json()))
                db.executemany("INSERT OR IGNORE INTO record_sources VALUES(?,?,?,?)", [(sid, r.id, s.document_id, s.page) for s in r.refs])
                if r.visibility == "visible":
                    db.execute("INSERT INTO search_index VALUES(?,?,?,?)", (sid, r.id, r.title + " " + " ".join(r.aliases), index_body(r)))
            db.executemany("INSERT INTO relations VALUES(?,?,?,?,?)", [(sid, r.id, r.source, r.target, r.model_dump_json()) for r in relations])
        return sid

    def manifest(self, scope: Scope) -> Manifest | None:
        with self.connect() as db:
            row = db.execute("SELECT manifest FROM snapshots WHERE id=? AND workspace=? AND course=?",
                             (scope.snapshot, scope.workspace, scope.course)).fetchone()
        return Manifest.model_validate_json(row[0]) if row else None

    def metadata(self, scope: Scope) -> dict | None:
        with self.connect() as db:
            row=db.execute('SELECT metadata FROM snapshots WHERE id=? AND workspace=? AND course=?',
                           (scope.snapshot,scope.workspace,scope.course)).fetchone()
        return json.loads(row[0]) if row else None

    def permitted_documents(self, scope: Scope) -> set[str]:
        manifest = self.manifest(scope)
        if manifest is None:
            return set()
        return {d.id for d in manifest.documents if d.id in scope.allowed_sources and
                (not scope.strict_history or (d.available_from is not None and scope.cutoff is not None and d.available_from <= scope.cutoff))}

    def get(self, scope: Scope, record_id: str) -> Record | None:
        permitted = self.permitted_documents(scope)
        if not permitted:
            return None
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE snapshot=? AND id=? AND visibility='visible'", (scope.snapshot, record_id)).fetchone()
        if not row:
            return None
        record = Record.model_validate_json(row[0])
        return scoped_details(record,permitted,strict_history=scope.strict_history) if all(s.document_id in permitted for s in record.refs) else None

    def eligible_sql(self, scope: Scope, alias: str = "r") -> tuple[str, list]:
        permitted = sorted(self.permitted_documents(scope))
        if not permitted:
            return "0", []
        marks = ",".join("?" for _ in permitted)
        return (f"{alias}.snapshot=? AND {alias}.visibility='visible' AND NOT EXISTS "
                f"(SELECT 1 FROM record_sources rs WHERE rs.snapshot={alias}.snapshot AND rs.record_id={alias}.id AND rs.document_id NOT IN ({marks}))",
                [scope.snapshot, *permitted])

    def list_records(self, scope: Scope, kind: str | None = None) -> list[Record]:
        where, params = self.eligible_sql(scope)
        if kind:
            where += " AND r.kind=?"
            params.append(kind)
        with self.connect() as db:
            rows = db.execute(f"SELECT r.payload FROM records r WHERE {where} ORDER BY r.id", params).fetchall()
        permitted=self.permitted_documents(scope)
        return [scoped_details(Record.model_validate_json(row[0]),permitted,strict_history=scope.strict_history) for row in rows]

    def _original_pages(self, scope):
        where, params = self.eligible_sql(scope)
        selected = (" FROM records r JOIN record_sources s ON s.snapshot=r.snapshot AND s.record_id=r.id "
                    "WHERE r.kind='block' AND r.id=s.document_id || ':p' || s.page "
                    "AND json_array_length(r.payload,'$.refs')=1 AND " + where)
        return selected,params

    def first_visible_pages(self,scope):
        selected,params = self._original_pages(scope)
        with self.connect() as db:
            return dict(db.execute('SELECT s.document_id,min(s.page)'+selected+' GROUP BY s.document_id',params))

    def original_page_slice(self, scope: Scope, offset: int, limit: int, *, document_id: str | None = None):
        selected,params = self._original_pages(scope)
        if document_id is not None:
            selected += ' AND s.document_id=?'
            params = [*params,document_id]
        with self.connect() as db:
            total = db.execute('SELECT count(*)' + selected, params).fetchone()[0]
            rows = db.execute('SELECT r.payload' + selected + ' ORDER BY s.document_id,s.page LIMIT ? OFFSET ?',
                              [*params, limit, offset]).fetchall() if limit else []
        permitted = self.permitted_documents(scope)
        return total, [scoped_details(Record.model_validate_json(row[0]), permitted, strict_history=scope.strict_history) for row in rows]

    def related(self, scope: Scope, record_id: str) -> list[Relation]:
        if not self.get(scope, record_id):
            return []
        allowed = self.permitted_documents(scope)
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM relations WHERE snapshot=? AND (source=? OR target=?)", (scope.snapshot, record_id, record_id)).fetchall()
        result = []
        for row in rows:
            edge = Relation.model_validate_json(row[0])
            if all(s.document_id in allowed for s in edge.refs) and self.get(scope, edge.source) and self.get(scope, edge.target):
                result.append(edge)
        return result
