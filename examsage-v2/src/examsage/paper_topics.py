"""Attach a course maintainer's study labels only within a verified original question."""
from functools import lru_cache
from importlib.resources import files
import json
import re

from .numbered_pages import locate_numbered_span


@lru_cache(maxsize=1)
def _catalog():
    return json.loads(files('examsage').joinpath('paper_topics.json').read_text(encoding='utf-8'))


def index_paper_topics(document, blocks, events):
    edition = _catalog().get(document.sha256)
    if document.kind != 'exam' or not edition or document.exam_year != edition['exam_year']:
        return []
    checked = []
    pages = {b.refs[0].page: b for b in blocks if b.visibility == 'visible'
             and b.details.get('extraction_status') != 'failed'}
    for item in edition['annotations']:
        number, page = item['number'], item['page']
        block = pages.get(page)
        span = locate_numbered_span(events, number, document.pages, question=True)
        if block is None or span is None:
            continue
        start, _, end = span
        if not start['page'] <= page <= end['page']:
            continue
        raw = block.details['raw_text']
        excerpt = raw[start['offset'] if page == start['page'] else 0:
                      end['offset'] if page == end['page'] else len(raw)]
        quote = item['quote']
        if quote not in ' '.join(excerpt.split()):
            continue
        if item['origin'] == 'printed_title':
            if page != start['page']:
                continue
            line = ' '.join(excerpt.lstrip().splitlines()[0].split())
            if not re.fullmatch(re.escape(number) + r'[.)]\s*' + re.escape(quote), line):
                continue
        checked.append({
            'page': page, 'question_start_page': start['page'],
            'number': number, 'topic': item['topic'], 'quote': quote,
            'label_origin': item['origin'], 'annotation_date': edition['annotation_date'],
        })
    return checked


def structured_topic_metadata(manifest, records, database):
    """Bind the edition's checked quotes to the shared snapshot's actual parent IDs."""
    from io import BytesIO

    from .numbered_pages import index_numbered_pages, pdf_layouts
    from .page_image import verified_source_bytes

    index = {}
    for doc in manifest.documents:
        edition = _catalog().get(doc.sha256)
        if doc.kind != 'exam' or not edition or doc.exam_year != edition['exam_year']:
            continue
        blocks = [r for r in records if r.kind == 'block' and len(r.refs) == 1
                  and r.refs[0].document_id == doc.id and r.id == f'{doc.id}:p{r.refs[0].page}']
        blocks.sort(key=lambda r:r.refs[0].page)
        content = verified_source_bytes(database,doc)
        layouts = pdf_layouts(BytesIO(content),blocks)
        events = index_numbered_pages(blocks,layouts,question_paper=True,page_count=doc.pages)
        entries = index_paper_topics(doc, blocks, events)
        if len(entries) != len(edition['annotations']):
            raise ValueError('Checked topic evidence does not match these original question spans')
        parents = {}
        for q in records:
            if (q.kind == 'question' and q.parent_id is None and q.visibility == 'visible'
                    and q.details.get('exam_year') == doc.exam_year and {r.document_id for r in q.refs} == {doc.id}):
                number = str(q.details.get('number'))
                if number in parents:
                    raise ValueError('Ambiguous shared parent number')
                parents[number] = q
        for item in entries:
            parent = parents.get(item['number'])
            if parent is None or not {item['page'],item['question_start_page']} <= {r.page for r in parent.refs}:
                raise ValueError('Shared question and verified PDF locations disagree')
            item['question_id'] = parent.id
        index[doc.id] = entries
    return {'paper_topic_documents':sorted(index),'paper_topic_evidence':index} if index else {}
