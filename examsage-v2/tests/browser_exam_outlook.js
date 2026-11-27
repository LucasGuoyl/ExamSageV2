async page => {
  const qa = await page.context().newPage(), dir = page.__examSageWebDir;
  const origin = 'http://127.0.0.1:19883';
  const messages = [], sessions = [], requests = [], runs = new Map();
  const document = {id:'paper',relative_path:'past.pdf',pages:3,kind:'exam'};
  const source = {document_id:'paper',page:2,filename:'past.pdf',source_id:'S1'};
  const gap = {document_id:'paper',page:3,year:2023,question_number:'2',filename:'past.pdf',
               source_id:'src_'+'a'.repeat(64)};
  try {
    await qa.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url()), path = url.pathname;
      const json = data => route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      if (url.origin !== origin) return route.abort();
      if (path === '/') return route.fulfill({path:dir+'/index.html',contentType:'text/html; charset=utf-8'});
      if (path.startsWith('/static/vendor/')) return route.fulfill({body:'',contentType:path.endsWith('.css')?'text/css':'text/javascript'});
      if (['/static/app.css','/static/chat.css','/static/app.js','/static/chat.js'].includes(path))
        return route.fulfill({path:dir+'/'+path.slice(8),contentType:path.endsWith('.css')?'text/css':'text/javascript; charset=utf-8'});
      if (path === '/api/status') return json({course:'数学演示',course_key:'math',topics:[],counts:{},documents:1,pages:3,exam_years:[]});
      if (path === '/api/documents') return json([document]);
      if (path === '/api/courses' || path.startsWith('/api/records')) return json([]);
      if (path === '/api/page/paper/3' && url.searchParams.get('source_id')===gap.source_id)
        return json({document,source_id:gap.source_id,bundle:{records:[{text:'Unlabelled original question.',details:{}}]},preview_url:null,media_urls:[]});
      if (path === '/api/page/paper/2') return json({document,bundle:{records:[{text:'Original proof prompt.',details:{}}]},preview_url:null,media_urls:[]});
      if (path === '/api/chat/status') return json({status:'ready',generation_verified:false});
      if (path === '/api/chat/sessions') {
        if (request.method() === 'GET') return json(sessions);
        sessions.push({id:'outlook',title:'考点'}); return json(sessions[0]);
      }
      if (path === '/api/chat/sessions/outlook/messages') {
        if (request.method() === 'GET') return json(messages);
        const question = request.postDataJSON().text, strict = question.includes('限考前可得资料');
        const target = Number(question.match(/】(\d{4})/)[1]);
        const report = {target_year:target,history_mode:strict?'strict':'paper_year',status:strict?'insufficient':'ranked',
          training_years:strict?[]:[2023],coverage:{exam_papers:strict?0:1,parent_questions:strict?0:2,tagged_questions:strict?0:1},
          unlabelled_examples:strict?[]:[gap],
          ranking:strict?[]:[{topic:'归纳法',year_count:1,question_count:1,years:[2023],sources:[source]}]};
        const answer = {exam_outlook:report,paragraphs:[{kind:strict?'insufficient':'source',text:strict?'缺少可得日期。':'可优先复习归纳法。',citations:[]}],
          limitations:strict?['往卷可得日期未知。']:[]};
        requests.push(question);
        const id = 'r' + requests.length;
        messages.push({role:'user',content:question,run_id:id},{role:'assistant',content:answer.paragraphs[0].text,answer});
        const result = {id,session_id:'outlook',status:'completed',question,answer};
        runs.set(id,result); return json(result);
      }
      if (path.startsWith('/api/chat/runs/')) return json(runs.get(path.split('/').pop()));
      return route.fulfill({status:404,body:''});
    });
    await qa.goto(origin+'/',{waitUntil:'domcontentloaded'});
    await qa.locator('.chat-outlook-options summary').click();
    const year = qa.locator('#outlookYear'), button = qa.locator('#chatOutlook');
    const expectedYear = await qa.evaluate(() => String(new Date().getFullYear()+1));
    const checks = {defaultYear:(await year.inputValue()) === expectedYear};
    await qa.locator('#chatInput').fill('保留草稿');
    await year.fill('2025');
    await button.click();
    const boxes = qa.locator('.chat-exam-outlook'), first = boxes.first();
    await first.waitFor({timeout:6000});
    checks.year = requests[0].startsWith('【历年试卷主题】2025 年，按卷面考年回顾。');
    const text = await first.innerText();
    checks.coverage = text.includes('1 份试卷 · 2 道大题，其中 1 道有主题标签');
    checks.topic = text.includes('归纳法') && text.includes('2023');
    checks.draft = await qa.locator('#chatInput').inputValue() === '保留草稿';
    await first.getByRole('button',{name:'past.pdf · 第 2 页'}).click();
    const overlay = qa.locator('dialog#overlay[open]');
    await overlay.getByText('Original proof prompt.',{exact:true}).waitFor({timeout:6000});
    checks.page = (await overlay.locator('#pageTitle').textContent()) === 'past.pdf · 2' &&
      (await overlay.locator('#pagePosition').textContent()) === '2 / 3';
    await qa.keyboard.press('Escape');
    await first.getByRole('button',{name:'2023 年第 2 题 · past.pdf 第 3 页'}).click();
    await overlay.getByText('Unlabelled original question.',{exact:true}).waitFor({timeout:6000});
    checks.unlabelled = (await overlay.locator('#pageTitle').textContent()) === 'past.pdf · 3';
    await qa.keyboard.press('Escape');
    await year.fill('2024');
    await qa.locator('#outlookMode').selectOption('strict');
    await button.click();
    await boxes.nth(1).waitFor({timeout:6000});
    checks.strict = requests[1].includes('2024 年，限考前可得资料') &&
      (await boxes.nth(1).innerText()).includes('可用往卷证据不足。') && await boxes.nth(1).locator('li').count() === 0;
    await qa.reload({waitUntil:'domcontentloaded'});
    await boxes.nth(1).waitFor({timeout:6000});
    checks.reopened = (await boxes.nth(0).innerText()).includes('2025') && (await boxes.nth(1).innerText()).includes('2024');
    return checks;
  } finally { await qa.close(); }
}
