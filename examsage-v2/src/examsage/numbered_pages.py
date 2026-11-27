"""Page locators for uncurated, explicitly dated uploads. No official answer edges are created."""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import re
import unicodedata
from threading import Lock

from .domain import Bundle
from .exam_outlook import ambiguous_exam_documents, paper_year


_ROOT = re.compile(r'^(?:question\s+(\d{1,3})\b|(\d{1,3})[.)]\s*question\b|第\s*(\d{1,3})\s*题)',re.I)
_DOTTED = re.compile(r'^(?:Q\s*)?(\d{1,3})\.([a-z]+(?:\.[a-z]+)*)[.)](?=\s|$)',re.I)
_FULL = re.compile(r'^(?:(?:Q(?:uestion)?\s*)?(\d{1,3})|第\s*(\d{1,3})\s*题)((?:\s*\([a-z]+\))+)(?=\s|[:.)]|$)',re.I)
_SECTION = re.compile(r'^Part\s+([A-Z])\s*[:.]?$',re.I)
_SUB = re.compile(r'^\(?([a-z]{1,4})\)',re.I)
_ROMAN = {'i','ii','iii','iv','v','vi','vii','viii','ix','x'}
_NUMBER = re.compile(r'^(\d{1,3})[.)]\s+(?:(\(?[a-z]{1,4}\))(?=\s|$))?', re.I)
_EXAMPLES = re.compile(r'\b(?:include|includes|including|for example|examples)\s*:\s*$', re.I)
_STEPS = re.compile(r'\b(?:steps|locations|items|examples)\s*[.:]\s*$', re.I)
_INSTRUCTIONS = re.compile(r"(?:(?:(?:candidate[s’']*|general|exam(?:ination)?)\s+)?instructions?(?:\s+(?:to|for)\s+(?:the\s+)?candidates?)?)\s*:?", re.I)
_INLINE_NUMBER = re.compile(r'(?:[ \t]{2,}|(?<=[.!?])[ \t]+)\d{1,3}[.)]\s+\S')
_FOLIO = re.compile(r'(?:[—–-]\s*\d+\s*[—–-]|page\s+\d+\s+of\s+\d+)', re.I)
NUMBERING_VERSION = 2


# Only a line start establishes a target. A second apparent label inside
# prose can be an adjacent question or a cross-reference; neither warrants
# attributing the rest of that line to a single requested answer.
_INLINE_LABEL = re.compile(
    r'(?<=\s)(?:(?:Q(?:uestion)?\s*)?\d{1,3}\.(?:[a-z]+\.)*[a-z]+[.)]'
    r'|(?:Q(?:uestion)?\s*)?\d{1,3}(?:\([a-z]+\))+)(?=\s|[:.)]|$)'
    r'|(?<=[ \t])\((?:[ivx]{1,4})\)(?=[ \t]+\S)'
    r'|(?<=[ \t])(?:\([a-z]\)|[ivx]{1,4}\))(?=[ \t]+[+\-−]?(?:\d|[.,]\d))'
    r'|(?:[ \t]{2,}|(?<=[.!?。！？;；:：])[ \t]+)(?:\((?:[a-z]|[ivx]{1,4})\)|[ivx]{1,4}\))(?=\s+\S)', re.I)


def _has_inline_label(text, question_paper=False):
    for line in text.splitlines():
        line = unicodedata.normalize('NFKC', line).strip()
        head = _DOTTED.match(line) or _FULL.match(line) or _ROOT.match(line)
        if question_paper and head is None:
            head = _NUMBER.match(line)
        if question_paper and _INLINE_NUMBER.search(line, head.end() if head else 0):
            return True
        if _INLINE_LABEL.search(line, head.end() if head else 0):
            return True
    return False


def _marker(line):
    text = unicodedata.normalize('NFKC',line).strip()
    match = _DOTTED.match(text)
    if match:
        return 'full', [str(int(match[1])),*match[2].lower().split('.')]
    match = _FULL.match(text)
    if match:
        return 'full', [str(int(match[1] or match[2])),*re.findall(r'[a-z]+',match[3].lower())]
    match = _ROOT.match(text)
    if match:
        return 'root', [str(int(next(n for n in match.groups() if n)))]
    match = _SECTION.match(text)
    if match:
        return 'section', [match[1].lower()]
    match = _SUB.match(text)
    if match:
        return 'sub', [match[1].lower()]
    if re.match(r'^(?:(?:Q(?:uestion)?\s*|第\s*)\d+\b|\d+\s*[.)](?!\d)|\d+\s*\(|\([a-z\d]{1,4}\)|[a-z]{1,3}[.:]\s+|Part\s+[A-Z]\b|Section\s+\w+\b|Appendix\b|End of (?:paper|exam|questions|solutions))',text,re.I):
        return 'boundary', []
    return None


def _compact_offsets(words, raw):
    # Some PDF layouts split words or punctuation. Map only whitespace
    # differences back to printed character positions in the canonical page.
    needle = ''.join(words)
    positions = [i for i, ch in enumerate(raw) if not ch.isspace()]
    compact = ''.join(raw[i] for i in positions)
    offsets = []
    for m in re.finditer(re.escape(needle), compact):
        start = positions[m.start()]
        if not start or raw[start-1].isspace():
            offsets.append(start)
    return offsets


@dataclass
class _PrintedList:
    instructions: bool = False
    previous: str = ''
    indent: int | None = None
    style: str | None = None


def _page_markers(raw, layout, number_margin=None, state=None):
    lines = (layout or raw).splitlines(keepends=True)
    found = []
    raw_offset = 0
    state = state if state is not None else _PrintedList()
    for line in lines:
        stripped = line.strip()
        if _FOLIO.fullmatch(stripped) or stripped.upper()=='PAPER CONTINUES ON NEXT PAGE':
            raw_offset += len(line)
            continue
        indent = len(line.expandtabs()) - len(line.expandtabs().lstrip())
        mark = _marker(line)
        if _INSTRUCTIONS.fullmatch(stripped):
            state.instructions = True
            mark = ('boundary', [])
        elif re.match(r'^(?:section\b|question\s+\d+\b)',stripped,re.I):
            state.instructions = False
        number = _NUMBER.match(stripped) if number_margin is not None else None
        style = 'number' if number else 'letter' if mark and mark[0]=='sub' else None
        if state.instructions and number_margin is not None and style:
            mark = None
        elif number_margin is not None and style and indent > number_margin and (
                (state.indent, state.style) == (indent, style) or
                ((state.previous.endswith(':') or _STEPS.search(state.previous)) if number else _EXAMPLES.search(state.previous))):
            state.indent, state.style = indent, style
            mark = None
        elif stripped:
            if style or mark or (state.indent is not None and indent < state.indent):
                state.indent = state.style = None
            if number and indent == number_margin and mark and mark[0]=='boundary':
                parts = [str(int(number[1]))]
                if number[2]:
                    parts.append(number[2].strip('()').lower())
                    indent += number.start(2)
                mark = ('numeric_root', parts)
            elif number and indent!=number_margin and mark and mark[0]=='boundary':
                mark = ('gap', [])
        if _has_inline_label(line, question_paper=number_margin is not None):
            mark = ('ambiguous_root', mark[1][:1]) if mark and mark[0]=='numeric_root' else ('gap', [])
        if stripped:
            state.previous = stripped
        if mark:
            if not layout:
                offsets = [raw_offset + len(line)-len(line.lstrip())]
            else:
                words = line.split()[:5]
                pattern = r'(?<!\S)' + r'\s+'.join(re.escape(w) for w in words) + r'(?!\S)'
                offsets = [m.start() for m in re.finditer(pattern,raw)]
                if not offsets:
                    offsets = _compact_offsets(words, raw)
            if not offsets:
                return None
            found.append(((*mark, indent),offsets))
        raw_offset += len(line)
    # All layout markers must have exactly one order-preserving alignment in
    # the original text, including isolated i)/ii) labels repeated on the page.
    first, last = [], []
    bound = -1
    for _,offsets in found:
        bound = next((pos for pos in offsets if pos>bound),None)
        if bound is None:
            return None
        first.append(bound)
    bound = len(raw)+1
    for _,offsets in reversed(found):
        bound = next((pos for pos in reversed(offsets) if pos<bound),None)
        if bound is None:
            return None
        last.append(bound)
    if first!=last[::-1]:
        return None
    return [(mark,pos) for (mark,_),pos in zip(found,first)]


def pdf_layouts(source, blocks):
    from pypdf import PdfReader
    reader = PdfReader(source)
    layouts = {}
    for block in blocks:
        if block.visibility == 'visible' and block.details.get('extraction_status') != 'failed':
            page = block.refs[0].page
            try:
                layouts[page] = reader.pages[page-1].extract_text(extraction_mode='layout')
            except Exception:
                # An optional layout extraction may fail on unsupported fonts.
                # Original-page extraction retains its separate status.
                continue
    return layouts


def index_numbered_pages(blocks, layouts, *, page_count=None, question_paper=False):
    events = []
    root = section = letter = None
    previous_page = 0
    margin = None
    if question_paper:
        margin = min((len(line)-len(line.lstrip()) for block in blocks
                      if block.visibility=='visible' and block.details.get('extraction_status')!='failed'
                      for line in (layouts.get(block.refs[0].page) or block.details.get('raw_text') or '').expandtabs().splitlines()
                      if _NUMBER.match(line.strip())), default=None)
    numeric = False
    hierarchy = []
    inline_family = None
    printed_list = _PrintedList()
    for block in blocks:
        if block.visibility == 'notes':
            continue
        page = block.refs[0].page
        if page > previous_page + 1:
            events.append({'page': previous_page + 1, 'offset': 0, 'path': '', 'gap': True})
            root = section = letter = None
            printed_list = _PrintedList()
        previous_page = page
        raw = block.details.get('raw_text') or ''
        marks = None
        if block.visibility=='visible' and block.details.get('extraction_status')!='failed' and raw.strip():
            marks = _page_markers(raw,layouts.get(page),margin,printed_list)
        if marks is None:
            events.append({'page':page,'offset':0,'path':'','gap':True})
            root = section = letter = None
            printed_list = _PrintedList()
            continue
        for (typ,parts,indent),offset in marks:
            path = []
            if typ != 'sub' and typ != 'numeric_root':
                numeric = False
            if typ in {'ambiguous_root','gap'}:
                if typ=='ambiguous_root':
                    events.append({'page':page,'offset':offset,'path':parts[0]})
                events.append({'page':page, 'offset':offset, 'path':'', 'gap':True})
                root = section = letter = None
                continue
            if typ=='boundary':
                root = section = letter = None
            elif typ=='numeric_root':
                root, section, letter = parts[0], None, None
                path = parts
                numeric = True
                hierarchy = []
                inline_family = None
                if len(parts)>1:
                    events.append({'page':page,'offset':offset,'path':root})
                    # The first inline part is at the first level, even when
                    # its alignment on the printed line differs from siblings.
                    hierarchy.append((indent,parts[1]))
                    inline_family = parts[1] in _ROMAN
            elif typ=='full':
                path = parts
                root = parts[0]
                parents = parts[1:-1] if parts[-1] in _ROMAN else parts[1:]
                section = parents[-2] if len(parents)>=2 else None
                letter = parents[-1] if parents else None
            elif typ=='root':
                root, section, letter = parts[0], None, None
                path = [root]
            elif root:
                label = parts[0]
                if numeric:
                    while hierarchy and hierarchy[-1][0]>=indent:
                        hierarchy.pop()
                    if len(hierarchy)==1 and inline_family is not None and (label in _ROMAN)==inline_family:
                        hierarchy.clear()
                    if not hierarchy:
                        inline_family = None
                    hierarchy.append((indent,label))
                    path = [root, *(value for _,value in hierarchy)]
                elif typ=='section':
                    section, letter = label, None
                    path = [root,section]
                elif label in _ROMAN:
                    if letter != 'h':
                        path = [v for v in [root,section,letter,label] if v]
                elif len(label)==1:
                    letter = label
                    path = [v for v in [root,section,letter] if v]
                else:
                    root = section = letter = None
            events.append({'page':page,'offset':offset,'path':'.'.join(path)})
    if page_count is not None and previous_page < page_count:
        events.append({'page': previous_page + 1, 'offset': 0, 'path': '', 'gap': True})
    return events


def locate_numbered_span(events,key,last_page,question):
    hits = [i for i,event in enumerate(events) if event['path']==key]
    if len(hits)!=1:
        return None
    i = hits[0]
    leaf = events[i]
    following = (event for event in events[i+1:] if not event['path'].startswith(key+'.'))
    end = next(following, {'page':last_page+1,'offset':0})
    if end.get('gap'):
        return None
    # Preserve earlier sibling conditions within the same root, including
    # values a later subquestion may inherit. Keep a fully qualified stand-alone
    # label usable when the document provides no preceding root heading.
    start = leaf
    if question:
        root = key.split('.')[0]
        # A fully qualified leaf restores its number, but it cannot restore
        # missing parent conditions. A new explicit root starts a fresh span.
        for prior in reversed(events[:i] if key!=root else []):
            if prior['path'] == root:
                break
            if prior.get('gap'):
                return None
        for prior in reversed(events[:i]):
            if not prior['path'] or prior['path'].split('.')[0]!=root:
                break
            start = prior
    return start,leaf,end


def _excerpts(store,scope,doc,span,key,role,limit,max_chars,selection):
    start,leaf,end = span
    last = min(doc.pages,end['page'] if end['offset'] else end['page']-1)
    if last-start['page']+1 > limit:
        return None
    result = []
    for page in range(start['page'],last+1):
        row = store.get(scope,f'{doc.id}:p{page}')
        if (row is None or row.kind!='block' or len(row.refs)!=1 or
                (row.refs[0].document_id,row.refs[0].page)!=(doc.id,page)):
            return None
        raw = row.details.get('raw_text')
        if not isinstance(raw,str) or row.details.get('extraction_status')=='failed':
            return None
        low = start['offset'] if page==start['page'] else 0
        high = end['offset'] if page==end['page'] else len(raw)
        if page >= leaf['page']:
            leaf_start = leaf['offset'] if page == leaf['page'] else low
            if _has_inline_label(raw[leaf_start:high], question_paper=role=='question'):
                return None
        body = raw[low:high].strip()
        if not body or _FOLIO.fullmatch(body):
            continue
        info = {'locator_role':role,'numbered_path':key,'label_page':leaf['page'],
                'label_offset':leaf['offset'],'source_kind':doc.kind,'exam_year':doc.exam_year}
        if row.details.get('source_reviews'):
            info['source_reviews'] = row.details['source_reviews']
        if selection:
            info.update(selection_basis='request_only', requested_exam_year=selection.exam_year)
        year_title = f'本次选卷 {selection.exam_year}' if selection else str(doc.exam_year)
        projected = row.model_copy(update={'title':f'{year_title} · {key} · {PurePosixPath(doc.relative_path).name}',
                                           'text':body,'details':info})
        if len(projected.model_dump_json()) > max_chars:
            return None
        max_chars -= len(projected.model_dump_json())
        result.append(projected)
    return result


# Immutable snapshot and caller scope select the canonical page records. Only
# offsets and numbering are retained here. Authorization is rechecked on each
# call, and PDF layout always refers to bytes matching the manifest digest.
_legacy_events = OrderedDict()
_legacy_lock = Lock()


def _existing_document_events(store, scope, doc, *, question_paper=False):
    from .page_image import verified_source_bytes
    from pypdf.errors import PyPdfError

    pdf = None
    if PurePosixPath(doc.relative_path).suffix.lower() == '.pdf':
        try:
            pdf = verified_source_bytes(store.path, doc)
        except (OSError, ValueError, RuntimeError):
            return []
    cache_key = (str(store.path.resolve()), scope.model_dump_json(), doc.id, doc.sha256, question_paper)
    with _legacy_lock:
        if cache_key in _legacy_events:
            _legacy_events.move_to_end(cache_key)
            return _legacy_events[cache_key]
    _, blocks = store.original_page_slice(scope, 0, doc.pages, document_id=doc.id)
    try:
        layouts = pdf_layouts(BytesIO(pdf), blocks) if pdf is not None else {}
    except (PyPdfError, OSError, ValueError, IndexError, RecursionError):
        return []
    events = index_numbered_pages(blocks, layouts, page_count=doc.pages, question_paper=question_paper)
    if len(events) <= 4096:
        with _legacy_lock:
            _legacy_events[cache_key] = events
            if len(_legacy_events) > 32:
                _legacy_events.popitem(last=False)
    return events


def _document_events(store, scope, doc, metadata, *, question, selected=False):
    index = metadata.get('numbered_page_index')
    if (index is None or
            (question and index.get(doc.id) and metadata.get('numbered_page_version',1)<NUMBERING_VERSION) or
            (selected and doc.id not in index and (doc.kind=='unknown' or doc.exam_year is None))):
        return _existing_document_events(store,scope,doc,question_paper=question)
    return index.get(doc.id,[])


def own_question_excerpts(store, scope, doc, events, key):
    """Only the numbered item's own text, before its first child or next sibling."""
    span = locate_numbered_span(events,key,doc.pages,question=True)
    if span is None:
        return []
    _, leaf, end = span
    position = events.index(leaf) + 1
    if position < len(events):
        end = events[position]
    if end.get('gap') or (leaf['page'],leaf['offset']) >= (end['page'],end['offset']):
        return []
    return _excerpts(store,scope,doc,(leaf,leaf,end),key,'question',doc.pages,200000,None) or []


def original_question_pages(store, scope, doc, metadata, already_located):
    """Locate remaining whole questions for a retrospective audit of a selected exam."""
    events = _document_events(store,scope,doc,metadata,question=True)
    numbers = {e['path'] for e in events if e['path'].isdecimal()} - already_located
    for number in sorted(numbers):
        span = locate_numbered_span(events,number,doc.pages,True)
        if span and _excerpts(store,scope,doc,span,number,'question',doc.pages,200000,None):
            yield number, span[1]['page']


def _selected_documents(documents, allowed, excluded, selection):
    by_id = {d.id: d for d in documents if d.id in allowed}
    chosen = {}
    for role, doc_id in [('exam', selection.paper_id), ('exam_solution', selection.solution_id)]:
        if doc_id is None:
            continue
        doc = by_id.get(doc_id)
        if doc is None or doc.id in excluded or any(d.sha256 == doc.sha256 for d in chosen.values()):
            return None
        for copy in documents:
            if copy.sha256 != doc.sha256:
                continue
            if copy.id in excluded or copy.kind not in {'unknown', role} or copy.exam_year not in {None, selection.exam_year}:
                return None
            # An explicit role/year here must also respect a contradictory academic-year label.
            if paper_year(copy.model_copy(update={'exam_year': selection.exam_year}))[0] != selection.exam_year:
                return None
        chosen[role] = doc
    return chosen


def numbered_sources(store,scope,metadata,year,number,part,with_answer,limit,max_chars,*,selection=None):
    bundle = Bundle(snapshot=scope.snapshot,mode='numbered_source_pages',sufficiency='insufficient')
    allowed = store.permitted_documents(scope)
    manifest = store.manifest(scope)
    index = metadata.get('numbered_page_index')
    excluded = set(metadata.get('ambiguous_solution_documents', ())) | set(metadata.get('ambiguous_paper_documents', ()))
    if index is None:
        for kind in ('exam', 'exam_solution'):
            excluded.update(ambiguous_exam_documents(manifest.documents, kind))
    groups = defaultdict(dict)
    excerpt_scope = scope
    if selection:
        bundle.mode = 'selected_numbered_source_pages'
        chosen = _selected_documents(manifest.documents, allowed, excluded, selection)
        if chosen is None:
            bundle.limitations.append('请重新选择两份不同的可见资料，并核对已经登记的类别与考年。')
            return bundle
        # Keep third-file notes and solution-supported annotations out of a
        # question-only response. The caller still issues the original page's citation.
        selected_ids = [doc.id for kind, doc in chosen.items() if kind=='exam' or with_answer]
        excerpt_scope = scope.model_copy(update={'allowed_sources':selected_ids})
        for kind, doc in chosen.items():
            groups[kind][doc.sha256] = doc
        bundle.limitations.append('考年及文件用途按本次选择处理。请对照原页确认卷别、题意与数值。')
    else:
        for doc in manifest.documents:
            if doc.id in excluded:
                continue
            if (doc.id in allowed and doc.kind in {'exam','exam_solution'} and doc.exam_year==year
                    and paper_year(doc)[0]==year):
                groups[doc.kind].setdefault(doc.sha256,doc)
    key = number+'.'+part if part else number
    for kind,role in [('exam','question'),('exam_solution','answer_candidate')]:
        if kind=='exam_solution' and not with_answer:
            break
        candidates = list(groups[kind].values())
        span = None
        if len(candidates)==1:
            doc = candidates[0]
            events = _document_events(store,excerpt_scope,doc,metadata,question=kind=='exam',selected=selection is not None)
            span = locate_numbered_span(events,key,doc.pages,kind=='exam')
        if not candidates:
            if selection:
                bundle.limitations.append('本次只选了试卷。需要解答时，请再选择对应的答案文件。')
                return bundle
            label = '真题' if kind == 'exam' else '答案'
            bundle.limitations.append(f'当前可见资料中没有可唯一归入 {year} 年的{label}文件。请在“试卷与练习”核对原件、资料类型和考年。')
            return bundle
        if span is None:
            bundle.limitations.append('当前可见原卷缺少唯一的小问位置，请核对考年、版本、小问编号和父题缺页。'
                if kind=='exam' else '当前答案资料缺少唯一、完整编号的小问线索，请核对版本和原件。')
            return bundle
        rows = _excerpts(store,excerpt_scope,doc,span,key,role,limit,max_chars,selection)
        if not rows:
            bundle.limitations.append('完整引用超出本次范围或有原页缺口，请逐页核查。')
            return bundle
        bundle.records.extend(rows)
        limit -= len(rows)
        max_chars -= sum(len(r.model_dump_json()) for r in rows)
    bundle.sufficiency = 'unassessed'
    bundle.limitations.append('原卷摘录保留本大题此前的可见条件，可能包含前序小问。涉及图表和公式时请核对原图。')
    if with_answer and not selection:
        bundle.limitations.append('答案候选按上传者登记的考年和卷面完整小问编号定位。版本、题意、数值及官方评分须另行核对。')
    return bundle
