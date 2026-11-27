async(page)=>{
  const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
  const sourcePages=[['geodynamics','doc_1cf93155c2c9b6885491c8fd',3],['planetary_science',null,null],['sea_level','doc_f864b87db30611fbeb1b8600',19],['ses',null,null]];
  for(const [slug,id,number] of sourcePages){
    await page.goto('http://127.0.0.1:8766/courses/'+slug+'/');await page.locator('#cards article').first().waitFor();
    if(!id)continue;
    const docs=await (await page.request.get('http://127.0.0.1:8766/courses/'+slug+'/api/documents')).json();const doc=docs.find(d=>d.id===id);
    await page.locator('#sources').click();await page.locator('#cards article').filter({has:page.locator('h3',{hasText:doc.relative_path.split('/').pop()})}).locator('button').click();
    await page.locator('#pageJump').fill(String(number));await page.locator('#pageJump').press('Enter');await page.waitForFunction(n=>document.querySelector('#pagePosition').textContent.startsWith(n+' /'),number);
    check(slug+'：低文本原页有可读补充说明',await page.locator('.page-supplement').count()===1);
    check(slug+'：OCR结果与原始抽取分别展开',await page.locator('.ocr-section').count()===1&&await page.locator('.raw-section').count()===1);
    await page.locator('#close').click();
  }
  await page.goto('http://127.0.0.1:8766/courses/sea_level/');await page.locator('#cards article').first().waitFor();
  for(const [query,n] of [['赤道虹吸',19],['锶同位素',23]]){
    await page.locator('#query').fill(query);await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
    const doc=query==='赤道虹吸'?'doc_f864b87db30611fbeb1b8600':'doc_d2287e7cbd1f0be8fef1728d';
    check(query+'：能查到原先只有图片的对应页',await page.locator('.ref[data-document="'+doc+'"][data-page="'+n+'"]').count()>0);
  }
  return {round:'low-text-student',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
