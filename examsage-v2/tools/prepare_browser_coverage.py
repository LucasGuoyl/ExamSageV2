from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
rows=json.loads((ROOT/'data/qa/low-text-20261028/inventory.json').read_text(encoding='utf-8'))
items=[{k:r[k] for k in ['course','document_id','number','native_text','render_sha256']} for r in rows]
script=r'''async(page)=>{
 await page.goto('http://127.0.0.1:8766/');
 const results=await page.evaluate(async(items)=>{
   const results=[];
   for(let offset=0;offset<items.length;offset+=6){
    const batch=await Promise.all(items.slice(offset,offset+6).map(async item=>{
     const result={name:item.course+' '+item.document_id+' p'+item.number,passed:false};
     try{const base='/courses/'+item.course;const response=await fetch(base+'/api/page/'+item.document_id+'/'+item.number);if(!response.ok)throw Error('page HTTP '+response.status);
      const data=await response.json(),record=data.bundle.records[0],s=record.details.supplement;
      if(record.details.raw_text!==item.native_text)throw Error('Native text changed');
      if(!s||!s.audit.summary||s.render_sha256!==item.render_sha256)throw Error('Supplement missing');
      const index=record.details.assets.indexOf(s.image_asset);const image=await fetch(base+'/api/media/'+item.document_id+'/'+item.number+'/'+index);if(!image.ok)throw Error('Supplement image unavailable');
      const bytes=await image.arrayBuffer();const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');if(hash!==item.render_sha256)throw Error('Image hash mismatch');
      if(!data.preview_url)throw Error('No original preview');const preview=await fetch(base+data.preview_url);if(!preview.ok)throw Error('Original preview HTTP '+preview.status);
      const bitmap=await createImageBitmap(await preview.blob());if(bitmap.width<100||bitmap.height<100)throw Error('Invalid image dimensions');bitmap.close();result.passed=true;
     }catch(e){result.error=String(e);}return result;
    }));results.push(...batch);
   }return results;
 },ITEMS);
 const base='http://127.0.0.1:8766/courses/ses';const questions=await (await page.request.get(base+'/api/records?kind=question&roots=true')).json();
 for(const q of questions){
  const b=await (await page.request.get(base+'/api/answer/'+encodeURIComponent(q.id))).json();const answers=b.records.filter(r=>r.kind==='answer');const a=answers[0];
  results.push({name:'SES pair '+q.details.exam_year+' Q'+q.details.number,passed:answers.length===1&&a.details.exam_year===q.details.exam_year&&a.details.number===q.details.number&&a.refs[0].document_id===q.details.paired_document_id});
  if(q.details.year_basis==='filename_label'){
   const r=await (await page.request.get(base+'/api/search?q='+encodeURIComponent(q.details.year_label+' Q'+q.details.number+' 解答'))).json();
   results.push({name:'academic year '+q.details.year_label+' Q'+q.details.number,passed:r.records.length===2&&r.records[0].id===q.id&&r.records[1].id===a.id});
  }
 }
 return {round:'complete-sources-and-pairings',total:results.length,passed:results.filter(r=>r.passed).length,results};
}'''.replace('ITEMS',json.dumps(items,ensure_ascii=False))
(ROOT/'tests/browser_low_text_coverage.js').write_text(script,encoding='utf-8')
print('Prepared',len(items),'page checks')
