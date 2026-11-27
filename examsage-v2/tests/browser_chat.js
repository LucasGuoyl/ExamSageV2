async (page) => {
  // UI-only response simulation: no live model, authentication, or course service calls.
  const origin = page.__chatQaOrigin || 'http://127.0.0.1:8766';
  // A runner may supply current local static files on page.__chatQaAssets when no server is running.
  const assets = page.__chatQaAssets || {};
  if (!page.__chatQaAssets) {
    for (const name of ['index.html', 'app.js', 'app.css', 'chat.js', 'chat.css']) {
      const response = await page.request.get(origin + (name === 'index.html' ? '/' : '/static/' + name));
      if (response.ok()) assets[name] = await response.text();
    }
  }
  const qa = await page.context().newPage();
  const results = [], requests = [], saved = {};
  const storageKeys = ['examsage.chat.v1:/', 'examsage.chat.v1:/courses/ses'];
  const check = (name, passed, extra = {}) => results.push({name, passed: !!passed, ...extra});
  const summary = () => ({mode: 'intercepted-ui-only-no-model', total: results.length,
    passed: results.filter(r => r.passed).length, results});
  const injection = '<img src=x onerror="window.__chatInjected=1">';
  const answer = {
    text: '已模拟返回的回答 ' + injection,
    paragraphs: [
      {text: '资料文字 ' + injection, kind: 'source', citations: ['E1']},
      {text: '推导解释 \\(v=q/\\phi\\)', kind: 'derivation', citations: ['E2']},
      {text: '采用你给出的孔隙度。', kind: 'assumption', citations: []},
      {text: '未找到官方答案。', kind: 'insufficient', citations: []}
    ],
    evidence: [{id: 'E1', title: '来源标题', text: '原文片段', kind: 'block',
      refs: [{document_id: 'qa-doc', page: 9, filename: 'QA课件.pdf', sha256: 'a'.repeat(64)}],
      limitations: ['本页内容仍待独立核查。']},
      {id:'E2',title:'数值复算',kind:'calculation',text:'q / porosity = 8 m/day',
       source_reviews:[{id:'r',summary:'数值须结合两页核对。',review:'unverified_note',
         evidence:[{document_id:'qa-doc',page:9},{document_id:'supplement',page:2}]}],
       refs:[{document_id:'qa-doc',page:9,filename:'QA课件.pdf',sha256:'a'.repeat(64)}],limitations:[],
       calculation:{expression:'q / porosity',inputs:{q:2,porosity:0.25},value:8,units:'m/day',source_ids:['E1']}}],
    limitations: ['No official exam solution supplied.']
  };
  const states = {};
  for (const prefix of ['', '/courses/ses']) {
    const id = prefix ? 'ses-history' : 'grt-history';
    states[prefix] = {status: 'unchecked', connects: 0, counter: 0, mode: 'normal', runs: {},
      sessions: [{id, title: prefix ? 'SES 会话' : 'GRT 会话', updated_at: '2026-11-11T00:00:00Z'},
        {id: id + '-other', title: '另一会话', updated_at: '2026-11-10T00:00:00Z'}],
      messages: {[id]: [{role: 'user', content: prefix ? 'SES 独立历史' : 'GRT 历史问题'},
        {role: 'assistant', content: answer.text, answer}],
        [id + '-other']: [{role: 'user', content: '另一会话独有内容'}]}};
  }
  let delayedStarted, releaseDelayed;
  const finish = (state, run) => {
    if (run.status === 'running') {
      run.status = 'completed'; run.answer = answer;
      state.messages[run.session_id].push({role: 'assistant', content: answer.text, answer});
    }
    return run;
  };
  const routeHandler = async route => {
    const request = route.request(), url = new URL(request.url());
    const prefix = url.pathname.startsWith('/courses/ses/') ? '/courses/ses' : '';
    const local = url.pathname.slice(prefix.length), state = states[prefix];
    const body = request.method() === 'POST' ? request.postDataJSON() : null;
    requests.push({path: url.pathname, method: request.method(), body, contentType: request.headers()['content-type']});
    const json = (data, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data)});
    if (local === '/__chat_qa_storage__') return route.fulfill({contentType: 'text/html', body: '<!doctype html><title>Chat UI fixture</title>'});
    if (local === '/') return route.fulfill({contentType: 'text/html', body: assets['index.html']});
    if (local.startsWith('/static/')) {
      const name = local.slice('/static/'.length);
      if (assets[name] !== undefined) return route.fulfill({contentType: name.endsWith('.css') ? 'text/css' : 'text/javascript', body: assets[name]});
      // The UI cases do not validate math typesetting; production KaTeX is tested separately.
      if (name.startsWith('vendor/')) return route.fulfill({contentType: name.endsWith('.css') ? 'text/css' : 'text/javascript', body: ''});
      return route.fulfill({status: 404, body: 'missing static file'});
    }
    if (local === '/api/status') return json({course: prefix ? 'SES 测试课程' : 'GRT 测试课程', course_key: prefix ? 'ses' : 'grt',
      structure_mode: 'curated', topics: [], counts: {}, documents: 1, pages: 9, notice: '界面模拟测试', exam_years: [2024]});
    if (local === '/api/documents') return json([{id: 'qa-doc', relative_path: 'QA课件.pdf', pages: 9, kind: 'lecture'},
      {id: 'supplement', relative_path: '注记依据.pdf', pages: 2, kind: 'lecture'}]);
    if (local === '/api/courses') return json([{slug: 'grt', name: 'GRT 测试课程', url: '/'}, {slug: 'ses', name: 'SES 测试课程', url: '/courses/ses/'}]);
    if (local.startsWith('/api/records')) return json([]);
    if (local === '/api/page/supplement/2') return json({document:{id:'supplement',relative_path:'注记依据.pdf',pages:2},
      bundle:{records:[{text:'第二份依据',details:{}}]},preview_url:null,media_urls:[]});
    if (local.startsWith('/api/page/')) return json({document: {id: 'qa-doc', relative_path: 'QA课件.pdf', pages: 9},
      bundle: {records: [{text: '原页文字', details: {}}]}, preview_url: null, media_urls: []});
    if (local === '/api/chat/status' || local === '/api/chat/connect') {
      if (local.endsWith('connect')) { state.connects++; if (!state.failConnect) state.status = 'ready'; }
      return json({status: state.status, message: state.status === 'ready' ? '套餐连接可用' : state.status === 'unavailable' ? '套餐连接暂不可用' : '尚未检查套餐连接', generation_verified: false});
    }
    if (local === '/api/chat/sessions') {
      if (request.method() === 'POST') {
        const id = (prefix ? 'ses-' : 'grt-') + (++state.counter);
        const session = {id, title: body.title, updated_at: '2026-11-11T00:00:00Z'};
        state.sessions.unshift(session); state.messages[id] = []; return json(session);
      }
      return json(state.sessions);
    }
    const messagesMatch = local.match(/^\/api\/chat\/sessions\/([^/]+)\/messages$/);
    if (messagesMatch) {
      const id = decodeURIComponent(messagesMatch[1]);
      if (!state.messages[id]) return json({detail: '会话不在当前课程中。'}, 404);
      if (request.method() === 'GET') {
        if (state.delayHistoryNext) {
          state.delayHistoryNext = false;
          await new Promise(resolve => {releaseDelayed = resolve; if (delayedStarted) delayedStarted();});
        }
        if (state.failHistoryOnce) { state.failHistoryOnce = false; return json({detail: '模拟历史读取失败'}, 503); }
        return json(state.messages[id]);
      }
      let run = Object.values(state.runs).find(r => r.session_id === id && r.request_id === body.client_request_id);
      if (!run) {
        run = {id: 'run-' + (++state.counter), session_id: id, status: 'running', question: body.text,
          request_id: body.client_request_id, mode: state.mode, polls: 0};
        state.runs[run.id] = run; state.messages[id].push({role: 'user', content: body.text, run_id: run.id});
        if (state.mode === 'lost-reply') { state.mode = 'normal'; run.mode = 'normal'; return route.abort('failed'); }
        if (state.mode === 'lost-reply-hold') { state.mode = 'normal'; run.mode = 'hold'; return route.abort('failed'); }
      }
      return json(run);
    }
    const runMatch = local.match(/^\/api\/chat\/runs\/([^/]+)(\/cancel)?$/);
    if (runMatch) {
      const run = state.runs[decodeURIComponent(runMatch[1])];
      if (!run) return json({detail: '运行不在当前课程中。'}, 404);
      if (runMatch[2]) {
        if (run.status === 'running') run.status = 'cancelled';
        if (run.mode === 'cancel-history') state.delayHistoryNext = true;
        return json(run);
      }
      run.polls++;
      if (run.mode === 'failed') { run.status = 'failed'; run.error = {code: 'model_failure', message: '模拟生成失败，请明确重试'}; return json(run); }
      if (run.mode === 'poll-error' && run.polls === 1) return json({detail: '模拟断线：结果暂未读取。'}, 503);
      if (run.mode === 'late-terminal' && run.polls === 1) {
        await new Promise(resolve => {releaseDelayed = resolve; if (delayedStarted) delayedStarted();});
        return json({...run, status: 'cancelled'});
      }
      if (run.mode === 'delayed' && run.polls === 1) {
        await new Promise(resolve => {releaseDelayed = resolve; if (delayedStarted) delayedStarted();});
        return json(finish(state, run));
      }
      if (!['hold','cancel-history'].includes(run.mode)) finish(state, run);
      return json(run);
    }
    return json({detail: '界面测试未声明此请求'}, 404);
  };
  await qa.route(origin + '/**', routeHandler);
  try {
    await qa.goto(origin + '/__chat_qa_storage__', {waitUntil: 'domcontentloaded'});
    for (const key of storageKeys) saved[key] = await qa.evaluate(key => localStorage.getItem(key), key);
    await qa.evaluate(keys => keys.forEach(key => localStorage.removeItem(key)), storageKeys);
    await qa.goto(origin + '/', {waitUntil: 'domcontentloaded'});
    if (!await qa.locator('#chatNav').count()) { check('存在学习对话入口', false); return summary(); }
    await qa.locator('#chatConnect').waitFor();
    check('默认显示学习对话且不自动检查套餐', await qa.locator('#chatView').isVisible() && states[''].connects === 0);
    check('未检查连接时发送禁用', await qa.locator('#chatSend').isDisabled());
    await qa.locator('[data-chat-session="grt-history"]').click();
    await qa.getByText('GRT 历史问题', {exact: true}).waitFor();
    check('历史文本安全呈现且不会执行 HTML', await qa.locator('#chatMessages').innerText().then(t => t.includes(injection)) &&
      await qa.locator('#chatMessages img').count() === 0 && !await qa.evaluate(() => window.__chatInjected));
    check('原文推导假设不足及限制分别呈现', await qa.locator('#chatMessages').innerText().then(t =>
      ['原文依据', '推导解释', '用户假设', '证据不足', '未提供官方考试答案'].every(s => t.includes(s))));
    const calculation = qa.locator('.chat-calculation').first();
    check('计算段单独显示学习注记与两页依据', await qa.locator('.chat-source-review').count()===1 &&
      await qa.locator('.chat-source-review .ref').count()===2 &&
      await qa.locator('.chat-source-review').innerText().then(t=>t.includes('未经独立学术核查')));
    const secondPage = qa.locator('.chat-source-review [data-document="supplement"]');
    if (await secondPage.count()) {
      await secondPage.click();
      await qa.locator('#pageTitle').filter({hasText:'注记依据.pdf · 2'}).waitFor();
      check('可打开第二份注记依据原页', (await qa.locator('#pageContent').innerText()).includes('第二份依据'));
      await qa.locator('#close').click();
    } else check('可打开第二份注记依据原页',false);
    if (await calculation.count()) {
      await calculation.locator('summary').click();
      check('可查看计算输入算式结果及单位', await calculation.innerText().then(t =>
        ['q / porosity', '0.25', '8', 'm/day'].every(s => t.includes(s))));
    } else check('可查看计算输入算式结果及单位', false);
    await qa.locator('#chatMessages .ref').first().click();
    await qa.locator('#overlay[open]').waitFor();
    await qa.locator('#pageTitle').filter({hasText:'QA课件.pdf · 9'}).waitFor();
    check('回答引用可以打开现有原页窗口', await qa.locator('#pageTitle').innerText().then(t => t.includes('QA课件')));
    await qa.locator('#close').click();
    await qa.locator('#chatConnect').click();
    await qa.waitForFunction(() => !document.querySelector('#chatSend').disabled);
    await qa.locator('#chatInput').fill('第一行'); await qa.locator('#chatInput').press('Shift+Enter');
    await qa.locator('#chatInput').press('a');
    check('Shift+Enter 换行', (await qa.locator('#chatInput').inputValue()).includes('\n'));
    await qa.locator('#chatInput').fill('检查重复发送');
    await qa.evaluate(() => { document.querySelector('#chatForm').requestSubmit(); document.querySelector('#chatForm').requestSubmit(); });
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('回答完成'));
    check('重复提交只发送一次并显示完成回答', requests.filter(r => r.method === 'POST' && r.body?.text === '检查重复发送').length === 1);
    await qa.reload({waitUntil: 'domcontentloaded'});
    await qa.getByText('检查重复发送', {exact: true}).waitFor();
    check('刷新恢复历史且不再次检查套餐', states[''].connects === 1);
    const stored = await qa.evaluate(key => localStorage.getItem(key), storageKeys[0]);
    check('浏览器仅保存会话和运行编号', !stored.includes('检查重复发送') && !stored.includes('资料文字'));

    states[''].mode = 'hold';
    await qa.locator('#chatInput').fill('请停止这一轮'); await qa.locator('#chatInput').press('Enter');
    await qa.waitForFunction(() => !document.querySelector('#chatStop').disabled);
    await qa.locator('#chatStop').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('已停止'));
    check('停止不会把部分内容当完整回答', Object.values(states[''].runs).some(r => r.question === '请停止这一轮' && r.status === 'cancelled'));

    states[''].failHistoryOnce = true;
    await qa.locator('#chatInput').fill('刷新恢复运行'); await qa.locator('#chatInput').press('Enter');
    await qa.getByText('模拟历史读取失败', {exact: true}).waitFor();
    const acceptedRun = Object.values(states[''].runs).find(r => r.question === '刷新恢复运行');
    const acceptedRemembered = await qa.evaluate(key => JSON.parse(localStorage.getItem(key)), storageKeys[0]);
    const acceptedSaved = acceptedRemembered.runs['grt-history'] === acceptedRun.id;
    check('发送已受理而历史读取失败仍保留运行编号', acceptedSaved);
    if (!acceptedSaved) return summary();
    await qa.waitForFunction(() => !document.querySelector('#chatStop').disabled);
    await qa.reload({waitUntil: 'domcontentloaded'});
    await qa.waitForFunction(() => !document.querySelector('#chatStop').disabled);
    check('刷新后继续读取当前运行', true);
    await qa.locator('#chatStop').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('已停止'));

    states[''].mode = 'lost-reply';
    await qa.locator('#chatInput').fill('提交后响应丢失'); await qa.locator('#chatInput').press('Enter');
    await qa.locator('#chatRetry:not([hidden])').waitFor(); await qa.locator('#chatRetry').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('回答完成'));
    const retries = requests.filter(r => r.method === 'POST' && r.body?.text === '提交后响应丢失');
    check('断线重发复用请求编号避免重复生成', retries.length === 2 && retries[0].body.client_request_id === retries[1].body.client_request_id);

    states[''].mode = 'lost-reply-hold';
    await qa.locator('#chatInput').fill('提交响应丢失后刷新'); await qa.locator('#chatInput').press('Enter');
    await qa.locator('#chatRetry:not([hidden])').waitFor();
    await qa.reload({waitUntil: 'domcontentloaded'});
    await qa.getByText('提交响应丢失后刷新', {exact: true}).waitFor();
    await qa.waitForTimeout(250);
    const recoveredLost = !await qa.locator('#chatStop').isDisabled() && await qa.locator('#chatSend').isDisabled();
    check('提交响应丢失后刷新能恢复服务端运行', recoveredLost);
    if (!recoveredLost) return summary();
    await qa.locator('#chatStop').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('已停止'));

    states[''].mode = 'poll-error';
    await qa.locator('#chatInput').fill('读取中断后继续'); await qa.locator('#chatInput').press('Enter');
    await qa.locator('#chatRetry:not([hidden])').waitFor();
    check('读取失败显示后端说明并等待手动重试', (await qa.locator('#chatError').innerText()).includes('模拟断线'));
    await qa.locator('#chatRetry').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('回答完成'));
    check('重试读取不会重新发送问题', requests.filter(r => r.method === 'POST' && r.body?.text === '读取中断后继续').length === 1);

    states[''].mode = 'failed';
    await qa.locator('#chatInput').fill('生成失败后重试'); await qa.locator('#chatInput').press('Enter');
    await qa.getByText('模拟生成失败，请明确重试', {exact: true}).waitFor();
    check('生成失败明确呈现且不自动重发', requests.filter(r => r.method === 'POST' && r.body?.text === '生成失败后重试').length === 1);
    states[''].status = 'unchecked';
    await qa.reload({waitUntil: 'domcontentloaded'});
    await qa.getByText('模拟生成失败，请明确重试', {exact: true}).waitFor();
    await qa.locator('#chatRetry').click();
    check('重载后未检查连接的重试保留问题并明确提示',
      await qa.locator('#chatError').textContent().then(t => t.includes('套餐连接')) &&
      await qa.locator('#chatRetry').isVisible());
    check('连接未检查时不会提交重试问题', requests.filter(r => r.method === 'POST' && r.body?.text === '生成失败后重试').length === 1);
    await qa.locator('#chatConnect').click();
    await qa.waitForFunction(() => !document.querySelector('#chatSend').disabled);
    states[''].mode = 'normal'; await qa.locator('#chatRetry').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('回答完成'));
    const failedRetries = requests.filter(r => r.method === 'POST' && r.body?.text === '生成失败后重试');
    check('明确重试失败生成会创建新请求', failedRetries.length === 2 && failedRetries[0].body.client_request_id !== failedRetries[1].body.client_request_id);

    states[''].mode = 'late-terminal';
    const staleTerminal = new Promise(resolve => delayedStarted = resolve);
    await qa.locator('#chatInput').fill('等待迟到终态的旧轮'); await qa.locator('#chatInput').press('Enter');
    await staleTerminal; await qa.locator('#chatStop').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('已停止'));
    states[''].mode = 'hold';
    await qa.locator('#chatInput').fill('同一会话中的新轮'); await qa.locator('#chatInput').press('Enter');
    await qa.waitForFunction(() => !document.querySelector('#chatStop').disabled);
    const newest = Object.values(states[''].runs).find(r => r.question === '同一会话中的新轮');
    releaseDelayed(); await qa.waitForTimeout(250);
    const rememberedAfterLate = await qa.evaluate(key => JSON.parse(localStorage.getItem(key)), storageKeys[0]);
    const stillCurrent = rememberedAfterLate.runs['grt-history'] === newest.id && !await qa.locator('#chatStop').isDisabled();
    check('同一会话旧轮迟到终态不覆盖新轮', stillCurrent);
    if (!stillCurrent) return summary();
    await qa.locator('#chatStop').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('已停止'));

    states[''].mode = 'cancel-history';
    await qa.locator('#chatInput').fill('取消后历史读取延迟'); await qa.locator('#chatInput').press('Enter');
    await qa.waitForFunction(() => !document.querySelector('#chatStop').disabled);
    const cancelHistory = new Promise(resolve => delayedStarted = resolve);
    await qa.locator('#chatStop').click(); await cancelHistory;
    states[''].mode = 'hold';
    await qa.locator('#chatInput').fill('取消后立即开始的新轮'); await qa.locator('#chatInput').press('Enter');
    await qa.getByText('取消后立即开始的新轮', {exact: true}).waitFor();
    const canStopNew = !await qa.locator('#chatStop').isDisabled();
    check('取消后的历史延迟不会禁用新轮停止按钮', canStopNew);
    releaseDelayed(); await qa.waitForTimeout(100);
    if (!canStopNew) return summary();
    await qa.locator('#chatStop').click();
    await qa.waitForFunction(() => document.querySelector('#chatRunStatus').textContent.includes('已停止'));

    states[''].mode = 'delayed';
    const delayed = new Promise(resolve => delayedStarted = resolve);
    await qa.locator('#chatInput').fill('迟到的旧会话结果'); await qa.locator('#chatInput').press('Enter');
    await delayed;
    await qa.locator('[data-chat-session="grt-history-other"]').click();
    await qa.getByText('另一会话独有内容', {exact: true}).waitFor();
    releaseDelayed(); await qa.waitForTimeout(250);
    check('旧轮询不会覆盖新选择的会话', !(await qa.locator('#chatMessages').innerText()).includes('迟到的旧会话结果'));

    await qa.locator('#courseSelect').selectOption('/courses/ses/');
    await qa.locator('[data-chat-session="ses-history"]').click();
    await qa.getByText('SES 独立历史', {exact: true}).waitFor();
    check('课程切换不混用会话', !(await qa.locator('#chatMessages').innerText()).includes('GRT 历史问题'));
    states['/courses/ses'].status = 'unavailable'; states['/courses/ses'].failConnect = true;
    await qa.reload({waitUntil: 'domcontentloaded'});
    await qa.getByText('SES 独立历史', {exact: true}).waitFor();
    await qa.locator('#chatConnect').click();
    check('模型不可用时历史仍可读且发送禁用', await qa.locator('#chatSend').isDisabled() && states['/courses/ses'].connects === 1);
    check('所有变更请求都是 JSON', requests.filter(r => r.method === 'POST').every(r => r.contentType?.startsWith('application/json') && r.body));
    await qa.setViewportSize({width: 390, height: 844});
    check('手机布局无横向溢出', await qa.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await qa.locator('#all').click();
    check('原有证据浏览仍可进入', await qa.locator('#evidenceView').isVisible() && !await qa.locator('#chatView').isVisible());
    await qa.locator('#chatNav').click();
    check('返回学习对话保留当前历史', await qa.getByText('SES 独立历史', {exact: true}).isVisible());
    await qa.locator('#chatNew').click();
    await qa.getByText('从一个具体问题开始', {exact: true}).waitFor();
    check('新对话独立创建并保留旧会话入口', await qa.locator('[data-chat-session="ses-history"]').count() === 1 && states['/courses/ses'].sessions.length === 3);
  } catch (error) {
    check('浏览器流程未出现异常', false, {error: String(error.message).slice(0,800)});
  } finally {
    if (releaseDelayed) releaseDelayed();
    await qa.evaluate(values => { for (const [key, value] of Object.entries(values)) {
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } }, saved).catch(() => {});
    await qa.unroute(origin + '/**', routeHandler); await qa.close();
  }
  return summary();
}
