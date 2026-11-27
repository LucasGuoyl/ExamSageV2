async(page)=>{
 const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
 const search=async query=>{await page.locator('#query').fill(query);await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');};
 await page.goto('http://127.0.0.1:8766/courses/geodynamics/');await page.locator('#cards article').first().waitFor();
 await search('板块弯曲 跨页推导');
 const derivation=page.locator('.derivation').first();const available=await derivation.count()>0;
 check('地球动力学：检索到跨页推导',available);
 if(available){await derivation.locator('summary').click();check('推导公式可排版',await derivation.locator('.katex').count()>0&&await derivation.locator('.katex-error').count()===0);check('步骤来自两份课件',await derivation.locator('.ref').evaluateAll(nodes=>new Set(nodes.map(n=>n.dataset.document)).size)>=2);
   const refs=derivation.locator('.ref');const last=refs.last();const expected=await last.getAttribute('data-page');await last.click();await page.locator('#pageJump:not([disabled])').waitFor();check('推导步骤跳回正确页',await page.locator('#pageJump').inputValue()===expected);await page.locator('#close').click();
 }else for(const name of ['推导公式可排版','步骤来自两份课件','推导步骤跳回正确页'])check(name,false);
 await page.goto('http://127.0.0.1:8766/courses/ses/');await page.locator('#cards article').first().waitFor();
 check('SES：题目索引可进入',await page.locator('#pilots').count()>0&&await page.locator('#pilots').isVisible());
 await search('2024 Q2 官方答案');
 check('2024 Q2：成对返回题目与答案',await page.locator('article[data-kind="question"]').count()===1&&await page.locator('article[data-kind="answer"]').count()===1);
 check('来源参数冲突直接可见',await page.locator('.source-warning').count()>0);
 check('答案来源为2024配对文件',await page.locator('article[data-kind="answer"] .ref[data-document="doc_07b9a8721931c6221cfacf29"]').count()>0);
 await search('2019 Q1');check('旧年份保留文件名依据',await page.locator('#cards').innerText().then(t=>t.includes('文件标签')||t.includes('文件名')));
 const answerButton=page.locator('.answer-link').first();let navigates=false;
 if(await answerButton.count()){await answerButton.click();await page.waitForFunction(()=>document.querySelector('#sectionTitle').textContent.startsWith('题目与配对答案'));navigates=await page.locator('article[data-kind="answer"] .ref[data-document="doc_cc9f8c3ff8403a759f904051"]').count()>0;}
 check('从题目导航到同年同号答案',navigates);
 for(const q of ['2026 Q1 官方答案','2024 Q9','2024 Q2(z)']){await search(q);check(q+'：明确证据不足',await page.locator('#count').innerText()==='证据不足'&&await page.locator('#cards article').count()===0);}
 return {round:'course-pilots-student',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
