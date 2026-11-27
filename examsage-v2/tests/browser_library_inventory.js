async(page)=>{
  await page.goto('http://127.0.0.1:8766/');
  return await page.evaluate(async()=>{
    const courses=await (await fetch('/api/courses')).json();const results=[];
    for(const course of courses){
      const base=course.url.replace(/\/$/,'');
      const docs=await (await fetch(base+'/api/documents')).json();
      for(const doc of docs){
        const pages=doc.relative_path.toLowerCase().endsWith('.pptx')?[1,doc.pages]:[1];
        for(const number of [...new Set(pages)]){
          const item={course:course.slug,document:doc.relative_path,page:number,passed:false};
          try{
            const response=await fetch(base+'/api/page/'+doc.id+'/'+number);if(!response.ok)throw Error('page '+response.status);
            const data=await response.json();if(!data.preview_url)throw Error('No full-page preview');
            const preview=await fetch(base+data.preview_url);if(!preview.ok)throw Error('image '+preview.status);
            const image=await createImageBitmap(await preview.blob());item.width=image.width;item.height=image.height;image.close();
            item.kind=data.preview_kind;item.passed=item.width>100&&item.height>100;
          }catch(e){item.error=String(e);}
          results.push(item);
        }
      }
    }
    return {round:'all-source-preview',total:results.length,passed:results.filter(r=>r.passed).length,results};
  });
}
