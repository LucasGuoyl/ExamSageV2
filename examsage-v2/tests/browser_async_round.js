async (page) => {
  const results=[];const assert=(v,m)=>{if(!v)throw new Error(m);};
  const check=async(name,run)=>{try{await run();results.push({name,passed:true});}catch(e){results.push({name,passed:false,error:e.message.slice(0,300)});}finally{await page.unrouteAll({behavior:'ignoreErrors'});}};
  const ready=async()=>{await page.goto('http://127.0.0.1:8766/');await page.locator('#cards article').first().waitFor();};
  await check('首次加载较慢时保留学生已经提交的搜索',async()=>{
    let release;const gate=new Promise(r=>release=r);
    await page.route('**/api/status',async route=>{const response=await route.fetch();await gate;await route.fulfill({response});});
    await page.goto('http://127.0.0.1:8766/',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(()=>!!document.getElementById('searchForm').onsubmit);
    await page.locator('#query').fill('2023 Q1');await page.locator('#query').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#count').textContent==='证据不足');
    release();await page.waitForLoadState('networkidle');
    assert(await page.locator('#sectionTitle').innerText()==='检索结果','Bootstrap overwrote user search');
    assert(await page.locator('#count').innerText()==='证据不足','Bootstrap cleared result state');
  });
  await check('慢搜索返回时不能覆盖刚选择的原始资料',async()=>{
    await ready();let release,seen;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r);
    await page.route('**/api/search?**',async route=>{const response=await route.fetch();seen();await gate;await route.fulfill({response});});
    await page.locator('#query').fill('Darcy');await page.locator('#query').press('Enter');await started;
    await page.locator('#sources').click();release();await page.waitForLoadState('networkidle');
    assert(await page.locator('#sectionTitle').innerText()==='原始资料','Stale search overwrote source view');
    assert(await page.locator('#cards article').count()===19,'Source catalog replaced');
  });
  await check('关掉慢原文请求后不能重新弹出或改写下一个原页',async()=>{
    await ready();await page.locator('#query').fill('2024 Q1');await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#sectionTitle').textContent==='检索结果');
    let release,seen;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r);let first=true;
    await page.route('**/api/page/**',async route=>{if(!first){await route.continue();return;}first=false;const response=await route.fetch();seen();await gate;await route.fulfill({response});});
    await page.locator('#cards .ref').first().click();await started;await page.keyboard.press('Escape');
    await page.locator('#cards .ref').nth(1).click();await page.waitForFunction(()=>document.querySelector('#pageTitle').textContent.includes('GeolRctvTransport.pdf'));
    const title=await page.locator('#pageTitle').innerText();release();await page.waitForLoadState('networkidle');
    assert(await page.locator('#pageTitle').innerText()===title,'Old page response replaced selected source');await page.keyboard.press('Escape');
  });
  await check('全部真题正文不再展示已核对的乱码符号',async()=>{
    await ready();await page.locator('#exam').click();await page.waitForFunction(()=>document.querySelector('#count').textContent==='26 条结果');
    const text=await page.locator('#cards').innerText();assert(!/[\u0B00-\u0D7F]/.test(text),'Garbled script remains in primary text');assert(!/𝐾𝐾|𝜙𝜙|𝜇𝜇|𝑄𝑄|𝑐𝑐/.test(text),'Duplicated math glyph remains');assert(await page.locator('#cards .katex-error').count()===0,'Invalid mathematical transcription');
  });
  await check('离线使用不需要第三方公式请求',async()=>{
    const external=[];const observe=request=>{if(!request.url().startsWith('http://127.0.0.1:8766/'))external.push(request.url());};page.on('request',observe);
    try{await ready();await page.locator('#formulas').click();await page.waitForFunction(()=>document.querySelector('#count').textContent==='6 条结果');assert(external.length===0,'External network request: '+external.join(','));assert(await page.locator('#cards .katex').count()===6,'Offline formula renderer unavailable');}finally{page.off('request',observe);}
  });
  await check('跨年份比较明确提示缺少的 2023 年',async()=>{
    await ready();await page.locator('#query').fill('比较 2023 Q1 和 2024 Q1');await page.locator('#query').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
    assert(await page.locator('#cards article').count()===0,'Unrequested years substituted');
    assert((await page.locator('#resultLimitations').innerText()).includes('2023'),'Missing year not named');
  });
  return {round:'async-and-full-exam',total:results.length,passed:results.filter(x=>x.passed).length,results};
}
