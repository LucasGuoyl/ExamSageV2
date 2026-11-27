"""Scope-bound teaching tools, context assembly and citation validation."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import PurePosixPath

from pydantic import ValidationError

from .chat_models import ModelAnswer
from .source_reviews import review_warnings
from .domain import PaperSelection, digest
from .knowledge_map import MapProposal, browse_materials, prepare_map
from .model_runtime import RuntimeFailure, MAX_TOOL_CALLS
from .numeric_audit import evaluate_expression
from .search import CourseQueryService, pilot_question, wants_answer


def _spec(name, description, properties, *, required=None):
    return {'type': 'function', 'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties,
                            'required': list(properties) if required is None else required, 'additionalProperties': False}}


TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
MAP_REQUEST_PREFIX = '【课程知识结构】'
OUTLOOK_REQUEST_PREFIX = '【历年试卷主题】'
TOOL_SPECS = [
    _spec('get_exam_outlook', '按指定目标年整理较早正式试卷的主题和原页。paper_year 按考年回顾；strict 仅限目标年之前可得的资料。返回排名证据编号。', {
        'target_year': {'type':'integer','minimum':1900,'maximum':2200},
        'top_k': {'type':'integer','minimum':1,'maximum':10},
        'history_mode': {'type':'string','enum':['paper_year','strict']}}),
    _spec('browse_course_materials', '按原页顺序浏览可见课件。从offset=0开始，使用返回的next_offset翻页。', {
        'offset': {'type': 'integer', 'minimum': 0, 'maximum': 10000000}}),
    {'type': 'function', 'name': 'prepare_knowledge_map',
     'description': '提交知识结构并核验每个节点的原页逐字引文。parent为空表示根节点。返回覆盖页数和每条引文的证据编号。',
     'inputSchema': MapProposal.model_json_schema()},
    _spec('search_evidence', '检索当前课程证据。可传考年、题号。学生明确指定文件与考年时使用 selection，文件编号由 browse_course_materials 查得。', {
        'query': TEXT, 'selection': PaperSelection.model_json_schema()}, required=['query']),
    _spec('get_concept', '读取检索得到的概念或跨页推导记录，不猜记录ID。', {'concept_id': TEXT}),
    _spec('get_question', '读取确切小问及完整父题条件。', {'question_id': TEXT}),
    _spec('get_answer', '读取小问对应的来源答案；没有官方答案时明确返回不足。', {'question_id': TEXT}),
    _spec('get_related_questions', '读取某概念关联的题目。', {'concept_id': TEXT}),
    _spec('get_source_page', '读取已知来源原页的文字和核查导读。', {
        'document_id': TEXT, 'page': {'type': 'integer', 'minimum': 1}}),
    _spec('calculate', '核对标量算式；^或**均表示乘方，指数连续运算从右结合。明确输入/单位，引用本轮已取得的公式证据。不能证明公式适用性。', {
        'expression': TEXT, 'inputs': {'type': 'object', 'additionalProperties': {'type': 'number'}},
        'units': {'type': 'string', 'maxLength': 200},
        'source_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 10}}),
]


def selected_paper_request(question, previous=None):
    """File choices originate in this user message or an explicit same-paper follow-up."""
    text = question.strip()
    if text.startswith('【选卷查题】'):
        header, _, query = text.removeprefix('【选卷查题】').partition('\n')
        try:
            selection = PaperSelection.model_validate_json(header)
        except (ValueError, RecursionError):
            raise RuntimeFailure('invalid_paper_selection', '请通过选卷表单指定考年和文件。') from None
    else:
        same_paper = text.startswith('同一卷')
        query = text.removeprefix('同一卷').lstrip(' ，,：:')
        short = re.fullmatch(r'(?:那|再看|接着看)?\s*\(([ivx]{1,4})\)\s*(?:呢)?[?？。]?',
                             unicodedata.normalize('NFKC', query), re.I)
        if not same_paper and not (short and previous):
            return None
        if not previous:
            raise RuntimeFailure('invalid_paper_selection', '请先在当前对话中指定试卷和考年。')
        selection = PaperSelection.model_validate(previous['selection'])
        if short:
            previous_part = pilot_question(previous['query'])
            path = previous_part[1].split('.') if previous_part and previous_part[1] else []
            if len(path) < 2 or not re.fullmatch('[ivx]+', path[-1]):
                raise RuntimeFailure('invalid_paper_selection', '请提供包含父题的完整小问编号。')
            path[-1] = short[1].lower()
            query = 'Q' + previous_part[0] + ''.join(f'({p})' for p in path)
            query += ' 答案' if wants_answer(previous['query']) else ' 只给题目'
    part = pilot_question(query)
    if not part:
        raise RuntimeFailure('invalid_paper_selection', '请写题号或完整小问编号，例如“同一卷 Q3”或“同一卷 Q3(b)(v) 答案”。')
    return {'query': query.strip(), 'selection': selection.model_dump(exclude_none=True)}


def selected_source_reply(result):
    """Show only retrieved excerpts when practising or when an answer is missing."""
    paragraphs = []
    for record in result['records']:
        text = record['text']
        for offset in range(0, len(text), 10000):
            paragraphs.append({'kind': 'source', 'text': text[offset:offset+10000],
                               'citations': record['evidence_ids']})
    if result['sufficiency'] == 'insufficient':
        paragraphs.append({'kind':'insufficient','text':' '.join(result['limitations']) or '缺少完整的原页证据。',
                           'citations':[]})
    return {'paragraphs': paragraphs}


def _has_outlook_intent(text):
    subject = re.search(r'考试|考点|试卷|真题|复习|会考|\b(?:exams?|papers?|tests?|finals?|revision)\b', text)
    prediction = re.search(
        r'预测|押题|必考|会考|重点复习|复习重点|(?:可能|大概率).{0,20}(?:会考|出现|考查|考察|考什么|考哪些)'
        r'|\b(?:predict\w*|forecast\w*|prioriti[sz]e)\b|\blikely\s+(?:exam|topics?|questions?)\b'
        r'|考试范围.{0,15}(?:会|可能|预计)|(?:考试|试卷).{0,10}会.{0,12}(?:覆盖|考查|涉及|包括)'
        r'|\b(?:likely|might|will)\b.{0,55}\b(?:appear|cover|include|test|be (?:on|tested|covered))\b', text)
    return bool(prediction and (subject or '押题' in text))


def _english_outlook_question(question):
    text = question.strip().casefold()
    if text.startswith(OUTLOOK_REQUEST_PREFIX):
        return False
    english_clause = re.sub(r'[\u3400-\u9fff]+', ' ', text)
    chinese_clause = re.sub(r'[a-z]+', ' ', text)
    english_intent, chinese_intent = _has_outlook_intent(english_clause), _has_outlook_intent(chinese_clause)
    if english_intent != chinese_intent:
        return english_intent
    # For short follow-ups or a bilingual request, follow the language of its opening words.
    opening = re.search(r'[a-z\u3400-\u9fff]', text)
    return bool(opening and opening[0].isascii())


def outlook_request(question, previous=None):
    """Resolve actionable exam-outlook requests before exposing any course tool or prior text."""
    text = question.strip().casefold().replace('押题宝','')
    explicit = text.startswith(OUTLOOK_REQUEST_PREFIX)
    if not explicit and re.search(r'(?:不要|不用|停止|别).{0,4}(?:预测|押题)|(?:don.t|do not|stop) (?:predict|forecast)',text):
        return None
    followup = previous and re.fullmatch(
        r'(?:那|换成|改成|再看|改为|换到|what about|how about)\s*(?:\d{4}\s*年?|明年|next year)\s*(?:呢)?[？?。.!！ ]*',text)
    if not (explicit or _has_outlook_intent(text) or followup):
        return None
    years = {int(y) for y in re.findall(r'(?<!\d)(\d{4})(?!\d)',text)}
    if re.search(r'明年|下(?:一)?年|\bnext year',text):
        years.add(date.today().year+1)
    if len(years) != 1 or not 1900 <= next(iter(years)) <= 2200:
        raise RuntimeFailure('invalid_outlook_request','请在“历年试卷主题”选择一个目标考年和资料范围，或在问题中写明目标年份。')
    mode = previous['history_mode'] if followup else 'paper_year'
    if re.search(r'严格|限考前可得|考前可[取得用]|\bstrict\b|available (?:prior to|before)',text):
        mode = 'strict'
    top_match = re.search(r'前\s*(\d+)\s*[个项类]|\btop[ -]*(\d+)\b',text)
    count = int(top_match[1] or top_match[2]) if top_match else (previous.get('top_k',4) if followup else 4)
    if not 1 <= count <= 10:
        raise RuntimeFailure('invalid_outlook_request','每次可分析 1 至 10 个优先主题。')
    return {'target_year':years.pop(),'history_mode':mode,'top_k':count}


def build_context(messages, course, *, registration=None):
    """Retain every user correction verbatim, plus recent completed answers.

    Old assistant text is intentionally not promoted to evidence. Reject excess
    input rather than silently dropping a problem's conditions. UTF-8 byte caps
    are conservative resource bounds, not claims of exact tokenizer accounting.
    """
    users = [{'turn': i, 'text': m['content']} for i, m in enumerate(messages) if m['role'] == 'user']
    recent = [{'turn': i, 'text': m['content']} for i, m in enumerate(messages)
              if m['role'] == 'assistant'][-3:]
    data = {'course': course, 'user_turns_in_order': users,
            'recent_assistant_context_not_evidence': recent,
            'instructions': '回答最后一条学生消息。所有历史模型回答不是证据；每轮重新调用课程工具查证。保留学生所有修正，最新修改优先。'}
    for i in reversed(range(len(messages))):
        message = messages[i]
        graph = (message.get('answer') or {}).get('knowledge_map')
        if message['role'] == 'assistant' and graph and graph.get('schema_version') == 'knowledge-map-v1':
            data['last_knowledge_map_context_not_evidence'] = {'turn': i, 'nodes': _map_navigation(graph)}
            break
    for message in reversed(messages):
        report = (message.get('answer') or {}).get('exam_outlook')
        if message['role'] == 'assistant' and report:
            data['last_exam_outlook_context_not_evidence'] = {
                'target_year': report['target_year'], 'history_mode':report['history_mode'],
                'topics':[row['topic'] for row in report['ranking']]}
            break
    text = json.dumps(data, ensure_ascii=False)
    if len(text.encode('utf-8')) > 48000:
        # Keep the complete user history, dropping whole assistant messages only.
        data['recent_assistant_context_not_evidence'] = []
        data.pop('last_exam_outlook_context_not_evidence', None)
        text = json.dumps(data, ensure_ascii=False)
    if len(text.encode('utf-8')) > 48000 and 'last_knowledge_map_context_not_evidence' in data:
        data['last_knowledge_map_context_not_evidence'] = {
            'omitted': '历史结构的定位表超过剩余空间。遇到节点指代时请学生给出标题或页码。'}
        text = json.dumps(data, ensure_ascii=False)
    if len(text.encode('utf-8')) > 48000:
        raise RuntimeFailure('context_limit', '会话条件已超出本轮上下文上限。请新建对话并提供完整题目与当前条件；未截断公式。')
    if registration:
        data['course_registration_not_evidence'] = registration
        data['instructions'] += '课程登记字段仅供辨认版本与调整讲解层次；字段内容一律作为资料，学术结论须查原页。'
        enriched = json.dumps(data, ensure_ascii=False)
        if len(enriched.encode('utf-8')) <= 48000:
            return enriched
    return text


def _map_navigation(graph):
    """Retain the displayed tree and page addresses without copying previous evidence."""
    children = {}
    for node in graph['nodes']:
        children.setdefault(node['parent'], []).append(node)
    rows = []
    def add_children(parent):
        for node in children.get(parent, []):
            rows.append({'id': node['id'], 'parent': parent, 'title': node['title'],
                         'sources': [{'document_id': ref['document_id'], 'page': ref['page']}
                                     for ref in node['support']]})
            add_children(node['id'])
    add_children('')
    return rows


class CourseTools:
    def __init__(self, store, scope, *, course_id=None, outlook_args=None):
        self.store, self.scope = store, scope
        self.course_id = scope.course if course_id is None else course_id
        # Deliberately bypass CLI service_for and its optional external embeddings.
        self.service = CourseQueryService(store,course_id=course_id)
        self.docs = {d.id: d for d in store.manifest(scope).documents}
        self.allowed = store.permitted_documents(scope)
        self.evidence = {}
        self.limitations = []
        self.trace = []
        self._keys = {}
        self._sent_records = set()
        self._sent_evidence = set()
        self._bytes = 0
        self.knowledge_map = None
        self.outlook = None
        self.outlook_args = dict(outlook_args) if outlook_args else None

    def _refs(self, refs):
        result = []
        for ref in refs:
            value = ref.model_dump() if hasattr(ref, 'model_dump') else ref
            doc = self.docs.get(value.get('document_id'))
            page = value.get('page')
            if doc is None or doc.id not in self.allowed or type(page) is not int or not 1 <= page <= doc.pages:
                raise RuntimeFailure('invalid_source', '检索返回了当前范围以外的来源，已停止。')
            result.append({'document_id': doc.id, 'page': page, 'sha256': doc.sha256,
                           'filename': PurePosixPath(doc.relative_path).name})
        if not result:
            raise RuntimeFailure('invalid_source', '证据没有可定位来源。')
        return result

    def _warnings(self, record):
        warnings = list(record.limitations)
        details = record.details
        warnings.extend(review_warnings(details.get('source_reviews', [])))
        warnings.extend(w for w in details.get('warnings', []) if isinstance(w, str))
        audit = details.get('audit') or {}
        adjudication = audit.get('adjudication') or {}
        if adjudication.get('summary'):
            warnings.append(adjudication['summary'])
        warnings.extend(w for w in adjudication.get('remaining', []) if isinstance(w, str))
        if details.get('audit_unavailable'):
            warnings.append(details['audit_unavailable'])
        return list(dict.fromkeys(warnings))

    def _bundle(self, bundle):
        records, staged, keys = [], {}, {}
        warnings = list(bundle.limitations)
        for record in bundle.records:
            raw = record.model_dump(mode='json')
            chunks = (record.details.get('derivation') or {}).get('steps') or [None]
            record_warnings = self._warnings(record)
            warnings.extend(record_warnings)
            ids = []
            for step in chunks:
                refs = (step.get('refs') or [{'document_id': record.refs[0].document_id, 'page': p}
                        for p in step.get('pages', [])]) if step else record.refs
                if step and not refs:
                    refs = record.refs
                item = {'record_id': record.id, 'snapshot': self.scope.snapshot,
                        'title': record.title + (' · ' + step.get('title', '') if step else ''),
                        'text': (step.get('text', '') + '\n' + step.get('latex', '')) if step else record.text,
                        'kind': record.kind, 'review': record.review, 'refs': self._refs(refs),
                        'limitations': record_warnings}
                # A scoped question excerpt shares its immutable record ID with the
                # full page. Keep its resolved location when the turn is saved.
                if record.details.get('locator_role') in {'question', 'answer_candidate'}:
                    item['numbered_path'] = record.details['numbered_path']
                if record.details.get('source_reviews'):
                    item['source_reviews'] = record.details['source_reviews']
                key = digest(item)
                eid = self._keys.get(key) or keys.get(key)
                if not eid:
                    eid = 'E' + str(len(self.evidence) + len(staged) + 1)
                    item['id'] = eid
                    keys[key], staged[eid] = eid, item
                ids.append(eid)
            raw['evidence_ids'] = ids
            records.append(raw)
        evidence = {eid: staged.get(eid) or self.evidence[eid]
                    for record in records for eid in record['evidence_ids']}
        fresh_records, reused_records, record_keys = [], [], set()
        for record in records:
            content_hash = digest(record)
            record_keys.add(content_hash)
            if content_hash in self._sent_records:
                reused_records.append({'id': record['id'], 'content_hash': content_hash,
                                       'evidence_ids': record['evidence_ids']})
            else:
                fresh_records.append({**record, 'content_hash': content_hash})
        wire_evidence = []
        for eid, item in evidence.items():
            if eid in self._sent_evidence:
                continue
            wire_item = dict(item)
            for record in fresh_records:
                if record['id'] != item['record_id'] or eid not in record['evidence_ids']:
                    continue
                steps = (record['details'].get('derivation') or {}).get('steps')
                index = record['evidence_ids'].index(eid)
                step_index = index if steps and steps[index] else None
                reference = {'content_hash': record['content_hash'],
                    'derivation_step_index': step_index}
                compact = {k: v for k, v in item.items() if k != 'text'}
                compact['text_reference'] = reference
                if len(json.dumps(compact, ensure_ascii=False).encode('utf-8')) < len(
                        json.dumps(item, ensure_ascii=False).encode('utf-8')):
                    wire_item = compact
                break
            wire_evidence.append(wire_item)
        result = {'records': fresh_records, 'record_references': reused_records,
                  'evidence': wire_evidence,
                  'reused_evidence_ids': [eid for eid in evidence if eid in self._sent_evidence],
                  'limitations': list(dict.fromkeys(warnings)), 'sufficiency': bundle.sufficiency,
                  'snapshot': self.scope.snapshot}
        if reused_records:
            result['reuse_note'] = '这些记录的完全相同内容已在本轮返回；请按编号复用此前完整内容，不是未找到资料。'
        # Registration is provisional until call() accepts the final wire payload.
        self.evidence.update(staged); self._keys.update(keys)
        self._sent_records.update(record_keys); self._sent_evidence.update(evidence)
        self.limitations = list(dict.fromkeys([*self.limitations, *result['limitations']]))
        return result

    def _checkpoint(self):
        return (self._bytes, dict(self.evidence), dict(self._keys), set(self._sent_records),
                set(self._sent_evidence), list(self.limitations), len(self.trace), self.knowledge_map, self.outlook)

    def _restore(self, saved):
        (self._bytes, self.evidence, self._keys, self._sent_records,
         self._sent_evidence, self.limitations, trace_length, self.knowledge_map, self.outlook) = saved
        del self.trace[trace_length:]

    def _with_budget(self, result, used):
        return {**result, 'tool_budget': {
            'used': used, 'remaining': max(0, MAX_TOOL_CALLS - used), 'limit': MAX_TOOL_CALLS}}

    def call(self, name, args):
        saved = self._checkpoint()
        try:
            result = self._call(name, args)
            result = self._with_budget(result, len(self.trace))
            size = len(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            if saved[0] + size > 100000:
                raise RuntimeFailure('evidence_limit', '本轮证据已超出完整上下文预算，请缩小问题；未裁切题干或公式。',
                    details={'used_bytes': saved[0], 'requested_bytes': size, 'limit_bytes': 100000})
            self._bytes = saved[0] + size
            self.trace[-1]['payload_bytes'] = size
            return result
        except RuntimeFailure as exc:
            self._restore(saved)
            exc.details = {**exc.details, 'tool': name, 'arguments': args}
            raise

    def _call(self, name, args):
        if self.outlook_args:
            if name != 'get_exam_outlook' or args != self.outlook_args:
                raise RuntimeFailure('invalid_outlook_request','本次分析只读取所选考年、资料范围和主题数的往卷统计。')
        elif name == 'get_exam_outlook':
            raise RuntimeFailure('outlook_requires_isolation','请通过“历年试卷主题”选择目标考年，开始独立分析。')
        spec = next((s for s in TOOL_SPECS if s['name'] == name), None)
        if spec is None or not isinstance(args, dict) or not (set(spec['inputSchema']['required']) <= set(args) <= set(spec['inputSchema']['properties'])):
            raise RuntimeFailure('invalid_tool', '模型工具或参数不在课程白名单中。')
        if name == 'search_evidence' and 'selection' in args:
            try:
                PaperSelection.model_validate(args['selection'])
            except ValidationError:
                raise RuntimeFailure('invalid_tool', '请提供本次选择的考年和试卷编号。') from None
        for key, value in args.items():
            schema = spec['inputSchema']['properties'][key]
            if schema['type'] == 'string' and (not isinstance(value, str) or '\0' in value or
                    len(value) > schema.get('maxLength', 4000) or
                    len(value.strip()) < schema.get('minLength', 0)):
                raise RuntimeFailure('invalid_tool', '模型工具参数无效。')
        if name == 'get_source_page' and (type(args['page']) is not int or args['page'] < 1):
            raise RuntimeFailure('invalid_tool', '原页页码无效。')
        if name == 'get_exam_outlook':
            result = self._exam_outlook(args)
        elif name == 'browse_course_materials':
            try:
                result = browse_materials(self.store, self.scope, args['offset'], self.course_id)
            except ValueError:
                raise RuntimeFailure('invalid_tool', '课件浏览起点无效。') from None
        elif name == 'prepare_knowledge_map':
            result = self._prepare_map(args)
        elif name == 'calculate':
            ids = args['source_ids']
            if not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(
                    not isinstance(eid, str) or eid not in self.evidence for eid in ids):
                raise RuntimeFailure('invalid_tool', '计算需要本轮取得的真实公式来源。')
            try:
                value = evaluate_expression(args['expression'], args['inputs'])
            except ValueError:
                raise RuntimeFailure('invalid_calculation', '无法安全计算该算式，请检查输入与公式。') from None
            eid = 'E' + str(len(self.evidence) + 1)
            refs = list({(ref['document_id'], ref['page']): ref
                         for sid in ids for ref in self.evidence[sid]['refs']}.values())
            warning = '计算由受限算术工具复算；公式适用性和单位解释仍需核对。'
            self.evidence[eid] = {'id': eid, 'snapshot': self.scope.snapshot, 'record_id': None,
                'title': '数值复算', 'text': f"{args['expression']} = {value} {args['units']}",
                'kind': 'calculation', 'refs': refs, 'limitations': [warning],
                'calculation': {**args, 'value': value}}
            reviews = {note['id']: note for sid in ids
                       for note in self.evidence[sid].get('source_reviews', [])}
            if reviews:
                self.evidence[eid]['source_reviews'] = list(reviews.values())
            self.limitations = list(dict.fromkeys([*self.limitations, warning]))
            result = {'value': value, 'units': args['units'], 'evidence_id': eid, 'source_ids': ids}
        else:
            bundle = getattr(self.service, name)(self.scope, **args)
            result = self._bundle(bundle)
            if name == 'search_evidence' and 'selection' not in args:
                # A high-ranked page can be one middle step of a longer chain.
                # Follow its exact source-page membership, without replacing the
                # original hits or asserting that page overlap proves relevance.
                top_pages = {(ref.document_id, ref.page) for record in bundle.records[:5]
                             if record.kind == 'block' for ref in record.refs}
                present = {record.id for record in bundle.records}
                chains = [(len(top_pages & {(ref.document_id, ref.page) for ref in record.refs}), record)
                          for record in self.store.list_records(self.scope, 'concept')
                          if record.details.get('derivation') and record.id not in present]
                chains = sorted((item for item in chains if item[0]), key=lambda item: (-item[0], item[1].id))
                if chains:
                    chain = chains[0][1]
                    result['related_derivation_candidate'] = {'id': chain.id, 'title': chain.title,
                        'reason': '包含已检索原页的跨页推导；需核对是否适用于当前问题。'}
                    base_state = self._checkpoint()
                    linked = self._bundle(self.service.get_concept(self.scope, chain.id))
                    merged = {**result}
                    for key in ('records', 'evidence', 'record_references'):
                        merged[key] = [*result[key], *linked[key]]
                    for key in ('reused_evidence_ids', 'limitations'):
                        merged[key] = list(dict.fromkeys([*result[key], *linked[key]]))
                    if linked.get('reuse_note'):
                        merged['reuse_note'] = linked['reuse_note']
                    wire = self._with_budget(merged, len(self.trace) + 1)
                    size = len(json.dumps(wire, ensure_ascii=False).encode('utf-8'))
                    if self._bytes + size <= 100000:
                        result = merged
                    else:
                        self._restore(base_state)
                        warning = '关联推导未能整组放入本轮预算，可用 get_concept 单独读取。'
                        result['limitations'].append(warning)
                        self.limitations = list(dict.fromkeys([*self.limitations, warning]))
        self.trace.append({'tool': name, 'arguments': args,
                           'evidence_ids': result['evidence_ids'] if name == 'get_exam_outlook' else list(self.evidence),
                           'limitations': result.get('limitations', [])})
        return result

    def _exam_outlook(self, args):
        from .exam_outlook import exam_outlook
        try:
            report = exam_outlook(self.store, self.scope, self.course_id, **args)
        except ValueError:
            raise RuntimeFailure('invalid_tool', '请检查目标年份、主题数量和资料范围。') from None
        ids = []
        for row in report['ranking']:
            refs = self._refs(row['sources'])
            for ref, source in zip(refs, row['sources']):
                if self.docs[ref['document_id']].kind != 'exam':
                    raise RuntimeFailure('invalid_source', '历年主题的证据必须来自可访问的正式题卷。')
                ref.update(record_id=source['record_id'], source_id=source['source_id'])
            item = {'snapshot':self.scope.snapshot, 'kind':'exam_topic', 'record_id':None,
                    'title':row['topic'], 'text':row['topic'] + ' · ' + '、'.join(str(y) for y in row['years']),
                    'target_year':report['target_year'], 'history_mode':report['history_mode'],
                    'refs':refs, 'limitations':report['limitations']}
            key = digest(item)
            eid = self._keys.get(key)
            if not eid:
                eid = 'E' + str(len(self.evidence) + 1)
                self._keys[key] = eid
                self.evidence[eid] = {**item,'id':eid}
            row['evidence_id'] = eid
            ids.append(eid)
        self.outlook = report
        return {'exam_outlook':report,'evidence_ids':ids,'limitations':report['limitations']}


    def _prepare_map(self, args):
        try:
            graph = prepare_map(self.store, self.scope, self.course_id, args)
        except ValueError:
            raise RuntimeFailure('invalid_knowledge_map', '知识结构未通过校验。请核对层级、原页和引文后重试。') from None
        ids, records = [], {}
        for node in graph['nodes']:
            for ref in node['support']:
                key = digest(['map_quote', ref['source_id'], ref['quote']])
                eid = self._keys.get(key)
                if not eid:
                    eid = 'E' + str(len(self.evidence) + 1)
                    refs = self._refs([ref])
                    record_id = f"{ref['document_id']}:p{ref['page']}"
                    if record_id not in records:
                        records[record_id] = self.store.get(self.scope, record_id)
                    record = records[record_id]
                    if record is None:
                        raise RuntimeFailure('invalid_source', '当前无法读取知识结构的原页。')
                    item = {'id': eid, 'source_id': ref['source_id'],
                        'record_id': record_id, 'kind': 'block', 'review': record.review,
                        'snapshot': self.scope.snapshot, 'title': ref['filename'], 'text': ref['quote'],
                        'refs': refs, 'limitations': self._warnings(record)}
                    if record.details.get('source_reviews'):
                        item['source_reviews'] = record.details['source_reviews']
                    self.evidence[eid] = item
                    self._keys[key] = eid
                ref['evidence_id'] = eid
                ids.append(eid)
        self.knowledge_map = graph
        return {'knowledge_map': graph, 'evidence_ids': list(dict.fromkeys(ids))}


def validate_answer(raw, tools, *, question=''):
    request = outlook_request(question) if question else None
    if request is not None and request != tools.outlook_args:
        raise RuntimeFailure('outlook_requires_isolation','本次结果与所问考年或资料范围不一致。请在“历年试卷主题”重新分析。')
    if tools.outlook_args:
        return _outlook_answer(tools, english=_english_outlook_question(question))
    try:
        answer = ModelAnswer.model_validate(raw)
    except ValidationError:
        raise RuntimeFailure('invalid_answer', '回答结构未通过校验，未展示为完整答案。') from None
    if not any(step['tool'] != 'calculate' for step in tools.trace):
        raise RuntimeFailure('evidence_not_checked', '本轮没有成功调用课程资料工具，尚未完成查证。请重试；这不表示课程资料缺失。')
    if question.lstrip().startswith(MAP_REQUEST_PREFIX) and tools.knowledge_map is None:
        raise RuntimeFailure('knowledge_map_missing', '本轮没有生成可按原页核对的知识结构。请缩小资料范围或重新生成。')
    used = []
    for paragraph in answer.paragraphs:
        if paragraph.kind in {'source', 'derivation'} and not paragraph.citations:
            raise RuntimeFailure('missing_citation', '回答中的资料结论缺少来源，未展示为已完成答案。')
        for eid in paragraph.citations:
            if eid not in tools.evidence:
                raise RuntimeFailure('invalid_citation', '回答引用了本轮未取得的来源，已拦截。')
            if eid not in used:
                used.append(eid)
    graph = tools.knowledge_map
    map_warnings = []
    if graph is not None:
        for node in graph['nodes']:
            map_warnings.extend(node['limitations'])
            for ref in node['support']:
                if ref['evidence_id'] not in used:
                    used.append(ref['evidence_id'])
    limitations = list(dict.fromkeys([*tools.limitations, *map_warnings, *answer.limitations]))
    return {'text': '\n\n'.join(p.text for p in answer.paragraphs),
            **({'knowledge_map': graph} if graph is not None else {}),
            'paragraphs': [p.model_dump() for p in answer.paragraphs],
            'evidence': [tools.evidence[eid] for eid in used], 'limitations': limitations,
            'trace': tools.trace, 'source_check': 'locations_validated_not_expert_reviewed'}


def _english_outlook_note(note):
    notes = {
        '可得日期未知。': 'Source availability dates are unknown.',
        '已核对短引的标签附有编制日期；其余题头索引的编制日期未经核验。': 'Labels checked against source excerpts have a compilation date. Dates for other question-heading indexes are unverified.',
        '主题标签来自当前快照，含候选映射；标签编制日期未经核验。': 'Topic labels come from the current snapshot and include tentative matches. Their compilation dates are unverified.',
        '按出现考年数、父题数、最近考年、标签字面顺序排列。每个主题最多示例三个年份，出现次数不能换算为出题概率。': 'Ranking uses the number of exam years, parent questions, most recent year and alphabetical label. Up to three years are shown per topic. Frequency does not establish its probability of appearing.',
        '没有明确考年、卷名学年与登记年份冲突或文件版本日期晚于所选上限的试卷不计入统计。': 'Papers with missing or conflicting exam years, or with a version date after the cutoff, are excluded.',
        '复习标签来自核对过的卷面标题或题干短引，可有多个。主题归纳待教师审核；同一主题在不同年份可能考查不同技能。': 'A question may have several labels drawn from verified headings or short excerpts. Topic groupings await instructor review. A topic may test different skills across years.',
        '仅统计可定位的卷面题头；未识别的题型、无主题标题或存在冲突的条目不参与排名。整卷大题总数与题答对应待审核。': 'Only traceable question headings count. Unrecognised formats, missing headings and conflicting entries are excluded. Question totals and answer matches await review.',
        '仅纳入截止日前有可得日期的来源。试卷封面日期不能证明当时可取得。': 'Only sources documented as available by the cutoff are included. A cover date alone cannot establish availability.',
        '按卷面考年回顾，部分年份仅有文件名学年标签。没有据此验证当年考前可得性。': 'The analysis uses paper years, some inferred from academic-year filenames. Availability before the exam is unverified.',
        '可用考年不足三个，排序对单份卷的内容敏感。': 'Fewer than three exam years are available, so one paper can strongly affect the ranking.',
        '部分试卷或大题缺少可核对的题目或主题，频次仅反映已定位的部分。': 'Some papers or questions lack verifiable questions or topics. Counts cover only the material located.',
        '当前范围内没有同时具备可定位父题和主题标签的往卷证据。': 'No past-paper evidence in this scope has both a traceable parent question and a topic label.',
    }
    numbered = re.fullmatch(r'另有 (\d+) 份卷可定位大题编号，但没有可用的主题题头。已计入大题覆盖。', note)
    if numbered:
        return f'{numbered[1]} additional papers have question numbers but no usable topic headings. They count towards question coverage.'
    gap = re.fullmatch(r'最近一次纳入的考年为 (\d+)，目标年之前有空档。缺卷年份不计作某主题没有考过。', note)
    if gap:
        return f'The latest included exam year is {gap[1]}. Missing years provide no evidence about which topics appeared.'
    return notes.get(note, note)


def _outlook_answer(tools, *, english=False):
    report = tools.outlook
    if report is None:
        raise RuntimeFailure('exam_outlook_missing','本轮没有取得所选范围内的往卷分析，请重试。')
    year = report['target_year']
    mode = '限考前可得资料' if report['history_mode'] == 'strict' else '按卷面考年回顾'
    rows = report['ranking']
    ids = [row['evidence_id'] for row in rows]
    if english:
        mode = 'sources available before the exam' if report['history_mode'] == 'strict' else 'by paper year'
        text = f'{year} revision priorities ({mode}). '
        if report['status'] == 'ranked' and rows:
            text += 'Earlier papers suggest reviewing ' + ', '.join(row['topic'] for row in rows) + '. See the years, question counts and source pages for each topic.'
            kind = 'derivation'
        else:
            text += 'The available past papers contain too little topic evidence to rank revision priorities.'
            kind = 'insufficient'
        report = {**report, 'limitations': [_english_outlook_note(note) for note in report['limitations']]}
    elif report['status'] == 'ranked' and rows:
        titles = '、'.join(row['topic'] for row in rows)
        text = f'{year} 年复习建议（{mode}）。按较早试卷的主题记录，可优先复习{titles}。下方列出各主题出现的年份、题数与原页。'
        kind = 'derivation'
    else:
        text = f'{year} 年复习建议（{mode}）。当前授权往卷缺少足以排列复习优先级的主题证据。'
        kind = 'insufficient'
    return {'text':text,'paragraphs':[{'kind':kind,'text':text,'citations':ids}],
            'exam_outlook':report,'evidence':[tools.evidence[eid] for eid in ids],
            'limitations':report['limitations'],'trace':tools.trace,'source_check':'locations_validated_not_expert_reviewed'}
