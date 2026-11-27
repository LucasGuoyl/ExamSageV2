'use strict';
(() => {
  if (!$('chatView')) return;
  const storageKey = 'examsage.chat.v1:' + (basePath || '/');
  const kindLabels = {source: '原文依据', derivation: '推导解释', assumption: '用户假设', insufficient: '证据不足'};
  const phaseLabels = {retrieving: '正在查找课程资料…', checking: '正在核对条件与来源…', answering: '正在整理回答…', generating: '正在整理回答…'};
  let sessions = [], currentSession = null, currentRun = null, history = [], scopeEpoch = 0;
  let busy = false, connecting = false, cancelling = false, ready = false, statusEpoch = 0;
  let timer = null, retryAction = null, pendingSend = null, rememberedRuns = {};
  const terminal = new Set();

  function readRemembered() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || '{}');
      const valid = id => typeof id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(id);
      rememberedRuns = Object.fromEntries(Object.entries(value.runs || {}).filter(([s, r]) => valid(s) && valid(r)));
      return valid(value.sessionId) ? value.sessionId : null;
    } catch { return null; }
  }
  function remember() {
    try { localStorage.setItem(storageKey, JSON.stringify({sessionId: currentSession, runs: rememberedRuns})); }
    catch { /* History remains in the server database when browser storage is unavailable. */ }
  }
  function current(epoch, sessionId = currentSession) { return epoch === scopeEpoch && sessionId === currentSession; }
  function running() { return currentRun && ['queued', 'running'].includes(currentRun.status); }
  function controls() {
    $('chatSend').disabled = !ready || busy || !!running() || !!pendingSend;
    $('chatMap').disabled = $('chatSend').disabled;
    $('chatOutlook').disabled = $('chatSend').disabled;
    $('chatInput').disabled = busy || !!running() || !!pendingSend;
    $('chatStop').disabled = !running() || cancelling;
    $('chatNew').disabled = busy;
    $('chatConnect').disabled = connecting;
    $('chatRetry').disabled = busy || cancelling;
  }
  function clearError() {
    retryAction = null; $('chatErrorBox').hidden = true; $('chatRetry').hidden = true;
    $('chatError').textContent = '';
  }
  function showError(message, retry = null, label = '重试') {
    $('chatErrorBox').hidden = false; $('chatError').textContent = String(message);
    retryAction = retry; $('chatRetry').hidden = !retry; $('chatRetry').textContent = label;
  }
  async function request(path, method = 'GET', body) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const options = {method, signal: controller.signal, cache: 'no-store'};
      if (method === 'POST') { options.headers = {'Content-Type': 'application/json'}; options.body = JSON.stringify(body || {}); }
      const response = await fetch(basePath + '/api/chat' + path, options);
      let value;
      try { value = await response.json(); } catch { value = null; }
      if (!response.ok) {
        const error = new Error(typeof value?.detail === 'string' ? value.detail : '请求未完成，请稍后重试。');
        error.status = response.status; throw error;
      }
      if (value === null) throw new Error('服务返回了无法读取的结果，请重试。');
      return value;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('等待服务超时。可以重试读取，或停止当前回答。');
      if (error instanceof TypeError) throw new Error('连接中断，暂时无法确认结果。请点击重试，不要重复新建问题。');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function connection(value) {
    ready = value.status === 'ready';
    $('chatConnectionLabel').textContent = ready ? '套餐连接可用' : value.status === 'unavailable' ? '套餐连接暂不可用' : '尚未检查套餐连接';
    $('chatConnectionLabel').parentElement.parentElement.dataset.status = value.status;
    const suffix = ready && value.generation_verified !== true ? '连接检查不代表真实回答已验证。' : '';
    $('chatConnectionMessage').textContent = [value.message, suffix, '仅使用现有 ChatGPT 套餐。'].filter(Boolean).join(' ');
    controls();
  }
  async function checkConnection() {
    if (connecting) return;
    connecting = true; controls(); const version = ++statusEpoch;
    $('chatConnectionLabel').textContent = '正在检查套餐连接…';
    try { const value = await request('/connect', 'POST', {}); if (version === statusEpoch) connection(value); }
    catch (error) { if (version === statusEpoch) connection({status: 'unavailable', message: error.message}); }
    finally { if (version === statusEpoch) { connecting = false; controls(); } }
  }
  function limitations(notes) {
    const unique = [...new Set((Array.isArray(notes) ? notes : []).filter(note => typeof note === 'string' && note.trim()))];
    if (!unique.length) return null;
    const box = el('div', undefined, 'chat-limitations');
    for (const note of unique) box.append(el('p', human(note)));
    return box;
  }

  function reviewView(note) {
    const box = el('aside', undefined, 'chat-source-review');
    box.append(el('strong', '学习注记 · 未经独立学术核查'), el('p', note.summary));
    const links = el('div', undefined, 'refs');
    for (const ref of note.evidence || []) {
      if (!ref || typeof ref.document_id !== 'string' || !Number.isInteger(ref.page) || ref.page < 1) continue;
      const name = docs[ref.document_id]?.relative_path?.split('/').pop() || ref.document_id;
      links.append(pageLink(ref.document_id, ref.page, name + ' · ' + ref.page));
    }
    box.append(links);
    return box;
  }
  function knowledgeMapView(graph) {
    const section = el('section', undefined, 'chat-knowledge-map');
    const kinds = {topic: '主题', method: '方法', application: '应用', worked_example: '例题'};
    section.append(el('h3', '课程知识结构'),
      el('p', '已引用 ' + graph.coverage.cited_pages + ' / ' + graph.coverage.visible_pages +
        ' 个可见原页。引文已与提取原文匹配，主题归类与解释待核查。', 'small'));
    const children = new Map();
    for (const node of graph.nodes) {
      if (!children.has(node.parent)) children.set(node.parent, []);
      children.get(node.parent).push(node);
    }
    function branch(parent) {
      const list = el('ul');
      for (const node of children.get(parent) || []) {
        const item = el('li');
        item.append(el('strong', node.title), el('span', kinds[node.kind], 'chat-kind'), el('p', node.summary));
        for (const ref of node.support) {
          const quote = el('blockquote', ref.quote);
          quote.append(pageLink(ref.document_id, ref.page, ref.filename + ' · 第 ' + ref.page + ' 页'));
          item.append(quote);
        }
        const note = limitations(node.limitations);
        if (note) item.append(note);
        if (children.has(node.id)) item.append(branch(node.id));
        list.append(item);
      }
      return list;
    }
    section.append(branch(''));
    const download = el('button', '下载知识结构 JSON');
    download.type = 'button';
    download.onclick = () => {
      const data = new Blob([JSON.stringify(graph, null, 2)], {type: 'application/json'});
      const url = URL.createObjectURL(data);
      const link = el('a'); link.href = url; link.download = 'course-knowledge-map.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    section.append(download);
    return section;
  }
  function topicEvidence(ref, label) {
    const origin=ref.label_origin==='printed_title'?'卷面标题':'题干短引';
    return el('p',(label?label+' · ':'')+'Q'+ref.question_number+' · '+origin+'：“'+ref.quote+'”','small');
  }
  function examOutlookView(report, reviewing=false) {
    const section = el('section', undefined, 'chat-exam-outlook');
    const mode = report.history_mode === 'strict' ? '限考前可得资料' : '按卷面考年回顾';
    section.append(el(reviewing?'h4':'h3', reviewing?'历史排名':report.target_year + ' 年复习主题'), el('p', mode));
    if (report.availability_cutoff) section.append(el('p','资料截止日：' + report.availability_cutoff));
    if (report.training_years.length) section.append(el('p', '纳入考年：' + report.training_years.join('、')));
    const coverage = report.coverage;
    const counts = coverage.heading_only
      ? '已定位 ' + coverage.parent_questions + ' 道大题，其中 ' + coverage.tagged_questions + ' 个有可用于统计的标签。'
      : coverage.parent_questions + ' 道大题，其中 ' + coverage.tagged_questions + ' 道有主题标签。';
    section.append(el('p', coverage.exam_papers + ' 份试卷 · ' + counts, 'small'));
    if (report.status === 'insufficient') {
      section.append(el('p', '可用往卷证据不足。'));
      if (report.unranked_reason === 'no_supported_topics') {
        section.append(el('p','已纳入往卷，但尚无能从父题原页核对的主题标签。','small'));
      } else if (report.history_mode === 'strict') {
        section.append(el('p','请核对往卷考年与可得日期。截止日之后取得的文件不能用于这次回看。','small'));
      }
    } else {
      const list = el('ol');
      for (const row of report.ranking) {
        const li = el('li'), refs = el('div', undefined, 'refs'), pages = new Set();
        li.append(el('strong', row.topic), el('p', row.year_count + ' 个考年 · ' +
          row.question_count + ' 道大题 · ' + row.years.join('、')));
        for (const ref of row.sources) {
          const key = ref.document_id + ':' + ref.page;
          if (pages.has(key)) continue;
          pages.add(key);
          refs.append(pageLink(ref.document_id, ref.page, ref.filename + ' · 第 ' + ref.page + ' 页',
                               reviewing || ref.availability || ref.quote ? ref.source_id : null));
          if (ref.quote) refs.append(topicEvidence(ref));
          if (ref.availability) refs.append(availabilityDetails(ref.availability));
        }
        li.append(refs);
        list.append(li);
      }
      section.append(list);
    }
    if (report.unlabelled_examples?.length) {
      const refs = el('div', undefined, 'refs');
      section.append(el('p','已定位、尚缺主题标签的原题举例。','small'));
      for (const ref of report.unlabelled_examples) {
        const label = ref.year + ' 年第 ' + ref.question_number + ' 题 · ' + ref.filename + ' 第 ' + ref.page + ' 页';
        refs.append(pageLink(ref.document_id, ref.page, label, ref.source_id));
      }
      section.append(refs);
    }
    return section;
  }

  function reviewSummary(report) {
    const body = $('examReviewBody'), forecast = report.outlook, metrics = report.metrics;
    body.append(el('h3',forecast.target_year+' 年逐题回测'));
    if (metrics) {
      body.append(el('p','返回的 '+metrics.predicted+' 个历史主题中，'+metrics.matched+' 个与目标卷标签匹配。目标卷共有 '+metrics.observed+' 个不同的已标注主题。'),
        el('p','按主题标签精确匹配，同义改名可能漏计；父题命中不能换算为小问分数。','small'));
    } else {
      const messages = {
        no_target:'当前范围没有可核定为该考年的正式目标卷，无法判断命中或误报。',
        no_forecast:'所选口径没有形成历史排名，无法计算命中率。',
        partial_target:'目标卷的题头或标签覆盖尚未确认，仅列出可核对的父题和匹配情况。'
      };
      body.append(el('p',messages[report.comparison_status]));
    }
    const historyBox=$('examReviewHistory');
    historyBox.append(examOutlookView(forecast,true));
    if (forecast.limitations?.length) {
      const box = el('details');
      box.append(el('summary','排名依据与限制'), limitations(forecast.limitations));
      historyBox.append(box);
    }
    for (const [title,values] of [
      ['目标卷中未入选的标签',report.new_to_prediction],
      ['入选后未见于目标卷已标注主题',report.unobserved_predictions],
      ['证据不足，尚无法核实的入选主题',report.unresolved_predictions]
    ]) {
      if (values.length) historyBox.append(el('p',title+'：'+values.join('、')));
    }
    const target=report.target_coverage;
    if (target.exam_papers) {
      body.append(el('h4','逐题核对'),el('p','目标卷 '+target.exam_papers+' 份，已登记 '+target.parent_questions+
        ' 道父题，其中 '+target.tagged_questions+' 道有主题标签。','small'));
      if (target.papers_without_parsed_questions) body.append(el('p','有 '+target.papers_without_parsed_questions+
        ' 份目标卷尚未定位到父题。','small'));
    }
  }
  function reviewRow(q, hasForecast) {
    const row=el('li'), ref=q.source;
    const status=!q.observed_topics.length?'无标签':!hasForecast?'无历史排名':
      !q.matched_topics.length?'未匹配':q.matched_topics.length===q.observed_topics.length?'匹配':'部分匹配';
    row.append(el('strong','Q'+q.question_number),el('span',status,'review-match'));
    if (q.observed_topics.length) row.append(el('p',q.observed_topics.join('、')));
    for (const evidence of q.topic_evidence || []) {
      row.append(topicEvidence(evidence,evidence.topic));
      if (evidence.source_id !== ref.source_id) {
        row.append(pageLink(evidence.document_id,evidence.page,evidence.filename+' · 第 '+evidence.page+' 页',evidence.source_id));
      }
    }
    if (status==='部分匹配') row.append(el('p','匹配主题：'+q.matched_topics.join('、'),'small'));
    row.append(pageLink(ref.document_id,ref.page,ref.filename+' · 第 '+ref.page+' 页',ref.source_id));
    return row;
  }
  let reviewRequest=null;
  function clearReview() {
    reviewRequest?.abort(); reviewRequest=null;
    $('examReview').hidden=true;
    $('examReviewBody').replaceChildren();
    $('examReviewHistory').replaceChildren();
    $('examReviewStatus').textContent='';
    $('reviewContinue').hidden=true;
    $('reviewContinue').onclick=null;
  }
  async function readReview(params, offset=0, scopeKey=null) {
    reviewRequest?.abort();
    const request=new AbortController();
    reviewRequest=request;
    const panel=$('examReview'), body=$('examReviewBody'), status=$('examReviewStatus'), more=$('reviewContinue');
    panel.hidden=false;
    if (!offset) { body.replaceChildren(); $('examReviewHistory').replaceChildren(); }
    status.textContent=offset?'正在读取下一批父题…':'正在核对历史排名和目标卷…';
    more.hidden=true;
    const query=new URLSearchParams({...params,offset});
    if (scopeKey) query.set('review_scope',scopeKey);
    try {
      const report=await api('/api/exam-outlook/review?'+query,{signal:request.signal});
      if (reviewRequest!==request) return;
      if (scopeKey && scopeKey!==report.review_scope) {
        const error=new Error('课程资料已变化，请重新回测。'); error.status=409; throw error;
      }
      if (!offset) {
        reviewSummary(report);
        if (report.target_questions_total) body.append(el('ul',undefined,'review-questions'));
      }
      const list=body.querySelector('.review-questions');
      for (const q of report.target_questions) list.append(reviewRow(q,report.outlook.ranking.length>0));
      status.textContent=list?'已显示 '+list.children.length+' / '+report.target_questions_total+' 道父题。':'';
      if (report.next_offset!==null) {
        more.textContent='下一批'; more.hidden=false;
        more.onclick=()=>readReview(params,report.next_offset,report.review_scope);
      }
    } catch (error) {
      if (reviewRequest!==request) return;
      const stale=[403,404,409,503].includes(error.status);
      if (stale) { body.replaceChildren(); $('examReviewHistory').replaceChildren(); }
      status.textContent=error.status?error.message:'暂时无法读取回测，请重试。';
      more.textContent='重试'; more.hidden=false;
      more.onclick=()=>readReview(params,stale?0:offset,stale?null:scopeKey);
    }
  }
  $('reviewYear').onclick=()=>{
    if (!$('chatOutlookForm').reportValidity()) return;
    readReview({target_year:$('outlookYear').value,top_k:$('outlookTopK').value,history_mode:$('outlookMode').value});
  };
  $('chatOutlookForm').addEventListener('input',clearReview);
  $('chatOutlookForm').addEventListener('change',clearReview);
  window.addEventListener('pagehide',clearReview);

  function answerView(answer, fallback) {
    const container = el('div', undefined, 'chat-answer');
    const evidence = new Map((Array.isArray(answer?.evidence) ? answer.evidence : []).map(item => [item.id, item]));
    const paragraphs = Array.isArray(answer?.paragraphs) && answer.paragraphs.length ? answer.paragraphs : [{text: answer?.text || fallback}];
    for (const paragraph of paragraphs) {
      if (typeof paragraph.text !== 'string') continue;
      const section = el('section', undefined, 'chat-paragraph');
      if (kindLabels[paragraph.kind]) {
        const label = el('span', kindLabels[paragraph.kind], 'chat-kind'); label.dataset.kind = paragraph.kind; section.append(label);
      }
      section.append(formattedText(paragraph.text));
      const refs = el('div', undefined, 'refs'), seen = new Set(), notes = [];
      const shownReviews = new Set();
      for (const id of Array.isArray(paragraph.citations) ? paragraph.citations : []) {
        const source = evidence.get(id);
        if (!source) { notes.push('部分引用无法定位，请结合原始资料核对。'); continue; }
        for (const ref of Array.isArray(source.refs) ? source.refs : []) {
          if (typeof ref.document_id !== 'string' || !Number.isInteger(ref.page) || ref.page < 1) continue;
          const key = ref.document_id + ':' + ref.page;
          if (!seen.has(key)) { seen.add(key); refs.append(pageLink(ref.document_id, ref.page,
            (ref.filename || docs[ref.document_id]?.relative_path.split('/').pop() || '来源') + ' · ' + ref.page)); }
        }
        notes.push(...(Array.isArray(source.limitations) ? source.limitations : []));
        for (const review of source.source_reviews || []) {
          if (review?.review === 'unverified_note' && !shownReviews.has(review.id)) {
            shownReviews.add(review.id);
            section.append(reviewView(review));
          }
        }
        if (source.kind === 'calculation' && source.calculation) {
          const calculation = source.calculation, content = el('div');
          content.append(el('p', '算式：' + calculation.expression));
          for (const [name, value] of Object.entries(calculation.inputs || {})) content.append(el('p', name + ' = ' + value));
          content.append(el('p', '工具计算结果：' + calculation.value + ' ' + (calculation.units || '')),
            el('p', '请核对公式适用条件和单位；来源定位校验不等于回答中的所有数值均已验证。', 'small'));
          const record = details('查看计算记录', content); record.className = 'chat-calculation'; section.append(record);
        }
      }
      if (refs.childElementCount) section.append(refs);
      const warning = limitations(notes); if (warning) section.append(warning);
      container.append(section);
    }
    if (answer?.knowledge_map?.schema_version === 'knowledge-map-v1') container.append(knowledgeMapView(answer.knowledge_map));
    if (answer?.exam_outlook) container.append(examOutlookView(answer.exam_outlook));
    const warning = limitations(answer?.limitations); if (warning) container.append(warning);
    return container;
  }
  function studentMessage(content){
    if(!content.startsWith('【选卷查题】'))return content;
    const end=content.indexOf('\n');
    if(end<0)return content;
    try{
      const choice=JSON.parse(content.slice('【选卷查题】'.length,end));
      const names=[choice.paper_id,choice.solution_id].filter(Boolean).map(id=>docs[id]?.relative_path||id);
      return '本次选卷 · '+choice.exam_year+' · '+names.join(' / ')+'\n'+content.slice(end+1);
    }catch{return content;}
  }
  function renderHistory(messages) {
    history = Array.isArray(messages) ? messages : [];
    $('chatMessages').replaceChildren();
    for (const message of history) {
      if (!['user', 'assistant'].includes(message.role) || typeof message.content !== 'string') continue;
      const article = el('article', undefined, 'chat-message ' + message.role);
      article.append(el('span', message.role === 'user' ? '你' : '押题宝', 'chat-role'));
      article.append(message.role === 'assistant' ? answerView(message.answer, message.content) : formattedText(studentMessage(message.content)));
      $('chatMessages').append(article);
    }
    if (!$('chatMessages').childElementCount) {
      const welcome = el('div', undefined, 'chat-welcome');
      welcome.append(el('strong', '从一个具体问题开始'), el('p', '可以问“为什么这样推导”，也可以给出年份和小问编号。后续追问会沿用当前会话的条件。'));
      $('chatMessages').append(welcome);
    }
    $('chatMessages').scrollTop = $('chatMessages').scrollHeight;
  }
  function renderSessions() {
    $('chatSessions').replaceChildren();
    for (const session of sessions) {
      const button = el('button', undefined, 'chat-session'); button.type = 'button';
      button.dataset.chatSession = session.id; button.setAttribute('aria-current', String(session.id === currentSession));
      button.append(el('span', session.title || '新对话'));
      const time = new Date(session.updated_at);
      if (!Number.isNaN(time.valueOf())) button.append(el('small', time.toLocaleString('zh-CN', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'})));
      button.onclick = () => selectSession(session.id); $('chatSessions').append(button);
    }
    if (!sessions.length) $('chatSessions').append(el('p', '当前课程还没有对话。', 'small'));
    $('chatSessionTitle').textContent = sessions.find(item => item.id === currentSession)?.title || '新对话';
  }
  async function refreshSessions(epoch) {
    const value = await request('/sessions');
    if (epoch !== undefined && epoch !== scopeEpoch) return;
    sessions = Array.isArray(value) ? value : []; renderSessions();
  }
  async function refreshHistory(epoch, sessionId) {
    const messages = await request('/sessions/' + encodeURIComponent(sessionId) + '/messages');
    if (current(epoch, sessionId)) renderHistory(messages);
  }
  function stopTimer() { clearTimeout(timer); timer = null; }
  async function applyRun(run, epoch, sessionId) {
    if (!current(epoch, sessionId) || run.session_id && run.session_id !== sessionId) return;
    if (terminal.has(run.id) && ['running', 'queued'].includes(run.status)) return;
    currentRun = run; rememberedRuns[sessionId] = run.id; remember(); controls();
    if (['running', 'queued'].includes(run.status)) {
      $('chatRunStatus').textContent = phaseLabels[run.phase] || '正在查找资料并整理回答…'; return;
    }
    terminal.add(run.id); stopTimer(); clearError();
    $('chatRunStatus').textContent = run.status === 'completed' ? '回答完成 · 可点击来源核对' : run.status === 'cancelled' ? '已停止这一轮回答' : '本轮回答未完成';
    try { await refreshHistory(epoch, sessionId); } catch (error) {
      if (current(epoch, sessionId)) showError(error.message, () => refreshCurrentHistory(), '重试读取历史');
    }
    if (!current(epoch, sessionId)) return;
    if (run.status === 'failed') {
      const question = run.question || [...history].reverse().find(m => m.role === 'user')?.content;
      showError(run.error?.message || '本轮未完成，请检查连接后明确重试。', question ? () => send(question) : null, '重新发送这条问题');
    }
    controls();
  }
  async function poll(epoch, sessionId, runId) {
    if (!current(epoch, sessionId)) return;
    stopTimer();
    try {
      const run = await request('/runs/' + encodeURIComponent(runId));
      if (!current(epoch, sessionId)) return;
      await applyRun(run, epoch, sessionId);
      if (current(epoch, sessionId) && currentRun?.id === runId && running()) timer = setTimeout(() => poll(epoch, sessionId, runId), 1000);
    } catch (error) {
      if (current(epoch, sessionId)) showError(error.message, () => poll(epoch, sessionId, runId), '重新获取结果');
    }
  }
  async function selectSession(sessionId) {
    const epoch = ++scopeEpoch; stopTimer(); currentSession = sessionId; currentRun = null;
    pendingSend = null; busy = true; cancelling = false; clearError(); remember(); renderSessions();
    $('chatRunStatus').textContent = '正在读取对话…'; $('chatMessages').replaceChildren(); controls();
    try {
      await refreshHistory(epoch, sessionId);
      if (!current(epoch, sessionId)) return;
      $('chatRunStatus').textContent = '';
      const serverRun = [...history].reverse().find(message => message.role === 'user' &&
        typeof message.run_id === 'string' && /^[a-zA-Z0-9_-]{1,160}$/.test(message.run_id))?.run_id;
      const runId = serverRun || rememberedRuns[sessionId];
      if (runId) await poll(epoch, sessionId, runId);
    } catch (error) {
      if (current(epoch, sessionId)) {
        $('chatRunStatus').textContent = '对话读取失败';
        showError(error.message, () => selectSession(sessionId), '重试读取对话');
        if (error.status === 404) { delete rememberedRuns[sessionId]; currentSession = null; remember(); }
      }
    } finally { if (epoch === scopeEpoch) { busy = false; controls(); } }
  }
  async function refreshCurrentHistory() {
    if (!currentSession) return;
    const epoch = scopeEpoch, sessionId = currentSession;
    try { await refreshHistory(epoch, sessionId); if (current(epoch, sessionId)) clearError(); }
    catch (error) { if (current(epoch, sessionId)) showError(error.message, refreshCurrentHistory, '重试读取历史'); }
  }
  async function newSession() {
    if (busy) return;
    const epoch = ++scopeEpoch; stopTimer(); currentRun = null; currentSession = null;
    pendingSend = null; busy = true; cancelling = false; clearError(); renderHistory([]); remember(); controls();
    $('chatRunStatus').textContent = '正在新建对话…';
    try {
      const session = await request('/sessions', 'POST', {title: '新对话'});
      if (epoch !== scopeEpoch) return;
      currentSession = session.id; sessions.unshift(session); remember(); renderSessions();
      $('chatInput').value = ''; $('chatRunStatus').textContent = '';
    } catch (error) { if (epoch === scopeEpoch) showError(error.message, newSession, '重试新建'); }
    finally { if (epoch === scopeEpoch) { busy = false; controls(); $('chatInput').focus(); } }
  }
  async function send(text, retry = false) {
    if (busy || running() || pendingSend && !retry) return;
    const question = String(text || '').trim(); if (!question || question.length > 4000) return;
    if (!ready) {
      showError('请先检查套餐连接，连接可用后再重新发送。本次重试尚未发出。',
        () => send(question, retry), retry ? '重试发送' : '重新发送这条问题');
      $('chatConnect').focus();
      return;
    }
    const epoch = ++scopeEpoch; stopTimer(); busy = true; clearError(); controls();
    try {
      if (!currentSession) {
        const session = await request('/sessions', 'POST', {title: '新对话'});
        if (epoch !== scopeEpoch) return;
        currentSession = session.id; sessions.unshift(session); remember(); renderSessions();
      }
      const sessionId = currentSession;
      if (!retry) pendingSend = {sessionId, text: question, id: crypto.randomUUID()};
      if (!pendingSend || pendingSend.sessionId !== sessionId) return;
      const payload = pendingSend;
      const run = await request('/sessions/' + encodeURIComponent(sessionId) + '/messages', 'POST',
        {text: payload.text, client_request_id: payload.id});
      if (!current(epoch, sessionId)) return;
      pendingSend = null;
      if ($('chatInput').value.trim() === question) $('chatInput').value = '';
      // Persist the accepted run before any secondary read can fail.
      await applyRun(run, epoch, sessionId);
      if (current(epoch, sessionId) && running()) {
        try { await refreshHistory(epoch, sessionId); }
        catch (error) { if (current(epoch, sessionId)) showError(error.message, refreshCurrentHistory, '重试读取历史'); }
        if (current(epoch, sessionId) && running()) timer = setTimeout(() => poll(epoch, sessionId, run.id), 1000);
      }
      await refreshSessions(epoch);
    } catch (error) {
      if (epoch === scopeEpoch) {
        if (error.status && error.status < 500) pendingSend = null;
        const retryPayload = pendingSend;
        showError(error.message, retryPayload ? () => send(retryPayload.text, true) : null, '重试发送');
      }
    } finally { if (epoch === scopeEpoch) { busy = false; controls(); } }
  }
  async function cancel() {
    if (!running() || cancelling) return;
    const epoch = scopeEpoch, sessionId = currentSession, runId = currentRun.id;
    cancelling = true; controls(); clearError(); stopTimer();
    $('chatRunStatus').textContent = '正在停止…';
    try {
      const run = await request('/runs/' + encodeURIComponent(runId) + '/cancel', 'POST', {});
      if (current(epoch, sessionId)) { cancelling = false; await applyRun(run, epoch, sessionId); }
    } catch (error) { if (current(epoch, sessionId)) showError(error.message, cancel, '重试停止'); }
    finally { if (current(epoch, sessionId)) { cancelling = false; controls(); } }
  }
  $('chatConnect').onclick = checkConnection; $('chatNew').onclick = newSession; $('chatStop').onclick = cancel;
  $('chatMap').onclick = () => send('【课程知识结构】请按课程资料整理主题、方法、应用和例题，为每项附上支持它的原页和引文。');
  $('outlookYear').value = String(new Date().getFullYear() + 1);
  $('chatOutlookForm').onsubmit = event => {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    const mode = $('outlookMode').value === 'strict' ? '限考前可得资料' : '按卷面考年回顾';
    send('【历年试卷主题】' + $('outlookYear').valueAsNumber + ' 年，' + mode + '。请根据往卷列出前' + $('outlookTopK').valueAsNumber + '个优先复习主题及来源；资料不足时说明原因。');
  };
  $('chatRetry').onclick = () => { const action = retryAction; clearError(); if (action) action(); };
  $('chatForm').addEventListener('selected-paper',event=>{
    send('【选卷查题】'+JSON.stringify(event.detail.selection)+'\n'+event.detail.query);
  });
  $('chatForm').onsubmit = event => { event.preventDefault(); send($('chatInput').value); };
  $('chatInput').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send($('chatInput').value); }
  });
  window.addEventListener('pagehide', stopTimer);
  renderHistory([]); controls();
  const remembered = readRemembered(), version = ++statusEpoch;
  request('/status').then(value => { if (version === statusEpoch) connection(value); })
    .catch(error => { if (version === statusEpoch) connection({status: 'unavailable', message: error.message}); });
  refreshSessions(scopeEpoch).then(() => {
    if (scopeEpoch !== 0) return;
    if (remembered && sessions.some(session => session.id === remembered)) selectSession(remembered);
    else { currentSession = null; remember(); }
  }).catch(error => { if (scopeEpoch === 0) showError(error.message, () => refreshSessions(scopeEpoch), '重试读取会话列表'); });
})();
