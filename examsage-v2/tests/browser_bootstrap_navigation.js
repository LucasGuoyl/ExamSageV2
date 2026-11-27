async(page)=>{
 const results=[];
 for(const [course,button] of [['ses','exam'],['planetary_science','all']]){
  let release,seen;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r);
  const pattern='**/courses/'+course+'/api/status';
  const delay=async route=>{seen();await gate;await route.fallback();};
  await page.route(pattern,delay);
  try{
   await page.goto('http://127.0.0.1:8766/courses/'+course+'/',{waitUntil:'domcontentloaded'});
   await started;await page.locator('#'+button).click();release();await page.waitForLoadState('networkidle');
   const title=await page.locator('#sectionTitle').innerText();const count=await page.locator('#cards article').count();
   const questionCards=await page.locator('#cards article[data-kind="question"]').count();
   const passed=title===(button==='exam'?'试卷、练习与答案资料':'原始资料')&&count>0&&questionCards===0;
   results.push({course,button,passed,title,count,questionCards});
  }catch(e){results.push({course,button,passed:false,error:e.message.slice(0,500)});}
  finally{release();await page.unroute(pattern,delay);}
 }
 for(const scenario of ['newer-search','metadata-failure']){
  let release,seen;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r);
  const pattern='**/courses/ses/api/status';
  const delay=async route=>{seen();await gate;if(scenario==='metadata-failure')await route.fulfill({status:503,body:'QA simulated failure'});else await route.fallback();};
  await page.route(pattern,delay);
  try{
   await page.goto('http://127.0.0.1:8766/courses/ses/',{waitUntil:'domcontentloaded'});await started;await page.locator('#exam').click();
   if(scenario==='newer-search'){await page.locator('#query').fill('2024 Q1(c)(i) 答案');await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');}
   release();await page.waitForLoadState('networkidle');
   const passed=scenario==='newer-search'?(await page.locator('#sectionTitle').innerText()==='检索结果'&&await page.locator('#cards article').first().getAttribute('data-record-id')==='imperial:elec70076:exam:2024:q1:c.i'):(await page.locator('#count').innerText()==='读取失败'&&await page.locator('#cards').getAttribute('aria-busy')==='false');
   results.push({scenario,passed});
   if(scenario==='metadata-failure'){
    for(const button of ['exam','all','sources']){await page.locator('#'+button).click();results.push({scenario:'navigation-after-failure',button,passed:await page.locator('#count').innerText()==='读取失败'&&await page.locator('#cards').getAttribute('aria-busy')==='false'});}
   }
  }catch(e){results.push({scenario,passed:false,error:e.message.slice(0,500)});}
  finally{release();await page.unroute(pattern,delay);}
 }
 for(const course of ['grt','ses']){
  let release,seen;const gate=new Promise(r=>release=r),started=new Promise(r=>seen=r);
  const prefix=course==='grt'?'':'/courses/ses';const pattern='http://127.0.0.1:8766'+prefix+'/api/status';
  const delay=async route=>{seen();await gate;await route.fallback();};await page.route(pattern,delay);
  try{await page.goto('http://127.0.0.1:8766'+prefix+'/',{waitUntil:'domcontentloaded'});await started;const before=await page.locator('#formulas').isDisabled();release();await page.waitForLoadState('networkidle');results.push({scenario:'formula-button-waits-for-course-mode',course,passed:before&&(await page.locator('#formulas').isDisabled())===(course==='ses')});}
  finally{release();await page.unroute(pattern,delay);}
 }
 return {total:results.length,passed:results.filter(r=>r.passed).length,results};
}
