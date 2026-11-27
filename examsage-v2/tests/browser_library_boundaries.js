async(page)=>{
  const results=[];const assert=(v,m)=>{if(!v)throw Error(m)};
  const check=async(name,run)=>{try{await run();results.push({name,passed:true})}catch(e){results.push({name,passed:false,error:String(e).slice(0,300)})}};
  const ready=async()=>{await page.goto('http://127.0.0.1:8766/courses/sea_level/');await page.locator('#cards article').first().waitFor()};
  await ready();
  await check('独立链接刷新仍保持海平面课程',async()=>{await page.reload();await page.waitForFunction(()=>document.querySelector('#courseCode').textContent==='imperial:sea-level');assert(await page.locator('#cards article').count()===20,'Missing source catalog')});
  await check('模拟卷与正式卷分开呈现',async()=>{await page.locator('#exam').click();const tags=await page.locator('#cards .badge').allTextContents();assert(tags.includes('正式试卷')&&tags.includes('模拟试卷')&&tags.includes('考试指导与示例'),'Incorrect source roles')});
  await check('未建立逐题结构时不伪造年份题号匹配',async()=>{await page.locator('#query').fill('2024 Q1');await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent==='证据不足');assert((await page.locator('#resultLimitations').innerText()).includes('逐题结构尚未验证'),'No structural limitation');assert(await page.locator('#cards article').count()===0,'Unverified question substituted')});
  await page.locator('#sources').click();
  const docs=await (await page.request.get('http://127.0.0.1:8766/courses/sea_level/api/documents')).json();
  const doc=docs.find(x=>x.id==='doc_853032ec56a887ddfeea1636');
  await page.locator('#cards article').filter({has:page.locator('h3',{hasText:doc.relative_path.split('/').pop()})}).locator('button').click();
  await page.locator('#pageJump').fill('16');await page.locator('#pageJump').press('Enter');await page.waitForFunction(()=>document.querySelector('#pagePosition').textContent.startsWith('16 /'));
  await check('动画幻灯片明确提示静态预览边界',async()=>{assert((await page.locator('#pageContent').innerText()).includes('不能重现逐步播放'),'Missing animation limitation');await page.locator('.pageimg').evaluate(img=>img.decode());assert(await page.locator('.pageimg').evaluate(img=>img.naturalWidth===2000),'No native slide')});
  await check('只完成渲染的页面不会伪称完成代理核查',async()=>{assert(await page.locator('.visual-review').count()===0,'Unaudited page promoted')});
  await check('移动端课程选择与原页不撑宽外层',async()=>{await page.setViewportSize({width:320,height:740});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile overflow');await page.locator('#close').click();assert(await page.locator('#courseSelect').isVisible(),'Course selector unavailable')});
  await check('预览失效时展开原文并保留下载入口',async()=>{
    await page.route('**/api/preview/**',route=>route.fulfill({status:503,body:'Simulated failure'}));
    try{await page.locator('#cards article').first().locator('button').click();await page.getByText('此图无法预览，请下载原文件查看。',{exact:true}).waitFor();assert(await page.locator('.raw-section').evaluate(x=>x.open),'Raw text not opened');assert((await page.locator('.download').getAttribute('href')).startsWith('/courses/sea_level/api/source/'),'Download left course route');await page.locator('#close').click()}finally{await page.unrouteAll({behavior:'ignoreErrors'})}
  });
  await page.setViewportSize({width:1365,height:900});
  return {round:'course-boundaries',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
