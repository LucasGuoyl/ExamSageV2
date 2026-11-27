async (page) => {
  const results=[];
  const check=async(name,run)=>{try{await run();results.push({name,passed:true});}catch(e){results.push({name,passed:false,error:e.message.slice(0,350)});}};
  const assert=(value,message)=>{if(!value)throw new Error(message);};
  const search=async(q)=>{await page.locator('#query').fill(q);await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');};
  await page.setViewportSize({width:1365,height:900});
  await page.goto('http://127.0.0.1:8766/');
  await page.locator('#cards article').first().waitFor();
  await check('缺失年份不混入其他年份试题',async()=>{await search('2023年Q1地下水年龄');assert(await page.locator('#cards article').count()===0,'Unexpected evidence returned');assert((await page.locator('#resultLimitations').innerText()).includes('年份'),'Missing specific year explanation');});
  await check('公式呈现为排版数学',async()=>{await page.locator('#formulas').click();await page.locator('#cards article').first().waitFor();await page.locator('#cards article').first().locator('summary').first().click();assert(await page.locator('#cards .katex').count()>0,'No rendered math');});
  await check('2024 公共题干保留结构化表格',async()=>{await search('2024 Q1 地下水年龄');await page.locator('#cards table').first().waitFor({timeout:1500});assert(await page.locator('#cards table').first().locator('tbody tr').count()===3,'Expected 3 well rows');assert(!(await page.locator('#cards article').first().innerText()).includes('𝐾𝐾'),'Duplicated source glyph still shown as primary text');});
  await check('原文弹层接管焦点并限制 Tab',async()=>{await page.locator('#cards .ref').first().click();await page.waitForFunction(()=>document.querySelector('#pageContent img')?.complete);assert(await page.evaluate(()=>document.querySelector('#overlay').contains(document.activeElement)),'Focus stayed behind modal');await page.locator('#close').focus();await page.keyboard.press('Shift+Tab');assert(await page.evaluate(()=>document.querySelector('#overlay').contains(document.activeElement)),'Keyboard focus escaped modal');});
  await check('Esc 关闭后焦点回到来源按钮',async()=>{await page.keyboard.press('Escape');assert(await page.evaluate(()=>!document.querySelector('#overlay').open),'Dialog still open');assert(await page.evaluate(()=>document.activeElement.classList.contains('ref')),'Trigger focus not restored');});
  await check('手机原卷可放大并翻页',async()=>{await page.setViewportSize({width:390,height:844});await page.locator('#cards .ref').first().click();await page.locator('#pageContent img').first().waitFor();await page.locator('#pageContent img').first().evaluate(img=>img.decode());const before=await page.locator('#pageContent img').first().evaluate(e=>e.getBoundingClientRect().width);await page.getByRole('button',{name:'放大',exact:true}).click({timeout:1500});const after=await page.locator('#pageContent img').first().evaluate(e=>e.getBoundingClientRect().width);assert(after>before*1.2,'Zoom did not enlarge source');await page.getByRole('button',{name:'下一页',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#pageTitle').textContent.endsWith('· 3'));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page overflow after zoom');});
  await page.keyboard.press('Escape');
  await page.setViewportSize({width:1365,height:900});
  return {round:'repair-regression',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
