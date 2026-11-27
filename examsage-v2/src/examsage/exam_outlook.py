"""A reproducible past-paper baseline. Holdout labels are read only by the evaluator."""
from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import PurePosixPath
import re

from .domain import digest, record_source_id
from .topic_evidence import scoped_topic_evidence, structured_question_evidence


METHOD = 'parent-topic-year-frequency-v1'
HEADING_INDEX = 'original-headings-v2'
LEGACY_HEADING_INDEX = 'original-headings-v1'



# Index only explicit topic headings. A numbered instruction or subpart can be a whole
# sentence without naming a topic, so it cannot supply a label for annual statistics.
_EN_HEADING = re.compile(r'(?:Question\s+(\d{1,3})\s+on|(?:Q\s*)?(\d{1,3})[.)]\s*Question\s+on)\s+(.{1,160})', re.I)
_ZH_HEADING = re.compile(r'第\s*([0-9]{1,3})\s*题\s*【主题[：:]\s*([^】]{1,160})】')


# Only an explicit label after the whole question number establishes this form.
_MARKED_EN = re.compile(r'(?:Question|Q)\s*(\d{1,3})\s*(?:[-–—.:]\s*|\s+)Topic\s*[:：]\s*(.{1,160})', re.I)
_MARKED_ZH = re.compile(r'第\s*(\d{1,3})\s*题\s*[-–—.:：]?\s*主题\s*[:：]\s*(.{1,160})')


# A geometrically flattened PDF row can contain a second imperative sentence.
_RUNNING_TASK = re.compile(r'(?:[.?!。？！]\s*|\s{2,})(?:calculate|compute|describe|discuss|explain|'
                           r'estimate|determine|derive|compare|evaluate|identify|prove|show|list|state|'
                           r'sketch|find|outline|give|write|analyse|analyze|assess)\b',re.I)
_ZH_RUNNING_TASK = re.compile(r'(?:\s{2,}|[。？！；;]\s*)请(?:根据|结合|比较|说明|解释|计算|分析|评价|证明|回答|列出|指出|画出)')
_MARKS = re.compile(r'\s*(?:\(\d+\s*(?:marks?|points?)\)|\[\d+(?:\s*(?:marks?|points?))?\]|'
                    r'[（(]\s*\d+\s*分\s*[）)]|【\s*\d+\s*分\s*】)\s*$',re.I)


def ambiguous_exam_documents(documents, kind):
    by_hash = defaultdict(list)
    for doc in documents:
        by_hash[doc.sha256].append(doc)
    excluded = set()
    for copies in by_hash.values():
        papers = [doc for doc in copies if doc.kind == kind]
        if papers:
            roles = {doc.kind for doc in copies if doc.kind != 'unknown'}
            years = {doc.exam_year for doc in papers if doc.exam_year is not None}
            if len(roles) > 1 or len(years) > 1:
                excluded.update(doc.id for doc in papers)
    return excluded


def ambiguous_papers(documents):
    excluded = ambiguous_exam_documents(documents, 'exam')
    by_content = defaultdict(list)
    for doc in documents:
        if doc.kind in {'exam','unknown'}:
            by_content[doc.sha256].append(doc)
    for copies in by_content.values():
        years = set()
        inconsistent = False
        for doc in copies:
            year, _ = paper_year(doc)
            if year is not None:
                years.add(year)
            elif doc.exam_year is not None:
                inconsistent = True
        if inconsistent or len(years) > 1:
            excluded.update(doc.id for doc in copies if doc.kind=='exam')
    return excluded


def ambiguous_outlook_documents(documents):
    excluded = ambiguous_papers(documents)
    assessment_types = {'exam','exam_solution','practice','mock_exam','exam_guidance',
                        'assessment_rubric','tutorial_feedback'}
    assessment_hashes = {d.sha256 for d in documents if d.kind in assessment_types}
    excluded.update(d.id for d in documents if d.sha256 in assessment_hashes and
                    d.kind in {'lecture','textbook','formula_sheet'})
    return excluded


def paper_headings(text, *, layout=None, marked_only=False):
    found = []
    original = ' '.join(text.split()) if layout is not None else None
    lines = layout.splitlines() if layout is not None else text.splitlines()
    for line in lines:
        heading = ' '.join(line.split())
        marked = _MARKED_EN.fullmatch(heading) or _MARKED_ZH.fullmatch(heading)
        if marked:
            number, topic = marked.groups()
        elif not marked_only and (english := _EN_HEADING.fullmatch(heading)):
            number, topic = english[1] or english[2], english[3]
        elif not marked_only and (chinese := _ZH_HEADING.fullmatch(heading)):
            number, topic = chinese.groups()
        else:
            continue
        if original is not None and heading not in original:
            continue
        if _RUNNING_TASK.search(line) or _ZH_RUNNING_TASK.search(line) or re.search(r'[?!。？！]\s*\S',topic):
            continue
        topic = _MARKS.sub('',topic).strip()
        if re.search(r'(?:^|\s)(?:\(?[a-zivx]{1,4}\)|part\s+[a-z]\b)|\[[0-9]+\]|\.{3,}',topic,re.I):
            continue
        if topic.strip() and int(number) > 0:
            found.append({'number':str(int(number)), 'topic':topic.strip(), 'heading':heading})
    return found


def _legacy_headings(raw, previous):
    # v1 stored a whitespace-normalized heading and sometimes recovered a line
    # from PDF layout. Prefer the original line, including column separators.
    originals = defaultdict(list)
    for line in raw.splitlines():
        originals[' '.join(line.split())].append(line)
    flattened = ' '.join(raw.split())
    for entry in previous:
        heading = entry['heading']
        if heading not in flattened:
            continue
        lines = originals.get(heading) or [heading]
        checked = [paper_headings(line) for line in lines]
        if all(items and items[0]['number'] == entry['number'] for items in checked):
            yield checked[0][0]
    yield from paper_headings(raw,marked_only=True)


def _indexed_headings(store,scope,metadata):
    where, args = store.eligible_sql(scope)
    legacy = metadata.get('paper_heading_index') == LEGACY_HEADING_INDEX
    raw = "json_extract(r.payload,'$.details.raw_text')" if legacy else 'NULL'
    select = "json_extract(r.payload,'$.details.paper_headings')"
    relevant = "headings IS NOT NULL"
    if legacy:
        relevant += " OR instr(lower(raw),'topic') OR instr(raw,'主题')"
    with store.connect() as db:
        rows = db.execute(f"""SELECT s.document_id,s.page,{select} AS headings,{raw} AS raw
            FROM records r JOIN record_sources s ON s.snapshot=r.snapshot AND s.record_id=r.id
            WHERE r.kind='block' AND r.id=s.document_id || ':p' || s.page
            AND json_array_length(r.payload,'$.refs')=1
            AND coalesce(json_extract(r.payload,'$.details.extraction_status'),'') != 'failed'
            AND ({relevant}) AND {where} ORDER BY s.document_id,s.page""",args)
        for doc_id,page,headings,raw_text in rows:
            saved = json.loads(headings) if headings else []
            for item in (_legacy_headings(raw_text or '',saved) if legacy else saved):
                yield doc_id,page,item


def _heading_observations(store, scope, papers, question_pages, metadata):
    editions = {(year,doc.sha256) for doc,year,_ in papers.values()}
    headings, checked = defaultdict(dict), defaultdict(dict)
    spellings = {}

    def add(group, doc_id, page, number, topic, evidence):
        doc, year, basis = papers[doc_id]
        key = year, doc.sha256, number
        label = topic.casefold()
        ref = {'document_id':doc_id, 'page':page, 'record_id':f'{doc_id}:p{page}',
               'filename':PurePosixPath(doc.relative_path).name, 'year':year,
               'year_basis':basis, 'question_number':number, **evidence}
        spellings[label] = min(topic, spellings.get(label, topic))
        previous = group[key].get(label)
        order = lambda r: (r['filename'],r['page'],r['document_id'])
        if previous is None or order(ref) < order(previous):
            group[key][label] = ref

    for doc_id, page, item in _indexed_headings(store,scope,metadata):
        add(headings,doc_id,page,item['number'],item['topic'],
            {'label_origin':'paper_heading','heading':item['heading']})
    allowed = scoped_topic_evidence(metadata, papers, scope.cutoff if scope.strict_history else None)
    for doc_id, entries in allowed.items():
        for item in entries:
            add(checked, doc_id, item['page'], item['number'], item['topic'],
                {k:item[k] for k in ('label_origin','quote','annotation_date','question_start_page') if k in item})

    topics = defaultdict(dict)
    parents = headings.keys() | checked.keys()
    conflicts = tagged = 0
    for key in sorted(parents):
        # An edition's individually verified annotations can describe several
        # concepts in one question. Disagreeing automatic titles remain unresolved.
        candidates = checked.get(key) or headings[key]
        if question_pages is not None:
            ref = min(candidates.values(),key=lambda r:(r['filename'],r['page'],r['document_id']))
            question_pages[key] = {k:v for k,v in ref.items()
                                   if k not in {'heading','label_origin','quote','annotation_date','question_start_page'}}
            if 'question_start_page' in ref:
                page = ref['question_start_page']
                question_pages[key].update(page=page, record_id=f"{ref['document_id']}:p{page}")
        if key not in checked and len(candidates) != 1:
            conflicts += 1
            continue
        tagged += 1
        for label, ref in candidates.items():
            topics[spellings[label]][key] = ref
    seen_editions = {(year,content_hash) for year,content_hash,_ in parents}
    coverage = {'exam_papers':len(editions),'parent_questions':len(parents),'tagged_questions':tagged,
                'papers_without_parsed_questions':len(editions-seen_editions),'heading_only':not checked,
                'conflicting_headings':conflicts}
    if checked:
        coverage['source_checked_questions'] = len(checked)
    return topics, sorted({year for year,_ in editions}), coverage


def paper_year(doc):
    # Some audited course archives identify the academic year only in the filename.
    # Bare years, file timestamps and years in question text do not establish a sitting.
    years = set()
    for start, end in re.findall(r'(?<!\d)((?:19|20)\d{2})[-_](\d{4}|\d{2})(?!\d)', PurePosixPath(doc.relative_path).name):
        following = int(start) + 1
        if end in {str(following), str(following)[-2:]}:
            years.add(following)
    if doc.exam_year is not None:
        if years and years != {doc.exam_year}:
            return None, None
        return doc.exam_year, 'manifest_exam_year'
    return (years.pop(), 'filename_academic_year') if len(years) == 1 else (None, None)


def _bounded_scope(scope, year, mode):
    if mode == 'paper_year' and not scope.strict_history:
        return scope
    cutoff = min(date(year-1, 12, 31), datetime.now(timezone.utc).date())
    if scope.strict_history:
        cutoff = min(cutoff, scope.cutoff)
    return scope.model_copy(update={'strict_history':True, 'cutoff':cutoff})


def _questions(store, scope):
    where, args = store.eligible_sql(scope)
    # Only extract topic annotations and paper locators. A question's text or
    # audit trail can include solution material written after the sitting.
    with store.connect() as db:
        return db.execute(f"""SELECT r.id, json_extract(r.payload,'$.topic') topic,
            json_extract(r.payload,'$.details.number') number,
            json_extract(r.payload,'$.details.exam_year') declared_year,
            json_extract(r.payload,'$.refs') refs
            FROM records r WHERE r.kind='question' AND r.parent_id IS NULL AND {where}
            ORDER BY r.id""",args).fetchall()


def _first_paper_page(store, scope, doc_id, refs):
    for ref in refs:
        page = ref['page']
        record = store.get(scope, f'{doc_id}:p{page}')
        if (record and record.kind == 'block' and len(record.refs) == 1
                and (record.refs[0].document_id, record.refs[0].page) == (doc_id, page)
                and record.details.get('extraction_status') != 'failed'):
            return page
    return None


def eligible_exam_materials(store, scope, year_filter, latest_material_year, metadata):
    manifest = store.manifest(scope)
    permitted = store.permitted_documents(scope)
    indexed_headings = metadata.get('paper_heading_index') in (LEGACY_HEADING_INDEX, HEADING_INDEX)
    excluded = (set(metadata.get('ambiguous_paper_documents', ())) |
                set(metadata.get('ambiguous_outlook_documents', ())) | ambiguous_outlook_documents(manifest.documents))
    papers, references = {}, set()
    for doc in manifest.documents:
        if (doc.id not in permitted or doc.id in excluded or (doc.document_date is not None and
                (doc.document_date.year > latest_material_year or
                 (scope.strict_history and doc.document_date > scope.cutoff)))):
            continue
        if doc.kind == 'exam':
            year, basis = paper_year(doc)
            if year is not None and year_filter(year) and (not indexed_headings or doc.exam_year is not None):
                papers[doc.id] = (doc, year, basis)
        elif (doc.kind in {'lecture','textbook','formula_sheet'}
                and (doc.exam_year is None or doc.exam_year <= latest_material_year)):
            references.add(doc.id)
    return papers, references


def _observations(store, scope, year_filter, latest_material_year, question_pages):
    metadata = store.metadata(scope) or {}
    indexed_headings = metadata.get('paper_heading_index') in (LEGACY_HEADING_INDEX, HEADING_INDEX)
    papers, references = eligible_exam_materials(store, scope, year_filter, latest_material_year, metadata)
    paper_scope = scope.model_copy(update={'allowed_sources':sorted(papers)})
    if indexed_headings:
        topics, years, coverage = _heading_observations(store,paper_scope,papers,question_pages,metadata)
        from .numbered_pages import original_question_pages
        for doc, year, basis in papers.values():
            known = {n for y,h,n in question_pages if (y,h)==(year,doc.sha256)}
            for number, page in original_question_pages(store,paper_scope,doc,metadata,known):
                question_pages[year,doc.sha256,number] = {
                    'document_id':doc.id,'record_id':f'{doc.id}:p{page}','page':page,
                    'filename':PurePosixPath(doc.relative_path).name,'year':year,
                    'year_basis':basis,'question_number':number}
        coverage['parent_questions'] = len(question_pages)
        coverage['papers_without_located_questions'] = coverage['exam_papers'] - len({(y,h) for y,h,_ in question_pages})
        return topics, years, coverage
    mapping_scope = scope.model_copy(update={'allowed_sources':sorted(set(papers) | references)})
    checked_documents = set(metadata.get('paper_topic_documents', ()))
    checked = structured_question_evidence(metadata,papers,scope.cutoff if scope.strict_history else None)
    checked_parents = set()
    parents, tagged, paper_questions = set(), set(), set()
    topics = defaultdict(dict)
    for q in _questions(store, paper_scope):
        refs = json.loads(q['refs'])
        ids = {ref['document_id'] for ref in refs}
        if len(ids) != 1 or not ids.issubset(papers):
            continue
        doc_id = ids.pop()
        doc, year, basis = papers[doc_id]
        number = str(q['number']) if q['number'] is not None else q['id']
        key = year, doc.sha256, number
        parents.add(key)
        paper_questions.add((year,doc.sha256))
        page = _first_paper_page(store,paper_scope,doc_id,refs)
        if page is None:
            continue
        ref = {'document_id':doc_id, 'page':page, 'record_id':f'{doc_id}:p{page}',
               'filename':PurePosixPath(doc.relative_path).name, 'year':year, 'year_basis':basis,
               'question_number':number}
        question_pages.setdefault(key,ref)
        if q['declared_year'] is not None and q['declared_year'] != year:
            continue
        if doc_id in checked_documents:
            for row in checked.get(q['id'], ()):
                if row['document_id'] != doc_id or row['number'] != number:
                    continue
                start = row['question_start_page']
                question_pages[key] = {**ref,'page':start,'record_id':f'{doc_id}:p{start}'}
                topics[row['topic']][key] = {**ref,**row}
                checked_parents.add(key)
                tagged.add(key)
            # A later or missing annotation cannot reinstate teaching-section labels.
            continue
        tags = {}
        if q['topic'] and str(q['topic']).strip():
            tags[q['topic'].strip()] = 'question_topic'
        else:
            for edge in store.related(mapping_scope,q['id']):
                if edge.source != q['id'] or edge.kind not in {'assesses','uses_formula'}:
                    continue
                concept = store.get(mapping_scope,edge.target)
                if (concept and concept.kind in {'concept','formula','example'} and concept.topic
                        and all(ref.document_id in references for ref in concept.refs)):
                    tags[concept.topic] = 'mapped_topic'
        if tags:
            tagged.add(key)
        for topic, origin in tags.items():
            topics[topic][key] = {**ref,'label_origin':origin}
    editions = {(year,d.sha256) for d,year,_ in papers.values()}
    coverage = {'exam_papers':len(editions),'parent_questions':len(parents),'tagged_questions':len(tagged),
                'papers_without_parsed_questions':len(editions-paper_questions)}
    coverage['papers_without_located_questions'] = len(editions - {(y,h) for y,h,_ in question_pages})
    if checked_parents:
        coverage['source_checked_questions'] = len(checked_parents)
    return topics, sorted({y for y,_ in editions}), coverage


def _sources(store, scope, course_id, occurrences):
    refs = sorted(occurrences, key=lambda r:(-r['year'],r['filename'],r['question_number'],r['page']))
    # Represent separate sittings first; the full counting base is in years/question_count.
    examples = {}
    for ref in refs:
        examples.setdefault(ref['year'],ref)
    result = []
    for ref in list(examples.values())[:3]:
        record = store.get(scope,ref['record_id'])
        sid = 'src_' + digest([course_id, scope.model_dump(mode='json'), digest(record.model_dump(mode='json'))])
        result.append({**ref,'source_id':sid})
    return result


def exam_outlook(store,scope,course_id,target_year,top_k,history_mode):
    if (type(target_year) is not int or not 1900 <= target_year <= 2200 or
            type(top_k) is not int or not 1 <= top_k <= 10 or history_mode not in ('paper_year','strict')):
        raise ValueError('Invalid forecast year, number of topics, or history mode')
    training = _bounded_scope(scope,target_year,history_mode)
    pages = {}
    topics, years, coverage = _observations(store, training, lambda y:y < target_year, target_year-1, pages)
    labelled = {key for occurrences in topics.values() for key in occurrences}
    unlabelled = _sources(store,scope,course_id,(ref for key,ref in pages.items() if key not in labelled))
    ranking = []
    for topic, occurrences in topics.items():
        observed = sorted({y for y,_,_ in occurrences})
        ranking.append({'topic':topic,'years':observed,'year_count':len(observed),'question_count':len(occurrences)})
    checked = coverage.get('source_checked_questions', 0)
    heading_only = coverage.get('heading_only', False)
    ranking.sort(key=lambda r:(-r['year_count'],-r['question_count'],-r['years'][-1],
                               r['topic'].casefold() if heading_only or checked else r['topic']))
    selected = ranking[:top_k]
    for row in selected:
        row['sources'] = _sources(store,scope,course_id,topics[row['topic']].values())
    if selected and training.strict_history:
        docs = {doc.id:doc for doc in store.manifest(training).documents}
        received = (store.metadata(training) or {}).get('received_on_utc')
        for row in selected:
            for ref in row['sources']:
                ref['availability'] = docs[ref['document_id']].availability(received)
    provenance = ('已核对短引的标签附有编制日期；其余题头索引的编制日期未经核验。' if checked else
                  '主题标签来自当前快照，含候选映射；标签编制日期未经核验。')
    limitations = [provenance,
                   '按出现考年数、父题数、最近考年、标签字面顺序排列。每个主题最多示例三个年份，出现次数不能换算为出题概率。',
                   '没有明确考年、卷名学年与登记年份冲突或文件版本日期晚于所选上限的试卷不计入统计。']
    if checked:
        limitations.append('复习标签来自核对过的卷面标题或题干短引，可有多个。主题归纳待教师审核；同一主题在不同年份可能考查不同技能。')
    if coverage.get('heading_only'):
        limitations.append('仅统计可定位的卷面题头；未识别的题型、无主题标题或存在冲突的条目不参与排名。整卷大题总数与题答对应待审核。')
    numbered_only = coverage['papers_without_parsed_questions'] - coverage['papers_without_located_questions']
    if numbered_only > 0:
        limitations.append(f'另有 {numbered_only} 份卷可定位大题编号，但没有可用的主题题头。已计入大题覆盖。')
    if training.strict_history:
        limitations.append('仅纳入截止日前有可得日期的来源。试卷封面日期不能证明当时可取得。')
    else:
        limitations.append('按卷面考年回顾，部分年份仅有文件名学年标签。没有据此验证当年考前可得性。')
    if len(years) < 3:
        limitations.append('可用考年不足三个，排序对单份卷的内容敏感。')
    if years and target_year - years[-1] > 1:
        limitations.append(f'最近一次纳入的考年为 {years[-1]}，目标年之前有空档。缺卷年份不计作某主题没有考过。')
    if coverage['tagged_questions'] < coverage['parent_questions'] or coverage['papers_without_located_questions']:
        limitations.append('部分试卷或大题缺少可核对的题目或主题，频次仅反映已定位的部分。')
    if not selected:
        limitations.append('当前范围内没有同时具备可定位父题和主题标签的往卷证据。')
    return {'course_id':course_id,'snapshot':scope.snapshot,'target_year':target_year,'history_mode':history_mode,
            'availability_cutoff':training.cutoff.isoformat() if training.strict_history else None,
            'method':'paper-source-topic-frequency-v1' if checked else 'paper-heading-year-frequency-v1' if coverage.get('heading_only') else METHOD,'status':'ranked' if selected else 'insufficient','top_k':top_k,
            'ranking':selected,'training_years':years,'coverage':coverage,'unlabelled_examples':unlabelled,'limitations':limitations,
            'unranked_reason':None if selected else ('no_supported_topics' if years else 'no_eligible_papers')}


def _review_questions(store, scope, course_id, pages, actual, matched_labels, offset, limit):
    questions = {key:{'source':ref, 'question_number':ref['question_number'],
                      'observed_topics':[], 'matched_topics':[]} for key,ref in pages.items()}
    for label, occurrences in actual.items():
        for key, evidence in occurrences.items():
            row = questions[key]
            if 'quote' in evidence:
                row.setdefault('topic_evidence', []).append({'topic':label, **evidence})
            row['observed_topics'].append(label)
            if label in matched_labels:
                row['matched_topics'].append(label)
    def paper_order(row):
        ref = row['source']
        label = row['question_number']
        digits = label.lstrip('0')
        number = (0,len(digits),digits,label) if label.isascii() and label.isdecimal() else (1,0,label,label)
        return ref['filename'], ref['document_id'], ref['page'], number
    ordered = sorted(questions.values(), key=paper_order)
    page = ordered[offset:None if limit is None else offset+limit]
    ids = {}
    for q in page:
        ref = q['source']
        if ref['record_id'] not in ids:
            record = store.get(scope,ref['record_id'])
            ids[ref['record_id']] = record_source_id(course_id,scope,digest(record.model_dump(mode='json')))
        q['source'] = {**ref,'source_id':ids[ref['record_id']]}
        for evidence in q.get('topic_evidence', []):
            record_id = evidence['record_id']
            if record_id not in ids:
                record = store.get(scope,record_id)
                ids[record_id] = record_source_id(course_id,scope,digest(record.model_dump(mode='json')))
            evidence['source_id'] = ids[record_id]
        q['observed_topics'].sort()
        q['matched_topics'].sort()
        q['label_status'] = 'labelled' if q['observed_topics'] else 'unlabelled'
    following = offset+len(page)
    return page, len(ordered), following if following < len(ordered) else None


def evaluate_outlook(store,scope,course_id,target_year,top_k,history_mode,*,offset=0,question_limit=None):
    forecast = exam_outlook(store,scope,course_id,target_year,top_k,history_mode)
    # Evaluation intentionally opens the target separately, still under the caller's
    # grant. The forecasting function cannot read these topics via this path.
    pages = {}
    actual, _, coverage = _observations(store,scope,lambda y:y == target_year,target_year,question_pages=pages)
    # Historical clients use this holdout field for a paper with no located question.
    coverage['papers_without_parsed_questions'] = coverage['papers_without_located_questions']
    predicted = {r['topic'] for r in forecast['ranking']}
    # Private paper headings use a case-insensitive vocabulary within a fold.
    # The display spelling can differ between the training and target folds.
    key = str.casefold if coverage.get('heading_only') or coverage.get('source_checked_questions') else str
    predicted_keys = {key(label) for label in predicted}
    matched_actual = {label for label in actual if key(label) in predicted_keys}
    actual_keys = {key(label) for label in actual}
    absent = sorted(label for label in predicted if key(label) not in actual_keys)
    hits = sorted(matched_actual)
    complete_labels = (bool(actual) and not coverage.get('heading_only') and not coverage.get('source_checked_questions') and
                       not coverage['papers_without_parsed_questions'] and
                       coverage['tagged_questions'] == coverage['parent_questions'])
    if not coverage['exam_papers']:
        status = 'no_target'
    elif not predicted:
        status = 'no_forecast'
    elif not complete_labels:
        status = 'partial_target'
    else:
        status = 'compared'
    metrics = None
    if status=='compared':
        metrics = {'matched':len(hits),'predicted':len(predicted),'observed':len(actual),'requested_k':top_k,
                   'precision_at_k':len(hits)/top_k,'precision_on_returned':len(hits)/len(predicted),
                   'recall':len(hits)/len(actual)}
    rows,total,following = _review_questions(store,scope,course_id,pages,actual,matched_actual,offset,question_limit)
    return {'outlook':forecast, 'target_coverage':coverage,'observed_topics':sorted(actual),
            'comparison_status':status,'target_questions':rows,'target_questions_total':total,'next_offset':following,
            'matched_topics':hits,'new_to_prediction':sorted(actual.keys()-matched_actual) if predicted else [],
            'unobserved_predictions':absent if status=='compared' else [],
            'unresolved_predictions':absent if status!='compared' else [],'metrics':metrics,
            'evaluation':'retrospective_exact_topic_labels','metric_basis':'distinct_topic_labels_in_accessible_records'}
