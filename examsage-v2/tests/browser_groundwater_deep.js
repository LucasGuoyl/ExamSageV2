async (page) => {
  const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
  const search=async q=>{await page.locator('#query').fill(q);await page.locator('#searchForm button').click();await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');};
  const jump=async n=>{await page.locator('#pageJump').fill(String(n));await page.locator('#pageJump').press('Enter');await page.waitForFunction(n=>document.querySelector('#pagePosition').textContent.startsWith(n+' /'),n);};
  await page.goto('http://127.0.0.1:8766/');await search('碳14校正推导');
  const card=page.locator('#cards article').filter({has:page.locator('h3').filter({hasText:'碳-14 校正'})}).first();
  await card.locator('.derivation>summary').click();
  check('计算学生：校正推导中的公式全部排版',await card.locator('.derivation .katex').count()===4&&await card.locator('.katex-error').count()===0);
  await card.locator(':scope > .refs > .ref[data-page="48"]').click();
  await page.waitForFunction(()=>document.querySelector('#pagePosition').textContent==='48 / 53');
  check('计算学生：明确指出 .102 错误和 -141 年的复算条件',(await page.locator('.audit-warnings').innerText()).includes('算术不成立')&&(await page.locator('.audit-warnings').innerText()).includes('1.01720'));
  await jump(49);await page.locator('.visual-review>summary').click();
  check('表格学生：保留15口井及小于检测限符号',await page.locator('.visual-review tbody tr').count()===15&&(await page.locator('.visual-review table').innerText()).includes('<0.62'));
  await jump(51);await page.locator('.visual-review>summary').click();
  check('推导学生：水头表保留km和m单位',await page.locator('.visual-review tbody tr').count()===10&&(await page.locator('.visual-review table').innerText()).includes('km'));
  await jump(53);check('末页学生：不会翻到第54张',await page.locator('#next').isDisabled());
  await page.locator('#pageJump').fill('54');await page.locator('#pageJump').press('Enter');
  check('跳页学生：越界输入明确提示且保留原页',(await page.locator('#pageJumpError').innerText()).includes('1—53')&&await page.locator('#pagePosition').innerText()==='53 / 53');
  await page.locator('#close').click();await search('36Cl 推导');
  const chlorine=page.locator('#cards article').filter({has:page.locator('h3').filter({hasText:'36Cl 地下水定年'})}).first();
  await chlorine.locator('.derivation>summary').click();
  check('案例学生：推导包含六口污染井和背景项',(await chlorine.innerText()).includes('4964、305、1184、7311、5092、15239')&&await chlorine.locator('.derivation .katex').count()===3);
  await chlorine.locator(':scope > .refs > .ref[data-page="17"]').click();await page.waitForFunction(()=>document.querySelector('#pagePosition').textContent==='17 / 19');await page.locator('.visual-review>summary').click();
  check('案例学生：26行测量保留空白与相对误差',await page.locator('.visual-review tbody tr').count()===26&&(await page.locator('.visual-review table').innerText()).includes('—')&&(await page.locator('.visual-review table').innerText()).includes('相对 ± %'));
  await page.setViewportSize({width:320,height:740});await page.locator('.visual-review').scrollIntoViewIfNeeded();
  check('小屏学生：宽表格在自身区域滚动',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth&&document.querySelector('.table-wrap').scrollWidth>document.querySelector('.table-wrap').clientWidth));
  await page.locator('#close').click();await page.setViewportSize({width:1365,height:900});
  return {round:'groundwater-calculation-and-reading',total:results.length,passed:results.filter(x=>x.passed).length,results};
}
