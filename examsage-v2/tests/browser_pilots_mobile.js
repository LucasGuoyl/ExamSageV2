async(page)=>{
 const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});const out='./data/qa/visual-test-20261028/lowtext/';
 const search=async q=>{await page.locator('#query').fill(q);await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');};
 await page.setViewportSize({width:1365,height:1000});await page.goto('http://127.0.0.1:8766/courses/geodynamics/');await page.locator('#pilots').waitFor();await page.locator('#pilots').click();await page.locator('.derivation summary').click();
 check('12步推导均可排版',await page.locator('.derivation section').count()===12&&await page.locator('.derivation .katex-error').count()===0);
 await page.locator('.derivation').scrollIntoViewIfNeeded();await page.screenshot({path:out+'geodynamics.png'});
 for(const width of [390,320]){await page.setViewportSize({width,height:844});check('推导 '+width+'px 页面不横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 await page.locator('.derivation section').first().scrollIntoViewIfNeeded();await page.screenshot({path:out+'geodynamics-mobile.png'});
 const ref=page.locator('.derivation .ref').last();await ref.click();await page.locator('#pageContent img').first().evaluate(img=>img.decode());
 check('移动端推导来源可打开',await page.locator('#pagePosition').innerText()==='17 / 18');await page.locator('#close').click();
 await page.setViewportSize({width:1365,height:1000});await page.goto('http://127.0.0.1:8766/courses/ses/');await page.locator('#pilots').waitFor();await search('2024 Q2 官方答案');await page.locator('#cards').scrollIntoViewIfNeeded();await page.screenshot({path:out+'ses-pair.png'});
 check('SES来源冲突两侧均可见',await page.locator('article[data-kind="question"] .source-warning').count()>0&&await page.locator('article[data-kind="answer"] .source-warning').count()>0);
 for(const width of [390,320]){await page.setViewportSize({width,height:844});check('题答 '+width+'px 页面不横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 await page.locator('.source-warning').first().scrollIntoViewIfNeeded();await page.screenshot({path:out+'ses-mobile.png'});
 for(const query of ['2019-20 Q4 解答','2024 Q1z 官方答案','2024 Q1 and Q2 answers']){
  await search(query);check(query,query.startsWith('2019')?(await page.locator('article[data-kind="question"] h3').innerText()).includes('2020'):await page.locator('#count').innerText()==='证据不足');
 }
 await page.setViewportSize({width:1365,height:1000});await page.goto('http://127.0.0.1:8766/courses/sea_level/');await page.locator('#cards article').first().waitFor();await search('赤道虹吸');await page.locator('.ref[data-page="19"]:visible').first().click();await page.locator('.page-supplement').scrollIntoViewIfNeeded();await page.screenshot({path:out+'sea-level-supplement.png'});
 check('图像页保留OCR和原文独立入口',await page.locator('.ocr-section summary').count()===1&&await page.locator('.raw-section summary').count()===1);
 await page.locator('#close').click();return {round:'mobile-pilots-and-visuals',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
