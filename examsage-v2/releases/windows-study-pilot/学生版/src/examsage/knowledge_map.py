"""Ground a host-authored topic hierarchy in the visible, extracted original pages."""
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints

from .domain import digest
from .source_reviews import review_warnings


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Quote(StrictModel):
    document_id: str = Field(min_length=1, max_length=200)
    page: StrictInt = Field(ge=1, le=100000)
    quote: str = Field(min_length=1, max_length=400)


class Topic(StrictModel):
    id: str = Field(pattern=r'^[a-z0-9_-]{1,64}$')
    parent: str = Field(pattern=r'^[a-z0-9_-]{0,64}$')
    kind: Literal['topic','method','application','worked_example']
    title: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=160)]
    summary: Annotated[str, StringConstraints(strip_whitespace=True,min_length=1,max_length=800)]
    support: list[Quote] = Field(min_length=1,max_length=6)


class MapProposal(StrictModel):
    nodes: list[Topic] = Field(min_length=1,max_length=30)


def original_text_field(details):
    """Identify extracted source text without promoting later commentary to an original."""
    if details.get('extraction_status') == 'failed':
        return None
    if details.get('raw_text') is not None:
        return 'raw_text' if isinstance(details['raw_text'],str) else None
    return None if details.get('visual_review') or details.get('supplement') else 'text'


def extracted_text(record):
    field = original_text_field(record.details)
    if field=='raw_text':
        return record.details['raw_text']
    return record.text if field=='text' and isinstance(record.text,str) else ''


def raw_text(record):
    return ' '.join(extracted_text(record).split())


def browse_materials(store, scope, offset, course_id=None):
    if type(offset) is not int or not 0 <= offset <= 10_000_000:
        raise ValueError('Invalid page offset')
    total, records = store.original_page_slice(scope, offset, 12)
    docs = {d.id:d for d in store.manifest(scope).documents}
    pages = []
    for record in records:
        ref = record.refs[0]
        text = raw_text(record)
        pages.append({'document_id': ref.document_id, 'page': ref.page,
                      'filename': PurePosixPath(docs[ref.document_id].relative_path).name,
                      'excerpt':text[:1400], 'more_text':len(text)>1400,
                      'extraction_status':record.details.get('extraction_status','unknown')})
    end = offset + len(pages)
    return {'course_id':course_id or scope.course, 'snapshot':scope.snapshot,
            'scope_digest':digest(scope.model_dump(mode='json')), 'visible_pages':total, 'pages':pages,
            'next_offset':end if end < total else None}


def prepare_map(store, scope, course_id, proposal):
    nodes = MapProposal.model_validate(proposal).nodes
    parents = {n.id:n.parent for n in nodes}
    if len(parents) != len(nodes):
        raise ValueError('Duplicate topic id')
    for node in nodes:
        current, seen = node.id, set()
        while current:
            if current not in parents or current in seen:
                raise ValueError('Invalid topic parent or cycle')
            seen.add(current)
            current = parents[current]
    docs = {d.id:d for d in store.manifest(scope).documents}
    allowed = store.permitted_documents(scope)
    pages, output = {}, []
    for node in nodes:
        support, warnings = [], []
        for q in node.support:
            key = q.document_id, q.page
            if key not in pages:
                doc = docs.get(q.document_id)
                if doc is None or doc.id not in allowed or q.page > doc.pages:
                    raise ValueError('Source page unavailable')
                record = store.get(scope, f'{doc.id}:p{q.page}')
                if (not record or record.kind!='block' or len(record.refs)!=1
                        or (record.refs[0].document_id,record.refs[0].page)!=key):
                    raise ValueError('Source page unavailable')
                sid = 'src_' + digest([course_id, scope.model_dump(mode='json'), digest(record.model_dump(mode='json'))])
                warning = list(record.limitations) + review_warnings(record.details.get('source_reviews',[]))
                warning.extend((record.details.get('visual_review') or {}).get('warnings',[]))
                pages[key] = raw_text(record), sid, warning
            text, sid, page_warnings = pages[key]
            quote = ' '.join(q.quote.split())
            if not quote or quote not in text:
                raise ValueError('Quote not found in extracted original page')
            support.append({'document_id':q.document_id,'page':q.page,'quote':quote,'source_id':sid,
                            'filename':PurePosixPath(docs[q.document_id].relative_path).name,
                            'sha256':docs[q.document_id].sha256})
            warnings.extend(page_warnings)
        output.append({**node.model_dump(exclude={'support'}), 'support':support,
                       'limitations':list(dict.fromkeys(warnings))})
    total, _ = store.original_page_slice(scope, 0, 0)
    return {'schema_version':'knowledge-map-v1','course_id':course_id,'snapshot':scope.snapshot,
            'scope_digest':digest(scope.model_dump(mode='json')),
            'validation':'quotes_matched_semantic_review_pending',
            'coverage':{'cited_pages':len(pages),'visible_pages':total}, 'nodes':output}
