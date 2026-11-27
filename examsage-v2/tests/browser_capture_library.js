async(page)=>{
  const out='./data/qa/groundwater-20261028/';
  await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:8766/');await page.locator('#cards article').first().waitFor();
  await page.locator('#query').fill('Darcy 地下水年龄推导');await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
  const ref=page.locator('.ref[data-document="doc_b5c6524e854f61967a6977d3"][data-page="9"]').first();
  await ref.click();await page.locator('.pageimg').evaluate(img=>img.decode());
  await page.screenshot({path:out+'native-slide.png'});
  await page.locator('#pageJump').fill('48');await page.locator('#pageJump').press('Enter');await page.waitForFunction(()=>document.querySelector('#pagePosition').textContent==='48 / 53');await page.locator('.pageimg').evaluate(img=>img.decode());
  await page.screenshot({path:out+'source-correction.png'});await page.locator('#close').click();
  await page.locator('#query').fill('碳-14 校正 混合比例 年龄');await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
  const chain=page.locator('#cards article').filter({has:page.locator('h3',{hasText:'碳-14 校正：从混合比例到年龄'})});
  await chain.locator('.derivation summary').click();await chain.scrollIntoViewIfNeeded();await chain.screenshot({path:out+'derivation.png'});
  await page.goto('http://127.0.0.1:8766/courses/ses/');await page.locator('#cards article').first().waitFor();await page.locator('#query').fill('官方答案');await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
  await page.screenshot({path:out+'course-ses.png'});
  await page.setViewportSize({width:390,height:844});await page.goto('http://127.0.0.1:8766/courses/sea_level/');await page.locator('#cards article').first().waitFor();await page.screenshot({path:out+'mobile-course.png'});
  await page.setViewportSize({width:1440,height:1000});
  return {screenshots:['native-slide.png','source-correction.png','derivation.png','course-ses.png','mobile-course.png']};
}
