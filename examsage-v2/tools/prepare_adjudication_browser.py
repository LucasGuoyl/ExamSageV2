"""Produce browser student checks from frozen IDs; UI interaction, not DOM injection."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/adjudication-20261102'
def main():
    baseline=json.loads((QA/'baseline.json').read_text(encoding='utf-8'))
    rows=[]
    for r in baseline['gaps']+baseline['conflicts']:
        d=r['details'];query=f"{d['exam_year']} Q{d['number']}"+''.join('('+p+')' for p in d['part'].split('.'))+' 答案'
        rows.append({'id':r['id'],'query':query})
    for entry in json.loads((ROOT/'courses/adjudication_gaps.json').read_text(encoding='utf-8')):
        original=next(r for r in baseline['gaps'] if r['id']==entry['record_id'])
        paired={original['refs'][0]['document_id'],original['details']['paired_document_id']}
        extra=next(e for e in entry['adjudication']['evidence'] if e['document_id'] not in paired)
        next(r for r in rows if r['id']==entry['record_id'])['supporting_source']=extra['document_id']
    pages=[{'course':r['course'],'id':r['document_id'],'number':r['number'],'name':Path(r['relative_path']).name} for r in baseline['pages']]
    config={'questions':rows,'pages':pages,'screenshot_dir':str(QA)}
    script='async(page)=>{const config='+json.dumps(config,ensure_ascii=False)+';'+r'''
      const results=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
      await page.setViewportSize({width:1440,height:1000});
      for(const row of config.questions){
        await page.goto('http://127.0.0.1:8766/courses/ses/?q='+encodeURIComponent(row.query));
        const target=page.locator('article[data-record-id="'+row.id+'"]');
        try{await target.waitFor({timeout:15000});const verdict=target.locator('.source-adjudication');await verdict.waitFor();
          const category=await verdict.getAttribute('data-category');
          const passed=['system_error','source_error','both','insufficient_evidence'].includes(category)&&await page.locator('.katex-error').count()===0;
          results.push({id:row.id,scenario:'学生查找小问、查看冲突归因及完整公式',category,passed});
          if(row.supporting_source){await verdict.locator('summary').click();await verdict.locator('button.ref[data-document="'+row.supporting_source+'"]').first().click();
            await page.waitForFunction(()=>document.querySelector('#pageContent img')?.complete&&document.querySelector('#pageContent img')?.naturalWidth>0);
            results.push({id:row.id,scenario:'打开教学补充对应课件原页',passed:await page.locator('#overlay').evaluate(e=>e.open)});await page.locator('#close').click();}
        }catch(e){results.push({id:row.id,passed:false,error:e.message.slice(0,300)});}
      }
      for(const row of config.pages){
        await page.goto('http://127.0.0.1:8766/courses/'+row.course+'/');
        const card=page.locator('article').filter({has:page.getByRole('heading',{name:row.name,exact:true})});
        await card.getByRole('button',{name:'查看第一页 →'}).click();
        await page.locator('#pageJump').fill(String(row.number));await page.locator('#jumpGo').click();
        await page.waitForFunction(()=>!!document.querySelector('#pageContent .source-adjudication'));
        await page.waitForFunction(()=>[...document.querySelectorAll('#pageContent img')].every(i=>i.complete&&i.naturalWidth>0));
        results.push({id:row.id+':p'+row.number,scenario:'原页、跨页证据和字面不确定',passed:await page.locator('#pageContent .recovery-warning').count()>0&&await page.locator('.katex-error').count()===0});
        await page.locator('#close').click();
      }
      for(const width of [390,320]){
        await page.setViewportSize({width,height:900});
        for(const row of [config.questions[0],config.questions.find(x=>x.query.startsWith('2024 Q1(e)(iii)')),config.questions.find(x=>x.query.startsWith('2023 Q2(c)(c)'))].filter(Boolean)){
          await page.goto('http://127.0.0.1:8766/courses/ses/?q='+encodeURIComponent(row.query));
          const target=page.locator('article[data-record-id="'+row.id+'"]');await target.waitFor();await target.locator('.source-adjudication').waitFor();
          const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
          await target.locator('.source-adjudication summary').click();
          const ref=target.locator('.source-adjudication button.ref').first();await ref.click();
          await page.waitForFunction(()=>document.querySelector('#pageContent img')?.complete&&document.querySelector('#pageContent img')?.naturalWidth>0);
          const opened=await page.locator('#overlay').evaluate(e=>e.open);await page.locator('#close').click();
          results.push({id:row.id,width,scenario:'手机阅读与原页返回',passed:!overflow&&opened&&await page.locator('.katex-error').count()===0});
        }
      }
      await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:8766/courses/ses/?q='+encodeURIComponent('2024 Q1(e)(iii) 答案'));
      await page.locator('.source-adjudication').first().waitFor();await page.locator('.source-adjudication').first().scrollIntoViewIfNeeded();await page.screenshot({path:config.screenshot_dir+'/ses-review.png',fullPage:false});
      await page.setViewportSize({width:390,height:900});await page.locator('.source-adjudication').first().scrollIntoViewIfNeeded();await page.screenshot({path:config.screenshot_dir+'/ses-mobile.png',fullPage:false});
      return {total:results.length,passed:results.filter(r=>r.passed).length,results,page_errors:errors};
    }'''
    (QA/'browser-students.js').write_text(script,encoding='utf-8');print({'question_scenarios':len(rows),'page_scenarios':len(pages)})
if __name__=='__main__':main()
