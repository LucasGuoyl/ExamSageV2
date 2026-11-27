"""In-process, bounded chat runs; no external scheduler or paid fallback."""
import atexit
import os
from functools import lru_cache
from pathlib import Path
import threading

from .chat_service import CourseTools, TOOL_SPECS, build_context, outlook_request, selected_paper_request, selected_source_reply, validate_answer
from .chat_store import ChatStore, ChatConflict
from .course_profile import course_registration
from .model_runtime import RuntimeFailure, SubscriptionAnswer, SubscriptionRuntime
from .search import wants_answer


# Identifies the loaded module, not whatever source is later edited on disk.
RUNTIME_REVISION = '2026-11-25-subscription-receipt-1'


class ChatRunner:
    def __init__(self, data: Path, *, runtime=None):
        self.data = Path(data).resolve()
        self.store = ChatStore(self.data / 'chat.sqlite3')
        self.store.recover_interrupted()
        self.runtime = runtime or SubscriptionRuntime(self.data)
        self.lock = threading.RLock()
        self.active = {}
        self.workers = {}
        self.phases = {}
        self.closed = False
        self.connection = {'status': 'unchecked', 'generation_verified': False,
            'message': '尚未检查套餐连接。仅支持个人本机 ChatGPT 套餐，不使用 API Key 或 API 额度。'}

    def status(self):
        with self.lock:
            return {**self.connection, 'runtime_revision': RUNTIME_REVISION, 'server_pid': os.getpid(),
                    'course_tools': [spec['name'] for spec in TOOL_SPECS]}

    def check_connection(self):
        with self.lock:
            if self.active:
                raise ChatConflict('已有回答正在进行，请完成或停止后再检查连接。')
            try:
                result = self.runtime.probe()
                self.connection = {**result, 'message': '套餐登录与模型列表可用；实际生成仍需完成一次提问验证。'}
            except RuntimeFailure as exc:
                self.connection = {'status': 'unavailable', 'code': exc.code,
                                   'message': str(exc), 'generation_verified': False}
            except Exception:
                self.connection = {'status': 'unavailable', 'code': 'connection_error',
                    'message': '连接检查失败；未启用其他计费方式。', 'generation_verified': False}
            return self.status()

    def submit(self, course_store, scope, session_id, text, request_id, scope_guard=None, course_id=None):
        with self.lock:
            if self.closed:
                raise ChatConflict('服务正在关闭，请稍后重新打开。')
            run = self.store.begin_run(scope, session_id, text, request_id)
            rid = run['id']
            if run['status'] != 'running' or rid in self.active:
                return run
            if self.active:
                self.store.fail_run(scope, rid, 'busy', '当前套餐已有回答进行中，请稍后重试。')
                return self.store.get_run(scope, rid)
            cancel = threading.Event()
            self.active[rid] = cancel
            self.phases[rid] = 'connecting'
            worker = threading.Thread(target=self._work, args=(course_store, scope.model_copy(deep=True), run, cancel, scope_guard, course_id),
                                      name='examsage-chat', daemon=True)
            self.workers[rid] = worker
            worker.start()
            return run

    def _work(self, course_store, scope, run, cancel, scope_guard, course_id):
        rid = run['id']
        tools = None
        def guard():
            if scope_guard is not None:
                try: valid = scope_guard()
                except Exception: valid = False
                if valid is False:
                    cancel.set()
                    raise RuntimeFailure('scope_changed', '课程资料或可访问范围已变化，本轮已停止；请重启后新建对话。')
        def phase(value):
            with self.lock:
                if rid in self.active: self.phases[rid] = value
        try:
            guard()
            history = self.store.messages(scope, run['session_id'])
            last_answer = next(((m.get('answer') or {}) for m in reversed(history)
                                if m['role'] == 'assistant'), {})
            previous = last_answer.get('selected_paper') if len(history)>1 and history[-2]['role']=='assistant' else None
            selected = selected_paper_request(run['question'], previous)
            expected = outlook_request(run['question'], last_answer.get('exam_outlook'))
            if selected and expected:
                raise RuntimeFailure('invalid_paper_selection', '按所选原卷查小问和预测复习主题请分别提问。')
            if expected:
                # Free text and previous messages can contain held-out questions and answers.
                prompt = (f"请调用 get_exam_outlook，target_year={expected['target_year']}，"
                          f"history_mode={expected['history_mode']}，top_k={expected['top_k']}。")
                messages = [{'role':'user','content':prompt}]
                specs = [spec for spec in TOOL_SPECS if spec['name'] == 'get_exam_outlook']
            elif selected:
                messages = [{'role':'user','content':selected['query']+'。请用 search_evidence 查我选定的原卷。'}]
                specs = [spec for spec in TOOL_SPECS if spec['name'] in {'search_evidence','calculate'}]
            else:
                messages = history
                specs = [spec for spec in TOOL_SPECS if spec['name'] != 'get_exam_outlook']
            registration = None
            if not (expected or selected or scope.cutoff or scope.strict_history):
                registration = course_registration(course_store, scope)
            context = build_context(messages, scope.course, registration=registration)
            tools = CourseTools(course_store, scope, course_id=course_id, outlook_args=expected)
            # Only this host binds files from a student's explicit request. The
            # model searches by text, including when it is using a selected pair.
            specs = [({**spec, 'description': (
                       '按 query 检索当前课程证据。定位考题用考年和准确题号，例如 2025 Q3(b)(i)。'
                       '对照讲义时，另用原题中的学科术语检索。逐段引用对应证据，标明物理页码。'
                       if not selected else '用 query 请求学生已选的试卷与小问。'),
                       'inputSchema':{**spec['inputSchema'],
                       'properties':{'query':spec['inputSchema']['properties']['query']}}}
                      if spec['name']=='search_evidence' else spec) for spec in specs]
            selected_result = None
            if selected:
                guard()
                selected_result = tools.call('search_evidence', selected)
            delivered = False
            def call(name, args):
                nonlocal delivered
                if cancel.is_set(): raise RuntimeFailure('cancelled', '已停止本次回答。')
                guard()
                if name=='search_evidence' and isinstance(args,dict) and 'selection' in args:
                    raise RuntimeFailure('invalid_paper_selection','请通过选卷入口明确指定文件。')
                if selected and name not in {'search_evidence','calculate'}:
                    raise RuntimeFailure('invalid_paper_selection','本轮只查所选试卷与答案。')
                if selected and name=='search_evidence' and not delivered:
                    delivered = True
                    result = selected_result
                else:
                    result = tools.call(name, selected if selected and name=='search_evidence' else args)
                guard()
                return result
            source_only = selected and (selected_result['sufficiency']=='insufficient' or not wants_answer(selected['query']))
            if source_only:
                raw = selected_source_reply(selected_result)
            else:
                raw = self.runtime.generate(context, specs, call, cancel, phase, before_send=guard)
                if selected and not delivered:
                    raise RuntimeFailure('evidence_not_checked','本轮未读取选定的小问证据，请重试。')
            guard()
            if cancel.is_set(): raise RuntimeFailure('cancelled', '已停止本次回答。')
            phase('validating')
            answer = validate_answer(raw, tools, question=run['question'])
            if isinstance(raw, SubscriptionAnswer):
                answer['subscription_verified'] = True
            if selected:
                answer['selected_paper'] = selected
            guard()
            if self.store.finish_run(scope, rid, answer) and not source_only:
                with self.lock:
                    self.connection = {**self.connection, 'status': 'ready', 'generation_verified': True,
                                       'message': '已完成套餐模型回答；引用定位已检查，科学正确性仍需核对。'}
        except RuntimeFailure as exc:
            self.store.fail_run(scope, rid, exc.code, str(exc), diagnostics={
                'trace': tools.trace if tools is not None else [], 'failure': exc.details})
            if exc.code in {'startup_denied', 'connection_closed', 'chatgpt_login_required', 'usage_limit', 'usage_unknown', 'not_installed'}:
                with self.lock:
                    self.connection = {'status': 'unavailable', 'code': exc.code,
                                       'message': str(exc), 'generation_verified': False}
        except Exception:
            self.store.fail_run(scope, rid, 'internal_error', '本轮处理出现错误，未保存为完整回答；可以明确重试。')
        finally:
            with self.lock:
                self.active.pop(rid, None)
                self.workers.pop(rid, None)
                self.phases.pop(rid, None)

    def get_run(self, scope, rid):
        result = self.store.get_run(scope, rid)
        with self.lock:
            return {**result, 'phase': self.phases.get(rid, result['status'])}

    def cancel(self, scope, rid):
        with self.lock:
            result = self.store.cancel_run(scope, rid)
            if rid in self.active: self.active[rid].set()
            return result

    def close(self):
        with self.lock:
            self.closed = True
            for cancel in self.active.values(): cancel.set()
            workers = list(self.workers.values())
        for worker in workers:
            worker.join(timeout=4)


@lru_cache(maxsize=16)
def get_runner(data: Path):
    runner = ChatRunner(data)
    atexit.register(runner.close)
    return runner
