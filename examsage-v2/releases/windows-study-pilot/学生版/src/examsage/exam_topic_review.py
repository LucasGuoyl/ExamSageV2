"""Check a host's proposed study topics against the exact visible exam-question text."""
from collections import defaultdict
from pathlib import PurePosixPath
import re

from .domain import digest, record_source_id
from .exam_outlook import _bounded_scope, eligible_exam_materials
from .numbered_pages import _document_events, own_question_excerpts


PAGE_SIZE = 8
_FURNITURE = re.compile(
    r'^(?:[—–-]\s*\d+\s*[—–-]|(?:page\s+\d+\s+of\s+\d+|第\s*\d+\s*页)(?:\s.*)?|'
    r'(?:paper continues on next page|(?:please\s+)?turn\s+over|end of (?:examination|paper)|answer all questions)\.?|'
    r'\(?\d+\s*(?:marks?|points?)\)?|\d+)$', re.I)

# A decimal at the beginning of a line can be a numeric subquestion or a
# measurement. Until the locator resolves it, text from there has no safe owner.
_UNRESOLVED_NUMBER = re.compile(
    r'(?:^[ \t]*|[ \t]{2,}|(?<=[.!?。！？])[ \t]+)(?:Q(?:uestion)?\s*)?'
    r'[1-9]\d{0,2}(?:\.\d+)+(?=\s|[.)：:]|$)', re.I | re.M)
_SCORE = re.compile(r'[\[(（【]\s*\d+(?:\.\d+)?\s*(?:marks?|points?|分)\s*[\])）】]', re.I)
_HEADING = re.compile(
    r'^(?:(?:Q(?:uestion)?\s*\d{1,3}\b|第\s*\d+\s*题|(?:Q\s*)?\d{1,3}\.(?:[a-z]+\.)*[a-z]+[.)]|\d{1,3}[.)])'
    r'(?:\s*\([a-z]{1,4}\))*|\([a-z]{1,4}\)|[a-z]{1,4}\))(?=\s|[:：.]|$)[\s:：.]*', re.I)
_COPYRIGHT = re.compile(r'^(?:course title\s*:.*?\s*)?©\s*(?:\d{4}\b.*|[^?？]*\b(?:university|college|institute)\b[^?？]*)$', re.I)


def text_segments(body):
    # A removed label, score or footer must also break the continuous quote.
    parts = []
    passage = []
    for line in body.splitlines():
        clean = ' '.join(line.split())
        if not clean:
            continue
        label = _HEADING.match(clean)
        if label:
            if passage:
                parts.append(' '.join(passage))
                passage = []
            clean = clean[label.end():]
        if not clean or _FURNITURE.fullmatch(clean) or _COPYRIGHT.fullmatch(clean):
            if passage:
                parts.append(' '.join(passage))
                passage = []
            continue
        for index, fragment in enumerate(_SCORE.split(clean)):
            if index and passage:
                parts.append(' '.join(passage))
                passage = []
            if fragment.strip():
                passage.append(fragment.strip())
    if passage:
        parts.append(' '.join(passage))
    return parts


class ExamTopicReview:
    def __init__(self,store,scope,course_id,target_year,history_mode):
        self.store = store
        self.scope = scope
        self.course_id = course_id
        self.history = _bounded_scope(scope,target_year,history_mode)
        self.metadata = store.metadata(self.history) or {}
        self.papers, _ = eligible_exam_materials(store,self.history,lambda y:y<target_year,
                                                target_year-1,self.metadata)
        self.paper_scope = self.history.model_copy(update={'allowed_sources':sorted(self.papers)})
        self.events = {}
        self.text = {}
        self.citations = {}
        self.header = {'course_id':course_id,'snapshot':scope.snapshot,'target_year':target_year,
                       'history_mode':history_mode,
                       'availability_cutoff':self.history.cutoff.isoformat() if self.history.strict_history else None}

    def _events(self,doc):
        if doc.id not in self.events:
            self.events[doc.id] = _document_events(self.store,self.paper_scope,doc,self.metadata,question=True)
        return self.events[doc.id]

    def _pages(self,doc,path):
        key = (doc.id,path)
        if key not in self.text:
            parts = {}
            for record in own_question_excerpts(self.store,self.paper_scope,doc,self._events(doc),path):
                boundary = _UNRESOLVED_NUMBER.search(record.text)
                body = record.text[:boundary.start()] if boundary else record.text
                segments = text_segments(body)
                if any(sum(c.isalnum() for c in text)>=4 for text in segments):
                    parts[record.refs[0].page] = segments
                if boundary:
                    break
            self.text[key] = parts
        return self.text[key]

    def _citation(self,doc,page):
        key = (doc.id,page)
        if key not in self.citations:
            record = self.store.get(self.scope,f'{doc.id}:p{page}')
            self.citations[key] = record_source_id(self.course_id,self.scope,digest(record.model_dump(mode='json')))
        return self.citations[key]

    def browse(self,offset):
        entries, editions = [], set()
        for doc,year,_ in sorted(self.papers.values(),key=lambda t:(-t[1],t[0].relative_path,t[0].id)):
            if (year,doc.sha256) in editions:
                continue
            editions.add((year,doc.sha256))
            paths = dict.fromkeys(e['path'] for e in self._events(doc) if e['path'])
            entries.extend((doc,year,path) for path in paths)
        rows = []
        for doc,year,path in entries[offset:offset+PAGE_SIZE]:
            pages = self._pages(doc,path)
            if not pages:
                continue
            excerpts = []
            for page,segments in list(pages.items())[:2]:
                first = segments[0]
                excerpts.append({'page':page,'source_id':self._citation(doc,page),'text':first[:360],
                                 'more_text':len(first)>360 or len(segments)>1})
            rows.append({'year':year,'document_id':doc.id,'filename':PurePosixPath(doc.relative_path).name,
                         'question_path':path,'excerpts':excerpts,'first_page':min(pages),'last_page':max(pages)})
        following = offset+PAGE_SIZE
        return {**self.header,'questions':rows,'next_offset':following if following<len(entries) else None,
                'eligible_years':sorted({y for y,_ in editions}), 'numbered_positions':len(entries),
                'limitations':['此处只摘录该编号本身的文字，父题条件可用查题工具另查。页内摘录可能截短。遇到未定位的数字小问边界即停止摘录；定位不唯一或缺页的编号跳过。']}

    def review(self,candidates):
        items, issues, counts = [], [], defaultdict(set)
        seen = set()
        for index,candidate in enumerate(candidates):
            entry = self.papers.get(candidate.document_id)
            quote = ' '.join(candidate.quote.split())
            parts = self._pages(entry[0],candidate.question_path).get(candidate.page,[]) if entry else []
            if (sum(c.isalnum() for c in quote)<4 or not any(quote in segment for segment in parts)
                    or self._citation(entry[0],candidate.page)!=candidate.source_id):
                issues.append({'index':index,'reason':'question_or_citation_unverified'})
                continue
            doc,year,_ = entry
            topic = ' '.join(candidate.topic.split())
            key = (topic,year,doc.sha256,candidate.question_path,candidate.page,quote)
            if key in seen:
                continue
            seen.add(key)
            counts[topic].add((year,doc.sha256,candidate.question_path.split('.')[0]))
            items.append({'index':index,'topic':topic,'year':year,'document_id':doc.id,
                          'filename':PurePosixPath(doc.relative_path).name,'question_path':candidate.question_path,
                          'page':candidate.page,'source_id':candidate.source_id,'quote':quote})
        topics = [{'topic':topic,'years':sorted({y for y,_,_ in count}),'parent_questions':len(count)}
                  for topic,count in sorted(counts.items())]
        return {**self.header,'status':'pending_academic_review','items':items,'issues':issues,'topics':topics,
                'limitations':['只核对原句是否位于所指题号、原页与授权范围内。主题为当前对话提出，含义和课程归类待核查。',
                               '计数仅覆盖这批提议中的不同父题。课程库、正式排名及历史回测均不因本次核对而改变。']}
