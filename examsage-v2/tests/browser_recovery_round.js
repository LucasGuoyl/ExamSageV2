async(page)=>{
 const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
 for(const [slug,id,n] of [['geodynamics','doc_1cf93155c2c9b6885491c8fd',3],['planetary_science','doc_893c18cb6042a86e6fa8ae8e',66],['sea_level','doc_75568ff811e86673d6aee091',10],['ses','doc_f12ea8990d648711e1b6dd3d',16]]){
  const base='http://127.0.0.1:8766/courses/'+slug;await page.goto(base+'/');await page.locator('#cards article').first().waitFor();await page.locator('#sources').click();
  const docs=await (await page.request.get(base+'/api/documents')).json();const name=docs.find(d=>d.id===id).relative_path.split('/').pop();
  await page.locator('#cards article').filter({has:page.locator('h3',{hasText:name})}).locator('button').click();await page.locator('#pageJump:not([disabled])').waitFor();await page.locator('#pageJump').fill(String(n));await page.locator('#pageJump').press('Enter');await page.waitForFunction(n=>document.querySelector('#pagePosition').textContent.startsWith(n+' /'),n);
  check(slug+'：逐项复核内容可读',await page.locator('.page-recovery').count()===1&&await page.locator('.page-recovery').innerText().then(t=>t.length>100).catch(()=>false));
  const data=await (await page.request.get(base+'/api/page/'+id+'/'+n)).json();const s=data.bundle.records[0].details.supplement;
  check(slug+'：复核与原OCR状态分开',!!s.audit.recovery&&!s.ocr_indexed&&s.ocr.mean_confidence<70&&await page.locator('.ocr-section').count()===1);
  await page.locator('#close').click();
 }return {round:'recovery-student',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
