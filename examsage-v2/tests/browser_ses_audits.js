async(page)=>{
 const results=[];const check=(name,passed)=>results.push({name,passed:!!passed});
 const base='http://127.0.0.1:8766/courses/ses';await page.goto(base+'/');await page.locator('#cards article').first().waitFor();
 const records=await(await page.request.get(base+'/api/records?kind=question')).json();
 const parts=records.filter(r=>r.details.audit);const formulas=parts.flatMap(r=>r.details.audit.formula_checks.map(f=>({id:r.id,latex:f.latex})));
 const errors=await page.evaluate(items=>items.flatMap(x=>{try{katex.renderToString(x.latex,{throwOnError:true,trust:false});return [];}catch(e){return [{...x,error:String(e)}];}}),formulas);
 check('全部小问公式可以排版',errors.length===0);
 for(const [year,number,part] of [[2024,'1','e.iii'],[2024,'1','e.iv'],[2024,'2','a.b']]){
  const q=parts.find(r=>r.details.exam_year===year&&r.details.number===number&&r.details.part===part);
  check(`${year} Q${number}(${part})保留来源冲突`,!!q&&q.details.audit.status==='source_conflict'&&q.details.audit.warnings.length>0);
  if(q){const query=year+' Q'+number+part.split('.').map(p=>'('+p+')').join('')+' 答案';await page.locator('#query').fill(query);await page.locator('#query').press('Enter');await page.waitForFunction(()=>document.querySelector('#count').textContent!=='查找中…');const card=page.locator('#cards article').first();
   check(`${year} Q${number}(${part})条件、数值和冲突可见`,await card.locator('.numeric-check').count()>0&&await card.locator('.subquestion-audit .source-warning').count()>0&&await card.locator('.subquestion-audit').isVisible());
  }
 }
 const mismatch=parts.flatMap(r=>r.details.audit.numerical_checks).filter(c=>c.comparison==='mismatch');
 check('数值不符不会消失或伪装成一致',mismatch.length>0&&parts.every(r=>r.details.audit.status!=='checked'||r.details.audit.numerical_checks.every(c=>c.comparison!=='mismatch')));
 check('数值表区分算术一致与物理适用性',(await page.locator('#cards').innerText()).includes('数值一致只表示'));
 return{round:'ses-condition-number-student',total:results.length,passed:results.filter(r=>r.passed).length,formulaCount:formulas.length,formulaErrors:errors,results};
}
