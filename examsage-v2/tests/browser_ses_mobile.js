async(page)=>{
 const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
 for(const width of [390,320]){
  await page.setViewportSize({width,height:844});await page.goto('http://127.0.0.1:8766/courses/ses/?q='+encodeURIComponent('2024 Q2(a)(b) 答案'));
  await page.locator('.subquestion-audit').first().waitFor();
  check(width+'px页面不横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  check(width+'px公式与复算表可阅读',await page.locator('.numeric-check').count()>0&&await page.locator('.katex-error').count()===0);
  const ref=page.locator('#cards article').first().locator(':scope > .refs > .ref').first();const n=await ref.getAttribute('data-page');await ref.click();await page.locator('#pageJump:not([disabled])').waitFor();
  check(width+'px打开正确来源页',await page.locator('#pageJump').inputValue()===n);await page.locator('#close').click();
 }
 await page.locator('.subquestion-audit').first().scrollIntoViewIfNeeded();await page.screenshot({path:'./data/qa/recovery-ses-20261102/ses-mobile.png'});
 await page.setViewportSize({width:1365,height:1000});return{round:'ses-mobile',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
