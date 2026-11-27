async page => {
  // Local replay. The host supplies the project web/ directory; every request is intercepted.
  const qa = await page.context().newPage();
  const origin = 'http://127.0.0.1:19877';
  const dir = page.__examSageWebDir;
  if (!dir) { await qa.close(); throw new Error('Supply page.__examSageWebDir before running'); }
  const sessions = [], opened = [];
  let messages = [], question = '';
  const source = {document_id: 'notes', page: 2, filename: 'notes.txt', quote: 'Sum 1..n = n(n+1)/2.'};
  const unsafe = '<img src=x onerror=alert(1)>';
  const graph = {schema_version: 'knowledge-map-v1', coverage: {cited_pages: 1, visible_pages: 3}, nodes: [
    {id: 'a', parent: '', kind: 'topic', title: '求和', summary: unsafe, support: [source], limitations: []},
    {id: 'b', parent: 'a', kind: 'method', title: '闭式', summary: 'n 是正整数', support: [source], limitations: ['待核查']}
  ]};
  const answer = {paragraphs: [{kind: 'source', text: '有限求和', citations: ['E1']}],
    evidence: [{id: 'E1', kind: 'block', refs: [source]}], knowledge_map: graph};
  const run = () => ({id: 'map-run', session_id: 'map-session', status: 'completed', question, answer});
  try {
    await qa.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), path = url.pathname;
      const json = value => route.fulfill({contentType: 'application/json', body: JSON.stringify(value)});
      if (url.origin !== origin) return route.abort();
      if (path === '/') return route.fulfill({path: dir + '/index.html', contentType: 'text/html; charset=utf-8'});
      if (path.startsWith('/static/vendor/')) return route.fulfill({body: '', contentType: path.endsWith('.css') ? 'text/css' : 'text/javascript'});
      if (['/static/app.js','/static/chat.js','/static/app.css','/static/chat.css'].includes(path)) {
        return route.fulfill({path: dir + '/' + path.slice(8), contentType: path.endsWith('.css') ? 'text/css' : 'text/javascript; charset=utf-8'});
      }
      if (path === '/api/status') return json({course: '演示', course_key: 'm', topics: [], counts: {}, documents: 1, pages: 3, exam_years: []});
      if (path === '/api/documents') return json([{id: 'notes', relative_path: 'notes.txt', pages: 3, kind: 'lecture'}]);
      if (path === '/api/courses' || path.startsWith('/api/records')) return json([]);
      if (path === '/api/page/notes/2') {
        opened.push(path);
        return json({document: {id: 'notes', relative_path: 'notes.txt', pages: 3},
          bundle: {records: [{text: source.quote, details: {}}]}, preview_url: null, media_urls: []});
      }
      if (path === '/api/chat/status') return json({status: 'ready', generation_verified: false});
      if (path === '/api/chat/sessions') {
        if (req.method() === 'POST') { sessions.push({id: 'map-session', title: '知识结构'}); return json(sessions[0]); }
        return json(sessions);
      }
      if (path === '/api/chat/sessions/map-session/messages') {
        if (req.method() === 'POST') {
          question = req.postDataJSON().text;
          messages = [{role: 'user', content: question, run_id: 'map-run'}, {role: 'assistant', content: '有限求和', answer}];
          return json(run());
        }
        return json(messages);
      }
      if (path === '/api/chat/runs/map-run') return json(run());
      return route.fulfill({status: 404, body: ''});
    });
    await qa.goto(origin + '/', {waitUntil: 'domcontentloaded'});
    await qa.locator('#chatInput').fill('未发送的草稿');
    await qa.locator('#chatMap').click();
    const section = qa.locator('.chat-knowledge-map');
    await section.waitFor({timeout: 7000});
    const text = await section.innerText();
    const checks = {prompt: question.startsWith('【课程知识结构】'),
      preservedDraft: await qa.locator('#chatInput').inputValue() === '未发送的草稿',
      coverage: text.includes('1 / 3'), nestedNodes: await section.locator('li > ul > li').count() === 1,
      safeSummary: text.includes(unsafe) && await section.locator('img').count() === 0};
    await Promise.all([qa.waitForResponse(origin + '/api/page/notes/2'),
      section.locator('li > ul > li button.ref').click()]);
    const dialog = qa.locator('dialog#overlay[open]');
    await dialog.getByText(source.quote, {exact: true}).waitFor();
    checks.source = opened.includes('/api/page/notes/2') && await dialog.isVisible()
      && await dialog.locator('#pageTitle').textContent() === 'notes.txt · 2'
      && await dialog.locator('#pagePosition').textContent() === '2 / 3'
      && await dialog.locator('#pageContent pre.pageText').innerText() === source.quote;
    await qa.reload({waitUntil: 'domcontentloaded'});
    await section.waitFor({timeout: 7000});
    checks.restored = await section.isVisible();
    const [file] = await Promise.all([qa.waitForEvent('download', {timeout: 7000}),
      section.getByRole('button', {name: '下载知识结构 JSON'}).click()]);
    const stream = await file.createReadStream(), parts = [];
    for await (const part of stream) parts.push(part);
    const exported = JSON.parse(Buffer.concat(parts).toString('utf8'));
    checks.download = file.suggestedFilename() === 'course-knowledge-map.json' && JSON.stringify(exported) === JSON.stringify(graph);
    return checks;
  } finally { await qa.close(); }
}
