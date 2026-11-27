async (page) => {
  const results=[];
  const check=(name,passed)=>results.push({name,passed:!!passed});
  await page.setViewportSize({width:1365,height:900});
  await page.goto('http://127.0.0.1:8766/');
  await page.locator('#query').fill('Darcy 地下水年龄推导');
  await page.locator('#searchForm button').click();
  await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
  check('复习学生：能检索到跨页推导',await page.locator('#cards h3').filter({hasText:'Darcy 到地下水年龄'}).count()>0);
  const ref=page.locator('article > .refs > .ref[data-document="doc_b5c6524e854f61967a6977d3"][data-page="9"]').first();
  await ref.click();
  await page.locator('#pageContent .pageimg').waitFor();
  await page.locator('#pageContent .pageimg').first().evaluate(img=>img.decode());
  check('读图学生：第9张显示一张完整2000像素幻灯片',await page.locator('#pageContent .pageimg').count()===1&&await page.locator('#pageContent .pageimg').evaluate(img=>img.naturalWidth===2000));
  check('来源类型：PPTX不被误称为PDF',await page.locator('#pageContent .pageimg').getAttribute('alt').then(x=>x.includes('完整幻灯片')));
  const canJump=await page.locator('#pageJump').count()>0;
  check('长课件阅读：支持直接跳至第48张',canJump);
  if(canJump){await page.locator('#pageJump').fill('48');await page.locator('#pageJump').press('Enter');await page.waitForFunction(()=>document.querySelector('#pagePosition').textContent==='48 / 53');}
  check('做题学生：原页旁能看到核查注记',await page.locator('.visual-review').count()>0);
  const raw=page.getByText('查看原始抽取文字（可能含识别误差）',{exact:true});await raw.click();
  check('核查学生：原始抽取与导读分开',!(await page.locator('#pageContent pre').innerText()).includes('[原页核查导读'));
  await page.locator('#close').click();
  check('推导学生：可展开逐步公式与适用条件',await page.locator('.derivation').count()>0);
  await ref.click();
  await page.locator('#pageContent .pageimg').waitFor();
  await page.setViewportSize({width:390,height:844});await page.locator('#zoomIn').click();
  check('手机学生：完整幻灯片放大且外层不溢出',await page.locator('#zoomLevel').innerText()==='150%'&&await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('#close').click();await page.setViewportSize({width:1365,height:900});
  return {round:'groundwater-student',total:results.length,passed:results.filter(x=>x.passed).length,results};
}
