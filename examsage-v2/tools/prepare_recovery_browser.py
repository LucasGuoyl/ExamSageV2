from pathlib import Path
root=Path(__file__).resolve().parents[1]
rows=(root/'data/qa/recovery-ses-20261102/browser-recovery-input.json').read_text(encoding='utf-8')
script='''async(page)=>{
const rows=ROWS;
await page.goto('http://127.0.0.1:8766/courses/ses/');await page.locator('#cards article').first().waitFor();
const formulas=[];
for(const r of rows){const d=await(await page.request.get('http://127.0.0.1:8766/courses/'+r.course+'/api/page/'+r.id+'/'+r.page)).json();
for(const b of d.bundle.records[0].details.supplement.audit.recovery.blocks)if(b.latex)formulas.push({...r,latex:b.latex});}
const errors=await page.evaluate(formulas=>formulas.flatMap(f=>{try{katex.renderToString(f.latex,{throwOnError:true,trust:false});return [];}catch(e){return [{...f,error:e.message}];}}),formulas);
return{pages:rows.length,formulas:formulas.length,errors};
}'''.replace('ROWS',rows)
(root/'tests/browser_recovery_math.js').write_text(script,encoding='utf-8')
