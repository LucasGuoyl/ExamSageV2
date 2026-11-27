from __future__ import annotations

from collections import defaultdict
import re
import time
import unicodedata

from .domain import Bundle, PaperSelection, Record, Scope
from .storage import Store
from .lexical import cjk_terms

STOP = set('the a an of and to is are what how why does do in for from with this that it as be can explain find about between versus'.split())
YEAR = re.compile(r'(?<!\d)(20\d{2})(?!\d)')
QUESTION = re.compile(r'(?:(?<![a-z])(?:question|q)\s*|第\s*)(\d+)(?!\d)(?:\s*题)?(?:\s*[（(]\s*([ivx]+|[a-z])\s*[）)])?',re.I)
ACADEMIC_YEAR = re.compile(r'(?<!\d)(20\d{2})\s*[-–/]\s*(20\d{2}|\d{2})(?!\d)')
PILOT_QUESTION = re.compile(r'(?:(?<![a-z])(?:question|q)\s*|第\s*)(\d+)(?!\d)(?:\s*题)?',re.I)


def pilot_question(query: str):
    """Parse one explicit part path; unknown descendants never become whole Qs."""
    text=unicodedata.normalize('NFKC',query)
    matches=list(PILOT_QUESTION.finditer(text))
    if len(matches)!=1:return None
    match=matches[0];tail=text[match.end():];parts=[]
    letters=r'(?:[ivx]+|[a-z])';token=r'(?:[ivx]+|[a-z]|\d+)'
    while True:
        parenthesis=re.match(r'\s*\(\s*('+token+r'(?:\s*\.\s*'+token+r')*)\s*\)',tail,re.I)
        plain=(re.match(r'\s*(?:part\s+|第\s*)('+token+r'(?:\s*\.\s*'+token+r')*)(?![a-z0-9])(?:\s*小问)?',tail,re.I) or
               re.match(r'\s*('+letters+r'(?:\s*\.\s*'+token+r')*)(?![a-z0-9])',tail,re.I)) if not parts else None
        found=parenthesis or plain
        if not found:break
        parts.extend(re.sub(r'\s+','',found[1]).lower().split('.'));tail=tail[found.end():]
    part_path=token+r'(?:\s*\.\s*'+token+r')*(?![a-z0-9])'
    if re.match(r'\s*[().\-]',tail) or re.search(r'\bpart\s+'+part_path+r'|第\s*[a-z0-9一二三四五六七八九]+\s*小问',tail,re.I):return None
    connector=r'(?:\b(?:and|or|vs|versus|to|through)\b|以及|和|及|与|或|到|至|、|[,;/&+])'
    parenthesized=r'\(\s*'+token+r'(?:\s*\.\s*'+token+r')*\s*\)'
    def secondary_bare(fragment):
        found=re.match(r'\s*('+part_path+r')',fragment,re.I)
        if not found:return False
        remainder=fragment[found.end():].lstrip()
        # A complete second path is ambiguous regardless of how the student
        # asks for its answer. Only recognizable prose/variable syntax is exempt.
        if re.match(r'[=<>≤≥≠]',remainder):return False
        if found[1].casefold()=='i' and re.match(r"(?:think|believe|suspect|assume|guess|feel|know|understand|wonder|am|have|would|can|could|should|need|want)\b|['’](?:m|ve|d|ll)\b",remainder,re.I):return False
        return True
    joined=re.match(r'\s*'+connector,tail,re.I)
    if not parts and (re.match(r'[a-z0-9_]|\s*[\[\]{}/]',tail,re.I) or
                      (joined and secondary_bare(tail[joined.end():]))):
        return None
    if parts and ((re.match(r'\s*[a-z]',tail,re.I) and secondary_bare(tail)) or
                  (joined and secondary_bare(tail[joined.end():])) or
                  re.search(connector+r'\s*'+parenthesized,tail,re.I)):return None
    return str(int(match[1])),'.'.join(parts) if parts else None

def pilot_years(query: str, questions: list[Record]) -> list[str]:
    years=[]
    for match in ACADEMIC_YEAR.finditer(query):
        start,end=match.groups();end=end if len(end)==4 else start[:2]+end
        labels={str(r.details['exam_year']) for r in questions if r.details.get('year_label') in {start+'-'+end[-2:],start+'-'+end}}
        years.extend(labels if int(end)==int(start)+1 else [])
        if not labels:years.append('0')
    years+=YEAR.findall(ACADEMIC_YEAR.sub(' ',query))
    return list(dict.fromkeys(years))


def wants_answer(query: str) -> bool:
    if re.search(r'(?:不要|不看|不含|先别|别|不需要|无需)\s*(?:给出|显示|给|看)?\s*(?:答案|解答)'
                 r'|(?:只给|只看|仅看|仅给)(?:我)?(?:题目|题干|问题)'
                 r'|\b(?:no|without|hide)\s+(?:the\s+|any\s+)?(?:answers?|solutions?)\b'
                 r'|\bquestion\s+only\b', query, re.I):
        return False
    return any(t in query.casefold() for t in ['答案','解答','answer','solution','mark scheme','评分',
        '怎么','如何','为什么','为何','多少','计算','推导','复算','核对','检查','是否','calculate','derive','explain','how ','why '])


def tokens(text: str) -> list[str]:
    normalized=unicodedata.normalize('NFKC',text).lower()
    # A single CJK character may be a complete title (e.g. an original poem
    # titled 窗). Keep it for the existing FTS title index, without changing
    # the treatment of noisy one-letter Latin tokens or rebuilding snapshots.
    return list(dict.fromkeys(x for x in re.findall(r'[\w]+',normalized)
                              if x not in STOP and (len(x)>1 or re.fullmatch(r'[\u3400-\u9fff]', x))))[:48]


def source_text_unavailable(record: Record) -> bool:
    """A raw page may exist while its readable evidence is absent or failed."""
    return record.kind=='block' and (record.details.get('extraction_status')=='failed' or not record.text.strip())


def context_record(record: Record) -> Record:
    """Defer duplicate raw pages, retaining full structured content and citations."""
    details={k:v for k,v in record.details.items() if k not in {'source_excerpts','source_question_text','source_only_text'} and not (k=='raw_text' and record.kind=='block')}
    if details.get('audit',{}).get('previous_assessment'):
        details['audit']={k:v for k,v in details['audit'].items() if k!='previous_assessment'}
        details['audit_history_deferred']=True
    if 'source_excerpts' in record.details:
        details['source_text_deferred']=True
    if details.get('supplement'):
        supplement=details['supplement']
        details['supplement']={**supplement,'ocr':{k:v for k,v in supplement['ocr'].items() if k not in {'words','lines','text'}},
                               'ocr_details_deferred':True}
        recovery=supplement.get('audit',{}).get('recovery')
        if recovery and recovery.get('previous_assessment'):
            details['supplement']['audit']={**supplement['audit'],'recovery':{k:v for k,v in recovery.items() if k!='previous_assessment'}}
    return record.model_copy(update={'details':details})


def context_group(records: list[Record]) -> list[Record]:
    """Keep the requested audit and inherited conditions; defer duplicate audits."""
    questions={r.id:context_record(r) for r in records if r.kind=='question'}
    target=next(iter(questions),None)
    result=[]
    for raw in records:
        record=context_record(raw);details=dict(record.details);audit=details.get('audit')
        if audit:
            same=next((q for q in questions.values() if q.details.get('audit')==audit and
                       all(q.details.get(k)==record.details.get(k) for k in ['exam_year','number','part'])),None)
            if record.kind=='answer' and same:
                details.pop('audit');details['audit_on_record_id']=same.id
            elif record.kind=='question' and record.id!=target and audit['numerical_checks']:
                details['audit_checks_deferred_count']=len(audit['numerical_checks'])
                details['audit']={**audit,'numerical_checks':[]}
        result.append(record.model_copy(update={'details':details}))
    return result


def append_budgeted(bundle: Bundle, group: list[Record], remaining: int, limit: int) -> int:
    size=sum(len(r.model_dump_json()) for r in group)
    if size>remaining or len(bundle.records)+len(group)>limit:
        note='Some matching evidence omitted to respect context budget; complete objects were not truncated.'
        if note not in bundle.limitations:bundle.limitations.append(note)
        return remaining
    bundle.records.extend(group)
    return remaining-size


def conflicting_selected_year(query, year):
    # A numerical condition (e.g. 2000 W) is not an exam sitting. Recognise a
    # year in a paper/question label or next to an explicit exam-year word.
    text = unicodedata.normalize('NFKC', query)
    years = r'(?:19|20|21)\d{2}'
    for m in re.finditer(r'(?<!\d)('+years+r')(?:\s*[-–/]\s*(\d{4}|\d{2}))?(?!\d)', text):
        before, after = text[:m.start()], text[m.end():]
        # A year can precede a question label or follow one as its edition.
        # Other dates in the problem (for example a historical event) remain
        # part of the text unless they explicitly refer to the paper/answer.
        context = (
            re.search(r'(?:考年|考试年份|试卷年份|学年|原卷|试卷|真题|\b(?:academic year|exam(?: year)?|paper)(?:\s+(?:in|of|for))?)\s*[:：]?\s*$', before, re.I)
            or re.match(r'\s*(?:年(?:度)?\s*)?(?:的\s*)?[,，:：]?\s*'
                        r'(?:学年|考年|(?:期末|期中|正式|补考)?(?:考试|原卷|试卷|考卷|真题)|卷|第\s*\d+\s*题|Q(?:uestion)?\s*\d|'
                        r'\b(?:academic year|exam|paper|sitting|solutions?|answers?)\b)', after, re.I)
            or re.match(r'\s*年(?:度)?\s*(?:的\s*)?(?:参考|标准|官方)?(?:答案|解答|评分)', after)
            or re.match(r'\s*年?\s*(?:和|与|、|及|\band\b|\bor\b)\s*'+years, after, re.I)
            or (re.search(r'(?:Q(?:uestion)?\s*\d+|第\s*\d+\s*题)(?:\s*\([a-z\d.]+\))+\s*[,，:：]?\s*$', before, re.I)
                and re.fullmatch(r'\s*年?\s*(?:(?:的\s*)?(?:答案|解答|题目|answer|solution))?[?？。.! ]*', after, re.I)))
        if context and (m[2] or int(m[1]) != year):
            return True
    return False


def supports_paper_selection(metadata):
    return (metadata.get('mode') == 'course_pack' and not metadata.get('export_schema')
            and metadata.get('import_report', {}).get('records') == 0)


def source_page_course(metadata):
    return (metadata.get('structure_mode') == 'source_pages'
            or (metadata.get('mode') == 'course_pack' and metadata.get('import_report', {}).get('records') == 0))


class CourseQueryService:
    def __init__(self, store: Store, vectors=None, embed_query=None, *, course_id=None):
        self.course_id = course_id
        self.store,self.vectors,self.embed_query=store,vectors,embed_query
        self._aliases={}

    def _terms(self, scope: Scope, query: str) -> list[str]:
        key=(scope.snapshot,scope.workspace,scope.course,tuple(sorted(scope.allowed_sources)),scope.strict_history,scope.cutoff)
        if key not in self._aliases:
            self._aliases[key]=[(alias,r.title) for kind in ['concept','formula','example']
                                for r in self.store.list_records(scope,kind) for alias in r.aliases]
        expanded=query
        for alias,term in (self.store.metadata(scope) or {}).get('query_aliases',{}).items():
            if alias.casefold() in query.casefold():expanded+=' '+term
        for alias,title in self._aliases[key]:
            if len(alias)>1 and alias.casefold() in query.casefold():
                expanded+=' '+title
        return list(dict.fromkeys(tokens(expanded)+cjk_terms(query)))[:96]

    def _availability(self, scope: Scope, query: str) -> str | None:
        text=query.casefold()
        if any(x in text for x in ['官方答案','official solution','official answer','mark scheme','官方评分']):
            if not self.store.list_records(scope,'answer'):
                return 'No official exam answers or marking scheme exist in this authorized snapshot.'
        years=YEAR.findall(text)
        if any(x in text for x in ['真题','exam paper','past paper','试卷']) or (len(set(years))>1 and QUESTION.search(text)):
            manifest=self.store.manifest(scope)
            allowed=self.store.permitted_documents(scope)
            existing={str(d.exam_year) for d in manifest.documents if d.kind=='exam' and d.id in allowed} if manifest else set()
            missing=sorted(set(years)-existing)
            if missing:
                return 'Missing exam years: '+', '.join(missing)
        return None

    def search_evidence(self, scope: Scope, query: str, limit: int = 8, max_chars: int = 24000, *, selection=None) -> Bundle:
        started=time.perf_counter()
        if not 1<=limit<=30 or not 100<=max_chars<=200000 or not query.strip() or len(query)>4000:
            raise ValueError('invalid query limits')
        bundle=Bundle(snapshot=scope.snapshot,mode='keyword_only')
        metadata=self.store.metadata(scope) or {}
        source_mode=source_page_course(metadata)
        # Original raw imports retain a complete manifest. Older portable subsets
        # may have lost conflicting editions when their manifest was projected.
        legacy_upload = supports_paper_selection(metadata)
        if selection is not None:
            selected = PaperSelection.model_validate(selection)
            requested = pilot_question(query)
            if not legacy_upload or not requested:
                bundle.sufficiency = 'insufficient'
                bundle.limitations.append('请在直接导入的课程里选择文件，并指定题号或完整小问编号，例如 Q3 或 Q3(b)(ii)。')
                return bundle
            if conflicting_selected_year(query, selected.exam_year):
                bundle.sufficiency = 'insufficient'
                bundle.limitations.append('问题中的年份与本次选卷考年不一致或含有学年范围，请核对考试公历年。')
                return bundle
            from .numbered_pages import numbered_sources
            return numbered_sources(self.store, scope, metadata, selected.exam_year, *requested,
                                    wants_answer(query), limit, max_chars, selection=selected)
        if source_mode and ('numbered_page_index' in metadata or legacy_upload) and QUESTION.search(query):
            requested = pilot_question(query)
            years = pilot_years(query,[])
            if not requested:
                bundle.sufficiency = 'insufficient'
                bundle.limitations.append('请一次指定一个明确的题号或小问编号。')
                return bundle
            if requested and (requested[1] or not metadata.get('pilot_questions')):
                if len(years) != 1 or not YEAR.fullmatch(years[0]):
                    bundle.sufficiency = 'insufficient'
                    bundle.limitations.append('请指定一个明确的考试公历年（考年），例如“2025 Q3(b)(ii)”。')
                    return bundle
                from .numbered_pages import numbered_sources
                return numbered_sources(self.store,scope,metadata,int(years[0]),*requested,wants_answer(query),limit,max_chars)
        if source_mode and metadata.get('pilot_questions') and QUESTION.search(query) and YEAR.search(query):
            questions=self.store.list_records(scope,'question')
            years=pilot_years(query,questions);requested=pilot_question(query)
            if requested is None:
                bundle.sufficiency='insufficient'
                bundle.limitations.append('题号或小问路径不明确，请逐次查询，如“2024 Q1(a)(i)”。')
                return bundle
            number,part=requested
            matches=[r for r in questions if len(years)==1 and
                     r.details.get('exam_year')==int(years[0]) and str(r.details.get('number'))==number and
                     r.details.get('part')==part]
            if len(matches)!=1:
                bundle.sufficiency='insufficient';bundle.limitations.append('Requested exam year, question number or subquestion is absent from the authorized snapshot.')
                return bundle
            want_answer=wants_answer(query)
            found=self.get_answer(scope,matches[0].id) if want_answer else self.get_question(scope,matches[0].id)
            max_chars=append_budgeted(bundle,context_group(found.records),max_chars,limit)
            bundle.limitations+=found.limitations
            if bundle.records:bundle.relations=found.relations
            bundle.sufficiency=found.sufficiency if bundle.records else 'insufficient'
            bundle.elapsed_ms=round((time.perf_counter()-started)*1000,3)
            return bundle
        if source_mode and ((QUESTION.search(query) and YEAR.search(query)) or (YEAR.search(query) and any(t in query.lower() for t in ['试卷','真题','exam','paper']))):
            bundle.sufficiency='insufficient'
            bundle.limitations.append('本课程的试卷按原始文件提供；年份与逐题结构尚未验证，请在“试卷与练习”中核对原文件。')
            return bundle
        if source_mode and not (metadata.get('pilot_questions') and YEAR.search(query)) and any(t in query.lower() for t in ['官方答案','official answer','official solution','mark scheme','官方评分']):
            manifest=self.store.manifest(scope)
            allowed=self.store.permitted_documents(scope)
            sources={d.id for d in manifest.documents if d.kind=='exam_solution' and d.id in allowed} if manifest else set()
            if sources:
                for record in self.store.list_records(scope,'block'):
                    if record.refs[0].document_id in sources and record.refs[0].page==1:
                        max_chars=append_budgeted(bundle,[context_record(record)],max_chars,limit)
                        if source_text_unavailable(record):
                            bundle.sufficiency='insufficient'
                            bundle.limitations.append('Answer source page has no usable extracted text; source review is required.')
                        if len(bundle.records)>=limit:break
                bundle.limitations.append('已找到文件级审阅标注的答案或评分反馈；尚未建立逐题对应，不能据此断言某题答案已验证。')
                if not bundle.records:bundle.sufficiency='insufficient'
                bundle.elapsed_ms=round((time.perf_counter()-started)*1000,3)
                return bundle
        availability=self._availability(scope,query)
        if availability:
            bundle.limitations.append(availability)
            bundle.sufficiency='insufficient'
            return bundle
        where,params=self.store.eligible_sql(scope)
        terms=self._terms(scope,query)
        ranks=[]
        if terms:
            expression=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
            with self.store.connect() as db:
                rows=db.execute(f'''SELECT r.id FROM search_index JOIN records r
                    ON r.snapshot=search_index.snapshot AND r.id=search_index.record_id
                    WHERE search_index MATCH ? AND {where}
                    ORDER BY bm25(search_index,0,0,6,1) LIMIT 80''',[expression,*params]).fetchall()
            ranks.append([r[0] for r in rows])
        exact_ids=[]
        years=list(dict.fromkeys(YEAR.findall(query)))
        requested=pilot_question(query) if PILOT_QUESTION.search(query) else None
        if len(years)==1 and PILOT_QUESTION.search(query) and requested is None:
            bundle.sufficiency='insufficient'
            bundle.limitations.append('Question or subquestion path is ambiguous; request one complete path at a time.')
            return bundle
        requested_part=requested[1] if requested else None
        if len(years)==1 and requested:
            with self.store.connect() as db:
                rows=db.execute(f'''SELECT r.id, r.parent_id, json_extract(r.payload,'$.details.part') AS part
                    FROM records r WHERE {where} AND r.kind='question'
                    AND json_extract(r.payload,'$.details.exam_year')=?
                    AND json_extract(r.payload,'$.details.number')=?
                    AND (? IS NULL OR json_extract(r.payload,'$.details.part')=?) ORDER BY r.parent_id IS NOT NULL''',
                    [*params,int(years[0]),requested[0],requested_part,requested_part]).fetchall()
            ids={r[0] for r in rows}
            parts=[r[2] for r in rows if r[2] is not None]
            if ((requested_part is not None and len(rows)>1) or
                    (requested_part is None and (sum(r[1] not in ids for r in rows)>1 or len(parts)!=len(set(parts))))):
                bundle.sufficiency='insufficient'
                bundle.limitations.append('Ambiguous exam path: multiple question variants match; choose a source-specific question record.')
                return bundle
            if rows:
                exact_ids=[r[0] for r in rows]
                ranks.insert(0,exact_ids)
            else:
                bundle.sufficiency='insufficient'
                bundle.limitations.append('Requested exam year, question number or subquestion is absent from the authorized snapshot.')
                bundle.elapsed_ms=round((time.perf_counter()-started)*1000,3)
                return bundle
        if self.vectors is not None and self.embed_query is not None:
            try:
                with self.store.connect() as db:
                    allowed={r[0] for r in db.execute(f'SELECT r.id FROM records r WHERE {where}',params)}
                hits=self.vectors.rank(scope.snapshot,self.embed_query(query),allowed)
                if hits:
                    ranks.append([rid for rid,_ in hits])
                    bundle.mode='hybrid'
                else:
                    bundle.limitations.append('No embeddings indexed for this route/snapshot.')
            except Exception:
                bundle.limitations.append('Semantic retrieval unavailable; keyword fallback used.')
        else:
            bundle.limitations.append('Embeddings are not configured; indexed keyword and course-alias retrieval is active.')
        scores=defaultdict(float)
        for route in ranks:
            for rank,rid in enumerate(route):
                scores[rid]+=1/(60+rank)
        ordered=sorted(scores,key=lambda rid:(-scores[rid],rid))
        if source_mode and metadata.get('pilot_questions') and YEAR.search(query):
            requested_years=pilot_years(query,self.store.list_records(scope,'question'))
            want_answer=wants_answer(query)
            for rid in ordered:
                hit=self.store.get(scope,rid)
                if not hit or hit.kind!='question' or len(requested_years)!=1 or str(hit.details.get('exam_year'))!=requested_years[0]:continue
                found=self.get_answer(scope,rid) if want_answer else self.get_question(scope,rid)
                before=len(bundle.records)
                max_chars=append_budgeted(bundle,context_group(found.records),max_chars,limit)
                if len(bundle.records)>before:bundle.relations+=found.relations;bundle.limitations+=found.limitations
            if not bundle.records:bundle.sufficiency='insufficient'
            bundle.limitations.append('按请求年份限定题目候选；请用年份和题号进一步精确定位。')
            bundle.limitations=list(dict.fromkeys(bundle.limitations))
            bundle.elapsed_ms=round((time.perf_counter()-started)*1000,3)
            return bundle
        # A derivation is a complete explanation spanning pages. If several top
        # source hits belong to it, reserve room for the chain before page excerpts.
        if source_mode and metadata.get('pilot_records'):
            top_refs=set()
            for rid in ordered[:5]:
                hit=self.store.get(scope,rid)
                if hit and hit.kind=='block':top_refs.update((r.document_id,r.page) for r in hit.refs)
            chains=[r for r in self.store.list_records(scope,'concept') if r.details.get('derivation') and
                    len(top_refs & {(s.document_id,s.page) for s in r.refs})>=2]
            ordered=list(dict.fromkeys([r.id for r in chains]+ordered))
        if exact_ids:
            linked=[]
            for edge in self.store.related(scope,exact_ids[0]):
                related=self.store.get(scope,edge.target)
                if related and related.kind in {'concept','formula','example'}:
                    overlap=len(set(tokens(related.title+' '+related.text)) & set(terms))
                    linked.append((related.id,overlap,related.kind=='formula'))
            linked.sort(key=lambda x:(-x[1],-x[2],x[0]))
            ordered=list(dict.fromkeys(exact_ids[:1]+[x[0] for x in linked[:3]]+exact_ids[1:]+ordered))
        seen=set()
        for rid in ordered:
            if len(bundle.records)>=limit:
                break
            record=self.store.get(scope,rid)
            if record is None or rid in seen:
                continue
            if source_text_unavailable(record):
                bundle.sufficiency='insufficient'
                bundle.limitations.append('Matching source page has no usable extracted text; source review is required.')
            if record.kind=='question' and 'has_answer' in record.details:
                found=self.get_question(scope,record.id)
                if not found.records:continue
                record=found.records[0]
            if exact_ids and requested_part and record.kind=='question' and rid not in exact_ids:
                continue
            edges=[]
            if record.kind=='question' and record.id in exact_ids and wants_answer(query):
                # Explicit requests resolve the pairing even when the answer has
                # no lexical overlap with the query (e.g. just a numerical value).
                found=self.get_answer(scope,record.id)
                group=found.records
                edges=found.relations
                bundle.limitations+=found.limitations
                if found.sufficiency=='insufficient':bundle.sufficiency='insufficient'
            elif record.kind=='answer':
                # An answer hit has no safe standalone meaning. Resolve its exact
                # question and all shared conditions before budgeting the group.
                questions={edge.source for edge in self.store.related(scope,record.id)
                           if edge.kind=='has_answer' and edge.target==record.id}
                if exact_ids and not questions <= set(exact_ids):
                    continue
                found=self.get_answer(scope,next(iter(questions))) if len(questions)==1 else None
                if found is None or found.sufficiency=='insufficient' or not any(r.id==record.id for r in found.records):
                    bundle.limitations.append('Matching answer omitted because its complete, unambiguous question context is unavailable.')
                    continue
                group=found.records
                edges=found.relations
                bundle.limitations+=found.limitations
            else:
                group=self._with_parents(scope,record)
            if not group:continue
            group=context_group([r for r in group if r.id not in seen])
            # Return a question with its complete shared parent context or omit the group.
            previous_count=len(bundle.records)
            max_chars=append_budgeted(bundle,group,max_chars,limit)
            if len(bundle.records)>previous_count:
                seen.update(r.id for r in group)
                known={edge.id for edge in bundle.relations}
                bundle.relations.extend(edge for edge in edges if edge.id not in known)
            elif record.id in exact_ids and wants_answer(query):
                bundle.sufficiency='insufficient'
        if not bundle.records:
            bundle.sufficiency='insufficient'
            bundle.limitations.append('No matching evidence in the permitted course, sources and date range.')
        if scope.strict_history:
            bundle.limitations.append('Strict historical filtering excludes unknown available_from dates and later sources.')
        bundle.limitations=list(dict.fromkeys(bundle.limitations))
        bundle.elapsed_ms=round((time.perf_counter()-started)*1000,3)
        return bundle

    def get_concept(self, scope: Scope, concept_id: str) -> Bundle:
        r=self.store.get(scope,concept_id)
        if r is None or r.kind not in {'concept','formula','example','proof'}:
            return Bundle(snapshot=scope.snapshot,sufficiency='insufficient',limitations=['Concept not found in permitted scope.'])
        return Bundle(snapshot=scope.snapshot,records=[r],relations=self.store.related(scope,r.id),limitations=r.limitations)

    def get_question(self, scope: Scope, question_id: str) -> Bundle:
        r=self.store.get(scope,question_id)
        if r is None or r.kind!='question':
            return Bundle(snapshot=scope.snapshot,sufficiency='insufficient',limitations=['Question not found in permitted scope.'])
        edges=self.store.related(scope,r.id)
        if 'has_answer' in r.details:
            r=r.model_copy(update={'details':{**r.details,'has_answer':any(e.kind=='has_answer' and e.source==r.id for e in edges)}})
        records=self._with_parents(scope,r)
        if not records:return Bundle(snapshot=scope.snapshot,sufficiency='insufficient',limitations=['Shared question context unavailable.'])
        return Bundle(snapshot=scope.snapshot,records=records,relations=edges,limitations=r.limitations)

    def with_question_topics(self, scope, records):
        parents = [r for r in records if r.kind == 'question' and r.parent_id is None]
        if not parents:
            return records
        from .topic_evidence import structured_question_evidence
        from .domain import digest, record_source_id
        docs = {ref.document_id for parent in parents for ref in parent.refs}
        index = structured_question_evidence(self.store.metadata(scope) or {}, docs,
                                             scope.cutoff if scope.strict_history else None)
        projected, pages = {}, {}
        for parent in parents:
            evidence = []
            for row in index.get(parent.id, ()):
                rid = row['record_id']
                if rid not in pages:
                    page = self.store.get(scope,rid)
                    pages[rid] = (record_source_id(self.course_id or scope.course,scope,digest(page.model_dump(mode='json')))
                                  if page else None)
                if pages[rid]:
                    evidence.append({**row,'source_id':pages[rid]})
            if evidence:
                projected[parent.id] = parent.model_copy(update={'details':{**parent.details,'exam_topic_evidence':evidence}})
        return [projected.get(r.id,r) for r in records]

    def _with_parents(self, scope: Scope, record: Record) -> list[Record]:
        records=[record];seen={record.id}
        while records[-1].parent_id:
            parent=self.store.get(scope,records[-1].parent_id)
            if parent is None or parent.id in seen or len(records)>=10:return []
            records.append(parent);seen.add(parent.id)
        records = self.with_question_topics(scope,records)
        # Scope-aware flags must also apply to inherited question records.
        return [r.model_copy(update={'details':{**r.details,'has_answer':any(e.kind=='has_answer' and e.source==r.id for e in self.store.related(scope,r.id))}})
                if r.kind=='question' and 'has_answer' in r.details else r for r in records]

    def get_related_questions(self, scope: Scope, concept_id: str) -> Bundle:
        edges=[e for e in self.store.related(scope,concept_id) if e.kind in {'assesses','uses_formula'}]
        records={}
        for e in edges:
            for rid in [e.source,e.target]:
                r=self.store.get(scope,rid)
                if r and r.kind=='question':
                    for question in self.get_question(scope,r.id).records:
                        records[question.id]=question
        return Bundle(snapshot=scope.snapshot,records=list(records.values()),relations=edges,
                      limitations=['Question mappings are inferred and require independent review.'])

    def get_answer(self, scope: Scope, question_id: str) -> Bundle:
        bundle=self.get_question(scope,question_id)
        if not bundle.records:return bundle
        edges=[e for e in bundle.relations if e.kind=='has_answer' and e.source==question_id]
        answers=[self.store.get(scope,e.target) for e in edges]
        if len(answers)!=1 or answers[0] is None or answers[0].kind!='answer':
            bundle.sufficiency='insufficient'
            bundle.limitations.append('本题尚无可访问的逐题配对答案；不会用其他年份或题号代替。')
            return bundle
        context=self._with_parents(scope,answers[0])
        if not context:
            bundle.sufficiency='insufficient';bundle.limitations.append('Shared answer context unavailable.');return bundle
        bundle.records+=context;bundle.relations=edges
        bundle.limitations+=answers[0].limitations
        bundle.limitations.append('小问题答已按原页对应；请同时查看条件、复算结果与来源冲突注记，独立专家验收待完成。' if answers[0].details.get('audit') else '题答已按来源与大题编号配对；导读摘要不等于完整答案，数值解与评分仍需对照原件核实。')
        return bundle

    def get_source_page(self, scope: Scope, document_id: str, page: int) -> Bundle:
        record=self.store.get(scope,f'{document_id}:p{page}')
        if record is None:
            return Bundle(snapshot=scope.snapshot,sufficiency='insufficient',limitations=['Source page not available in permitted scope.'])
        unavailable=source_text_unavailable(record)
        return Bundle(snapshot=scope.snapshot,records=[record],
                      sufficiency='insufficient' if unavailable else 'unassessed',
                      limitations=record.limitations+(['Source page has no usable extracted text; source review is required.'] if unavailable else []))
