async(page)=>{
 const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
 const base='http://127.0.0.1:8766/courses/ses';
 const search=async q=>{await page.locator('#query').fill(q);await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');};
 const card=id=>page.locator('article[data-record-id="'+id+'"]');
 await page.setViewportSize({width:1365,height:1000});await page.goto(base+'/');await page.locator('#pilots').waitFor();await page.locator('#pilots').click();
 await page.waitForFunction(()=>document.querySelector('#sectionTitle').textContent.startsWith('已整理大题'));
 check('题目入口只显示28道大题，避免一次铺开所有小问',await page.locator('#cards article').count()===28);
 const qid='imperial:elec70076:exam:2024:q2';
 await card(qid).locator('.children-link').click();await page.waitForFunction(()=>document.querySelector('#sectionTitle').textContent.startsWith('小问'));
 check('2024 Q2分成Part A和Part B',await card(qid+':a').count()===1&&await card(qid+':b').count()===1);
 await card(qid+':a').locator('.children-link').click();await card(qid+':a.b').waitFor();
 check('Part A继续进入a/b小问',await page.locator('#cards article').count()===2);
 check('子级导航保留完整公共题干与上级条件',await page.locator('.shared-question-context h4').count()===2&&(await page.locator('.shared-question-context').innerText()).includes('230'));
 check('叶子显示条件和复算，不再提供空子级按钮',await card(qid+':a.b').locator('.subquestion-audit').count()===1&&await card(qid+':a.b').locator('.numeric-check').count()>0&&await card(qid+':a.b').locator('.children-link').count()===0);
 await card(qid+':a.b').locator('.answer-link').click();await page.waitForFunction(()=>document.querySelector('#sectionTitle').textContent.startsWith('题目与配对答案'));
 check('小问答案带完整三级题干和答案上下文',await card(qid+':a.b').count()===1&&await card(qid+':a').count()===1&&await card(qid).count()===1&&await card(qid.replace(':exam:',':answer:')+':a.b').count()===1);
 const r=card(qid+':a.b').locator(':scope > .refs > .ref').first();const expected=await r.getAttribute('data-page');await r.click();await page.locator('#pageJump:not([disabled])').waitFor();
 check('小问可打开准确原卷页',await page.locator('#pageJump').inputValue()===expected);await page.locator('#close').click();
 for(const query of ['2024 Q1(c)(i) 答案','2024 Q1 c.i answer','2024 Q1c(i) answer']){await search(query);check(query+'精确定位',await page.locator('#cards article').first().getAttribute('data-record-id')==='imperial:elec70076:exam:2024:q1:c.i');}
 await search('2019-20 Q1(a) 答案');check('文件学年精确映射2020，不串到2019',await page.locator('#cards article').first().getAttribute('data-record-id')==='imperial:elec70076:exam:2020:q1:a');
 for(const query of ['2099 Q1(a)答案','2024 Q1(z)答案','2024 Q1(c)(i)(x)答案','2024 Q1(a) and (b) answers']){await search(query);check(query+'明确证据不足',await page.locator('#cards article').count()===0&&await page.locator('#count').innerText()==='证据不足');}
 await page.goto(base+'/?q='+encodeURIComponent('2024 Q2(a)(b) 答案'));await card(qid+':a.b').waitFor();
 check('报告链接直接打开指定小问',await page.locator('#cards article').first().getAttribute('data-record-id')===qid+':a.b');
 check('当前公式无排版错误',await page.locator('.katex-error').count()===0);
 await card(qid+':a.b').scrollIntoViewIfNeeded();await page.screenshot({path:'./data/qa/recovery-ses-20261102/ses-student.png'});
 return{round:'ses-subquestion-student',total:results.length,passed:results.filter(r=>r.passed).length,results};
}
