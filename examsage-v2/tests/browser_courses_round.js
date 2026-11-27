async(page)=>{
  const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
  await page.goto('http://127.0.0.1:8766/');await page.locator('#courseSelect option').first().waitFor({state:'attached'});
  check('课程选择：列出5门真实课程',await page.locator('#courseSelect option').count()===5);
  const courses=[['geodynamics','Geodynamics','板块弯曲',17],['planetary_science','Planetary Science','火星',17],['sea_level','Sea Level','海平面',20],['ses','Sustainable Electrical Systems','潮流',25]];
  for(const [slug,name,query,count] of courses){
    await page.locator('#courseSelect').selectOption('/courses/'+slug+'/');await page.waitForURL('**/courses/'+slug+'/');
    await page.waitForFunction(name=>document.querySelector('#courseName').textContent.includes(name),name);
    check(name+'：课程身份和资料数正确',(await page.locator('#stats').innerText()).startsWith(String(count))&&!(await page.locator('#courseCode').innerText()).includes('70151'));
    await page.locator('#query').fill(query);await page.locator('#searchForm button').click();await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
    const refs=page.locator('#cards .ref:visible');check(name+'：中文术语能找到课程证据',await refs.count()>0);
    if(await refs.count()){
      await refs.first().click();await page.locator('#pageContent .pageimg').first().waitFor();await page.locator('#pageContent .pageimg').first().evaluate(img=>img.decode());
      check(name+'：来源原页可读且请求留在本课程',(await page.locator('#pageContent .pageimg').first().getAttribute('src')).startsWith('/courses/'+slug+'/api/'));
      await page.locator('#close').click();
    }
    const denied=await page.request.get('http://127.0.0.1:8766/courses/'+slug+'/api/page/doc_b5c6524e854f61967a6977d3/9');
    check(name+'：不能跨课程读取GRT来源',denied.status()===404);
    if(slug==='geodynamics'){
      await page.locator('#exam').click();check('地球动力学：练习不标为正式真题',!(await page.locator('#cards').innerText()).includes('正式试卷')&&(await page.locator('#cards').innerText()).includes('练习题'));
    }
    if(slug==='ses'){
      await page.locator('#query').fill('官方答案');await page.locator('#searchForm button').click();await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');
      check('SES：已有答案文件不再被声明不存在',await page.locator('#cards .ref').count()>0&&!(await page.locator('#resultLimitations').innerText()).includes('未提供官方'));
    }
  }
  await page.locator('#courseSelect').selectOption('/');await page.waitForURL('http://127.0.0.1:8766/');
  await page.waitForFunction(()=>document.querySelector('#courseCode').textContent.includes('70151'));
  await page.waitForFunction(()=>document.querySelector('#cards').getAttribute('aria-busy')==='false'&&document.querySelectorAll('#cards article').length>0);
  check('切回GRT：保留已核查的课程知识与公式',await page.locator('#formulas').isEnabled()&&await page.locator('#cards article').count()>0);
  return {round:'multi-course-student',total:results.length,passed:results.filter(r=>r.passed).length,results};
}

