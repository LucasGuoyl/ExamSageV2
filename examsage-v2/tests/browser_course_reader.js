async (page) => {
  const checks = [], errors = [];
  const listener = error => errors.push(String(error));
  page.on('pageerror', listener);
  const check = (name, passed) => checks.push({name, passed:!!passed});
  const reviewButton = page.getByRole('button',{name:'查看导入审核'});
  check('source import review is accessible', await reviewButton.count()===1);
  for (const cid of ['physics','mathematics','literature','history']) {
    await page.locator('#course').selectOption('demo-'+cid);
    check(cid+': course changes', (await page.locator('#profile').textContent()).includes('演示资料'));
    check(cid+': focus evidence rendered', await page.locator('#results article').count()>0);
    const focusTitle = await page.locator('#results h3').first().textContent();
    await reviewButton.click();
    check(cid+': import review opens', await page.locator('#results h2').textContent()==='导入审核');
    check(cid+': physical pages listed', await page.locator('#results article').count()===(cid==='history'?3:2));
    await page.locator('#items button').filter({hasText:focusTitle}).click();
    await page.locator('#results .refs button').first().click();
    check(cid+': original page opens', await page.locator('#source').isVisible() &&
      !(await page.locator('#source-text').textContent()).includes('没有可显示'));
    check(cid+': source hash visible', /SHA256：[0-9a-f]{64}/.test(await page.locator('#source-meta').textContent()));
    await page.locator('#close-source').click();
    check(cid+': page closes', !(await page.locator('#source').isVisible()));
    await page.locator('#items button').filter({hasText:'题目 / 小问 a'}).click();
    check(cid+': shared parent retained', await page.locator('#results article').count()>=2);
    await page.getByRole('button',{name:'核对本小问的答案'}).click();
    check(cid+': answer availability explicit', (await page.locator('#results h2').textContent())===
      (['physics','mathematics'].includes(cid)?'题目、共享条件与参考答案':'配对答案不足'));
  }
  await page.locator('#course').selectOption('demo-literature');
  await page.getByRole('button',{name:'contradicts · 窗：离开归属的读法'}).click();
  check('literature: alternative interpretation navigable',(await page.locator('#results h3').first().textContent()).includes('离开归属'));
  await page.locator('#filter').fill('unfindable-123');
  check('filter: empty state visible',(await page.locator('#items').textContent()).includes('没有匹配'));
  await page.locator('#filter').fill('窗');
  check('single-character title filter',await page.locator('#items button').count()>0);
  await page.evaluate(()=>{
    const target=current.items.find(i=>i.id==='focus');
    target.bundle.records[0].text='<img src=x onerror="window.readerInjected=true">';
    choose(target);
  });
  check('source HTML stays literal',await page.locator('#results img').count()===0 &&
      !(await page.evaluate(()=>Boolean(window.readerInjected))));
  await page.setViewportSize({width:390,height:844});
  check('mobile has no horizontal overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  check('mobile course selector usable',await page.locator('#course').isVisible());
  await page.setViewportSize({width:1360,height:950});
  await page.locator('#course').selectOption('demo-mathematics');
  check('no page errors',errors.length===0);
  page.off('pageerror',listener);
  return {mode:'actual-browser-static-reader-no-model',total:checks.length,passed:checks.filter(c=>c.passed).length,checks,errors};
}
