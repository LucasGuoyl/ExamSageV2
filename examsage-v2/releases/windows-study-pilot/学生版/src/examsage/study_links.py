"""Resolve the direct evidence and related readings for a single saved paragraph."""
import re
from pathlib import PurePosixPath

from .domain import digest
from .knowledge_map import extracted_text
from .numbered_pages import NUMBERING_VERSION, _document_events, own_question_excerpts
from .page_image import is_original_page
from .study_reader import _document, completed_answer, read_original


TEACHING = {'lecture', 'textbook', 'formula_sheet'}
MAX_RELATED = 8
WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
# English compounds must be uninterrupted, content-bearing words. Keep “of”
# inside a term (e.g. “coefficient of performance”), never as its endpoint.
STOP = set("""a an and are as at be by calculate calculated can consider could data describe determine discuss
does each equation example exam exercise explain explained for formula from given gives has have how if in
into is it its may model must not obtain of on or our part problem provided question read result same
see should show shown solution solve state student study such than that the their them then therefore these
this those to two under unit units use used uses using value values was we were what when where which will
with would you your large small following original first second next general different based material
materials assume assuming assumptions conditions answer answers page pages lecture lectures notes method
find write derived derivation derive compare defined called term required figure table
numbers previous case cases unknown quantity quantities system systems rate total according analysis known
information evidence facts discussed course text context common passage sourcefile""".split())
CHINESE_TERM = re.compile(
    r"[\u3400-\u9fff]{1,10}(?:定律|定理|方程|效应|系数|定则|假说|模型|阻抗|原理|理论|主义|运动|革命|战争|协定|条约|意象|修辞)")
QUESTION = re.compile(r"[0-9]+(?:\.(?:[0-9]+|[a-z]+))*")


def _terms(text, source):
    """Derive exact phrases shared by this paragraph and its own source. Never score question numerals."""
    terms = set()
    lower = source.lower()
    words = list(WORD.finditer(text))
    for i, word in enumerate(words):
        if word[0].lower() in STOP:
            continue
        for end in range(i + 1, min(i + 5, len(words))):
            between = text[words[end-1].end():words[end].start()]
            if between not in {' ', '-'}:
                break
            value = words[end][0].lower()
            if value in STOP and value != 'of':
                break
            phrase = text[word.start():words[end].end()].lower()
            if value != 'of' and len(phrase) >= 8 and phrase in lower:
                terms.add(phrase)
    for match in CHINESE_TERM.finditer(text):
        # Chinese articles/conjunctions need not be identical around the term.
        candidates = (match[0][i:] for i in range(max(0, len(match[0])-10), len(match[0])-3))
        shared = next((part for part in candidates if part in source), '')
        if shared:
            terms.add(shared)
    return sorted(terms, key=lambda t: (-len(t), t))[:12]


def _matches(text, terms):
    alternatives = [r'(?<![a-z])' + re.escape(term) + r'(?![a-z])' if WORD.match(term)
                    else re.escape(term) for term in terms]
    return re.finditer('|'.join(alternatives), text, re.I) if alternatives else iter(())


TABLE_NUMBER = re.compile(r'[+−-]?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?')


def _table_row(literal, claim):
    """Identify a unique printed numeric row inside this citation, preserving its exact text."""
    def normalize(token):
        return token.replace(',', '').replace('−', '-').lstrip('+')

    # Single-digit question/page/row numbers carry little evidence on their own.
    values = {normalize(m[0]) for m in TABLE_NUMBER.finditer(claim)
              if len(normalize(m[0]).lstrip('-')) > 1}
    if len(values) < 2:
        return ''
    candidates = []
    for line in literal.splitlines():
        cells = line.split()
        if 2 <= len(cells) <= 16 and all(TABLE_NUMBER.fullmatch(cell) for cell in cells):
            hits = len(values.intersection(normalize(cell) for cell in cells))
            if hits >= 2:
                candidates.append((hits, line.strip()))
    candidates.sort(reverse=True)
    if candidates and (len(candidates) == 1 or candidates[0][0] > candidates[1][0]):
        return candidates[0][1]
    return ''


def _excerpt(raw, match, *, limits=None):
    """A short, contiguous piece of the physical page around the match."""
    start, end = match.span()
    lo = max(raw.rfind('\n', 0, start)+1, start-68)
    line_end = raw.find('\n', end)
    hi = min(len(raw) if line_end < 0 else line_end, end+110)
    if limits is not None:
        lo, hi = max(lo, limits[0]), min(hi, limits[1])
    return raw[lo:hi].strip()


def _label(path):
    if not isinstance(path, str) or not QUESTION.fullmatch(path):
        return None
    head, *rest = path.split('.')
    return 'Q' + head + ''.join('('+part+')' for part in rest)


def _record_label(record, doc):
    if not record or (record.kind, doc.kind) not in {('question','exam'),('answer','exam_solution')}:
        return None
    number = str(record.details.get('number',''))
    part = record.details.get('part')
    return _label(number + ('.' + str(part) if part else ''))


def _page(store, scope, doc, number):
    if type(number) is int and 1 <= number <= doc.pages:
        record = store.get(scope, f'{doc.id}:p{number}')
        if is_original_page(record, doc.id, number):
            return record
    return None


def _item(run, index, doc, page, relationship, quote, basis, *, question=None, **extra):
    key = digest([run, index, relationship, doc.id, page, question, extra])
    return {'key':key, 'relationship':relationship, 'document_id':doc.id,
            'filename':PurePosixPath(doc.relative_path).name, 'page':page, 'kind':doc.kind,
            'exam_year':doc.exam_year, 'question':question, 'quote':quote, 'basis':basis, **extra}


def _direction(doc):
    if doc.kind == 'exam':
        return TEACHING
    return {'exam'} if doc.kind in TEACHING else set()


def _question_at(store, scope, doc, metadata, number, match, raw):
    """Only the numbered item's OWN passage may establish that a term is tested here."""
    if doc.kind != 'exam' or metadata.get('numbered_page_version') != NUMBERING_VERSION:
        return None, None
    events = metadata.get('numbered_page_index',{}).get(doc.id,[])
    prior = [e for e in events if (e['page'],e['offset']) <= (number,match.start())]
    if not prior or not prior[-1].get('path'):
        return None, None
    path = prior[-1]['path']
    for record in own_question_excerpts(store,scope,doc,events,path):
        if record.refs[0].page != number or not record.text:
            continue
        start = raw.find(record.text)
        if (start >= 0 and raw.count(record.text)==1 and start <= match.start()
                and match.end() <= start + len(record.text)):
            return _label(path), (start,start+len(record.text))
    return None, None


def _candidate_pages(store, scope, doc_ids, terms):
    # Query only authorized original pages, returning IDs (never notes / another scope's text).
    # Check the exact phrase again in extracted_text after the inexpensive SQLite prefilter.
    query, params = store._original_pages(scope)
    placeholders = ','.join('?' for _ in doc_ids)
    raw = "lower(coalesce(json_extract(r.payload,'$.details.raw_text'),json_extract(r.payload,'$.text'),''))"
    contains = ' OR '.join(f'instr({raw},?)>0' for _ in terms)
    with store.connect() as db:
        return db.execute(f'SELECT s.document_id,s.page{query} AND s.document_id IN ({placeholders}) '
                          f'AND ({contains}) ORDER BY s.document_id,s.page LIMIT 64',
                          [*params,*doc_ids,*terms]).fetchall()


def _related(study, scope, run, index, docs, seeds, paragraph):
    store = study.store
    output = []
    seen = {(d.id, item['page'], item['question']) for d, item, *_ in seeds}
    metadata = None
    for doc, _, record, raw in seeds:
        kinds = _direction(doc)
        targets = {d.id:d for d in docs.values() if d.kind in kinds}
        if not targets:
            continue
        if record:
            for edge in store.related(scope, record.id):
                if edge.kind not in {'assesses','uses_formula','explains'}:
                    continue
                other = store.get(scope,edge.target if edge.source==record.id else edge.source)
                if other is None:
                    continue
                for ref in other.refs:
                    target = targets.get(ref.document_id)
                    if target is None:
                        continue
                    page = _page(store,scope,target,ref.page)
                    question = _record_label(other,target)
                    identity = (target.id,ref.page,question)
                    if not page or identity in seen:
                        continue
                    literal = other.text if other.text.strip() and other.text in extracted_text(page) else ''
                    basis = '课程记录已标注此关联' if edge.origin=='explicit' else '课程记录推断的关联，待核对'
                    output.append(_item(run,index,target,ref.page,'related',literal,basis,question=question))
                    seen.add(identity)
                    if len(output) == MAX_RELATED:
                        return output
        terms = _terms(paragraph, raw)
        if not terms:
            continue
        for document_id, number in _candidate_pages(store,scope,sorted(targets),terms):
            target = targets[document_id]
            page = _page(store,scope,target,number)
            if not page:
                continue
            text = extracted_text(page)
            if metadata is None:
                metadata = store.metadata(scope) or {}
            for match in _matches(text, terms):
                question, bounds = _question_at(store,scope,target,metadata,number,match,text)
                identity = (target.id,number,question)
                if identity in seen:
                    continue
                basis = f'两份原文均出现“{match[0]}”，可核对是否讨论同一知识点。'
                quote = _excerpt(text,match,limits=bounds)
                output.append(_item(run,index,target,number,'related',quote,basis,question=question))
                seen.add(identity)
                if len(output) == MAX_RELATED:
                    return output
                if target.kind != 'exam':
                    break
    return output


def _direct(desk, scope, answer, run_id, paragraph_index, cache):
    paragraph = answer['paragraphs'][paragraph_index]
    evidence = {e['id']:e for e in answer.get('evidence',[]) if isinstance(e,dict) and 'id' in e}
    seeds = []
    for eid in dict.fromkeys(paragraph.get('citations',[])):
        entry = evidence.get(eid)
        if not entry or entry.get('snapshot',scope.snapshot) != scope.snapshot:
            continue
        rid = entry.get('record_id')
        if isinstance(rid,str) and rid not in cache['records']:
            cache['records'][rid] = desk.store.get(scope,rid)
        record = cache['records'].get(rid)
        for n, ref in enumerate(entry.get('refs',[])):
            try:
                doc = _document(desk.store,scope,ref)
            except ValueError:
                continue
            number = ref.get('page')
            address = (doc.id,number)
            if address not in cache['pages']:
                cache['pages'][address] = _page(desk.store,scope,doc,number)
            page = cache['pages'][address]
            if not page:
                continue
            text = extracted_text(page)
            literal = entry.get('text') or ''
            is_computed = entry.get('kind') in {'calculation','exam_topic'}
            quote = literal if not is_computed and literal.strip() and literal in text else ''
            question = None
            basis = '本段计算引用的原页' if is_computed else '本段回答标注的出处'
            if doc.kind in {'exam','exam_solution'}:
                path = entry.get('numbered_path')
                question = _label(path) or _record_label(record,doc)
                if not path and question and record:
                    path = '.'.join(re.findall(r'[0-9]+|[a-z]+',question))
                if not path and doc.kind=='exam' and doc.exam_year is not None:
                    # Older protocol stored the numbered-page projection's title and raw span.
                    # A title alone is insufficient: require its own numbered excerpt below.
                    title = (entry.get('title') or '').split(' · ')
                    if (len(title)==3 and title[0]==str(doc.exam_year) and _label(title[1])
                            and title[2]==PurePosixPath(doc.relative_path).name):
                        path = title[1]
                if doc.kind=='exam' and _label(path):
                    if doc.id not in cache['events']:
                        if 'metadata' not in cache:
                            cache['metadata'] = desk.store.metadata(scope) or {}
                        cache['events'][doc.id] = _document_events(desk.store,scope,doc,cache['metadata'],question=True)
                    lookup = (doc.id,path)
                    if lookup not in cache['excerpts']:
                        cache['excerpts'][lookup] = {r.refs[0].page:r.text for r in own_question_excerpts(
                            desk.store,scope,doc,cache['events'][doc.id],path)}
                    own = cache['excerpts'][lookup].get(number) or ''
                    if own and own in text and (question or own in quote):
                        question = _label(path)
                        quote, basis = own, '本段引用的小问正文，题干及前置条件见完整原页。'
                    elif question:
                        # Projected parent and earlier sibling pages establish context,
                        # never label their bodies as the requested leaf question.
                        basis = f'此页是 {question} 的上下文，小问正文未在本页单独定位。'
                        quote, question = '', None
            term_source = quote
            row = _table_row(quote, paragraph.get('text','')) if doc.kind == 'exam' and not question else ''
            if row:
                quote = row
            elif len(quote) > 420:
                match = next(_matches(quote,_terms(paragraph.get('text',''),quote)),None)
                if match:
                    quote = _excerpt(quote,match)
                elif not question and doc.kind == 'exam' and re.match(r'^\s*[—–-]\s*\d+\s*[—–-]',quote):
                    quote, basis = '', '这一段引用了考卷页，尚未定位到更具体的原句。'
                else:
                    quote = quote[:420].rstrip()
            item = _item(run_id,paragraph_index,doc,number,'cited',quote,basis,question=question,
                         evidence_id=eid,ref_index=n)
            seeds.append((doc,item,record,term_source))
    return seeds


def _cache():
    # A single request only. Permissions and document identities are rechecked on every action.
    return {'pages':{}, 'records':{}, 'events':{}, 'excerpts':{}}


def answer_sources(desk, run_id):
    scope, answer = completed_answer(desk,run_id)
    session, course = desk.session_id, desk.course_id
    cache = _cache()
    paragraphs = []
    for index in range(len(answer.get('paragraphs',[]))):
        seeds = _direct(desk,scope,answer,run_id,index,cache)
        paragraphs.append({'paragraph_index':index,'items':[item for _,item,_,_ in seeds]})
    if desk._current()!=scope or desk.session_id!=session or desk.course_id!=course:
        raise ValueError('课程或对话已切换，请重新打开出处。')
    return {'paragraphs':paragraphs}


def paragraph_sources(desk, run_id, paragraph_index):
    scope, answer = completed_answer(desk,run_id)
    session, course = desk.session_id, desk.course_id
    paragraphs = answer.get('paragraphs',[])
    if type(paragraph_index) is not int or not 0 <= paragraph_index < len(paragraphs):
        raise ValueError('请选择当前回答中的一个段落。')
    seeds = _direct(desk,scope,answer,run_id,paragraph_index,_cache())
    items = [item for _,item,_,_ in seeds]
    if seeds and not (answer.get('exam_outlook') or answer.get('selected_paper') or scope.strict_history or scope.cutoff):
        allowed = desk.store.permitted_documents(scope)
        docs = {d.id:d for d in desk.store.manifest(scope).documents if d.id in allowed}
        items.extend(_related(desk,scope,run_id,paragraph_index,docs,seeds,paragraphs[paragraph_index].get('text','')))
    if desk._current()!=scope or desk.session_id!=session or desk.course_id!=course:
        raise ValueError('课程或对话已切换，请重新打开出处。')
    return {'items':items}


def linked_page(desk, run_id, paragraph_index, key, *, page=None, image=False):
    # Recompute the membership under the current grant; a client-provided key never grants access.
    scope = desk._current()
    items = paragraph_sources(desk,run_id,paragraph_index)['items']
    item = next((item for item in items if item['key']==key),None)
    if item is None:
        raise ValueError('此来源不属于当前回答段落。')
    doc = _document(desk.store,scope,item)
    return read_original(desk,scope,doc,item['page'],item['quote'],page=page,image=image)
