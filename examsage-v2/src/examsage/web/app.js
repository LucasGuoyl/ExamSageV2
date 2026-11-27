'use strict';
const $=id=>document.getElementById(id);
const basePath=(location.pathname.match(/^\/courses\/[a-z0-9_-]+/)||[''])[0];
const labels={concept:'知识点',formula:'公式',example:'案例',question:'真题',answer:'答案导读',block:'原文片段'};
let docs={},viewToken=0,sourceToken=0,sourceState=null,opener=null,zoom=1,metadataReady=false,metadataError=null,pendingSourceToken=null,pendingCourseView=null,courseMode='curated',examYears=[],hasQuestionPilot=false;
const messages={
  'Requested exam year, question number or subquestion is absent from the authorized snapshot.':'当前资料中没有这个年份、题号或小问，请核对后重试。',
  'Requested exam year or question number is absent from the authorized snapshot.':'当前资料中没有这个年份或题号的试题，请核对年份与题号。',
  'Requested exam year is absent from the authorized snapshot.':'当前资料中没有这个年份的试卷。',
  'No official exam answers or marking scheme exist in this authorized snapshot.':'当前资料未提供官方考试答案或评分标准。',
  'Embeddings are not configured; indexed keyword and course-alias retrieval is active.':'当前使用关键词和课程别名检索；表达差异较大时，可以尝试换用课程术语。',
  'Question mappings are inferred and require independent review.':'考题关联为推断结果，仍需独立核查。',
  'Some matching evidence omitted to respect context budget; complete objects were not truncated.':'为保留完整题干和公式，部分结果未在本次展示；可缩小查询范围继续查找。',
  'No matching evidence in the permitted course, sources and date range.':'当前可用课程资料中没有匹配证据。',
  'Source transcription visually checked by an agent; independent expert review remains pending.':'这段转录已由代理对照原页核查，尚未经独立专家验收。',
  'No official exam solution supplied.':'未提供官方考试答案。',
  'Formula/figure layout requires original-page verification.':'公式与图表请结合原始页面核对。'
};
const human=message=>message.startsWith('Missing exam years: ')?'缺少以下年份的试卷：'+message.slice('Missing exam years: '.length)+'。':messages[message]||message;
function el(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;}
function availabilityDetails(info) {
  const details = el('details', undefined, 'availability-note small');
  const receipt = info.basis === 'project_receipt';
  const label = receipt ? '项目收件日 ' + info.known_by + '（UTC）' : '清单登记可得日 ' + info.known_by;
  details.append(el('summary', label));
  if (receipt) details.append(el('p', '此日项目已持有下列版本。学校首次发布日期仍待核实。'));
  details.append(el('p', '文件 SHA-256：' + info.file_sha256));
  return details;
}
async function api(path,options={}){
  const response=await fetch(basePath+path,{cache:'no-store',...options});
  if(response.ok)return response.json();
  const body=[409,503].includes(response.status)?await response.json().catch(()=>null):null;
  const error=new Error(typeof body?.detail==='string'?body.detail:'读取失败，请检查资料是否可用。');
  error.status=response.status;throw error;
}
function active(button){
  document.querySelectorAll('.navbtn').forEach(x=>x.classList.toggle('active',x===button));
  if($('chatView')){const chat=button?.id==='chatNav';$('chatView').hidden=!chat;$('evidenceView').hidden=chat;if(chat)viewToken++;}
}
function showError(error){$('cards').setAttribute('aria-busy','false');$('count').textContent='读取失败';$('cards').replaceChildren(el('div',error.message,'empty'));}
function renderMath(node){
  if(typeof renderMathInElement!=='function')return;
  renderMathInElement(node,{delimiters:[{left:'\\(',right:'\\)',display:false},{left:'\\[',right:'\\]',display:true}],throwOnError:false,trust:false,strict:'warn',maxExpand:1000});
}
function formattedText(text){
  const body=el('div',undefined,'body');
  const lines=text.split('\n');let paragraph=[];
  const flush=()=>{if(paragraph.length){body.append(el('p',paragraph.join('\n')));paragraph=[];}};
  for(let i=0;i<lines.length;i++){
    if(lines[i].trim().startsWith('|')&&/^\s*\|(?:\s*:?-+:?\s*\|)+\s*$/.test(lines[i+1]||'')){
      flush();const cells=line=>line.trim().slice(1,-1).split('|').map(x=>x.trim());
      const wrap=el('div',undefined,'table-wrap'),table=el('table'),head=el('thead'),row=el('tr'),bodyRows=el('tbody');
      for(const text of cells(lines[i])){const th=el('th',text);th.scope='col';row.append(th);}head.append(row);table.append(head);i+=2;
      while(i<lines.length&&lines[i].trim().startsWith('|')){const tr=el('tr');for(const text of cells(lines[i]))tr.append(el('td',text));bodyRows.append(tr);i++;}
      i--;table.append(bodyRows);wrap.append(table);body.append(wrap);
    }else paragraph.push(lines[i]);
  }
  flush();renderMath(body);return body;
}
function details(title,content){const d=el('details');d.append(el('summary',title),content);return d;}
function hasReviewedTranscription(record){const data=record.details?.transcription;return !!(data&&typeof data==='object'&&data.review==='agent_source_checked'&&/^[a-f0-9]{64}$/.test(data.source_sha256)&&typeof record.details.raw_text==='string');}
function pageLink(id,number,label,sourceId){const b=el('button',label||'第 '+number+' 页 / 张','ref');b.type='button';b.dataset.document=id;b.dataset.page=number;b.onclick=()=>openPage(id,number,b,sourceId);return b;}
function derivationView(record){
  const data=record.details.derivation,content=el('div',undefined,'derivation-content');
  content.append(el('p','原页核查导读 · 非官方答案 · 独立专家验收待完成','small'));
  if(data.summary)content.append(formattedText(data.summary));
  for(const step of data.steps){const section=el('section');section.append(el('h4',step.title),formattedText(step.text));if(step.latex)section.append(formattedText('\\('+step.latex+'\\)'));const refs=el('div',undefined,'refs');for(const ref of (step.refs||(step.pages||[]).map(page=>({document_id:record.refs[0].document_id,page})))){const name=docs[ref.document_id]?.relative_path.split('/').pop();refs.append(pageLink(ref.document_id,ref.page,name?name+' · '+ref.page:undefined));}section.append(refs);content.append(section);}
  content.append(el('h4','适用条件'));for(const text of data.conditions)content.append(el('p',text,'small'));
  for(const text of data.warnings||[])content.append(el('p',text,'notice source-warning'));
  const d=details('查看跨页推导与适用条件',content);d.className='derivation';return d;
}
function reviewView(review,id){
  const content=el('div',undefined,'review-content');content.append(formattedText(review.summary),el('p','已由代理对照此页图像核查版式与关键内容；独立专家验收待完成。','small'));
  for(const latex of review.formulas||[])content.append(formattedText('\\('+latex+'\\)'));
  for(const table of review.tables||[]){const wrap=el('div',undefined,'table-wrap'),node=el('table'),head=el('thead'),row=el('tr'),body=el('tbody');for(const value of table.headers){const th=el('th',value);th.scope='col';row.append(th);}head.append(row);node.append(head);for(const values of table.rows){const tr=el('tr');for(const value of values)tr.append(el('td',value==null?'—':String(value)));body.append(tr);}node.append(body);wrap.append(node);content.append(wrap);}
  for(const ref of review.references||[]){if(!/^https:\/\//.test(ref.url))continue;const a=el('a',ref.title);a.href=ref.url;a.target='_blank';a.rel='noopener';content.append(a);}
  for(const chain of review.derivations||[]){const b=el('button','查看推导：'+chain.title,'linkbtn');b.onclick=async()=>{const token=++viewToken;closeSource();try{const data=await api('/api/record/'+encodeURIComponent(chain.id));if(token===viewToken)render([data.record],'跨页推导');}catch(e){if(token===viewToken)showError(e);}};content.append(b);}
  const d=details('查看本页核查导读（非官方答案）',content);d.className='visual-review';return d;
}
function adjudicationView(value){
  const labels={system_error:'系统错误',source_error:'原始资料错误',both:'系统与原始资料均有问题',insufficient_evidence:'证据仍不足'};
  const readable=text=>text.replace('逐页目视原PDF渲染；按原始参数独立复算；完整替换本叶audit，保留明确的原文差异与未决条件。','已对照原页，按原始参数重新计算；保留原文差异和仍未确定的条件。').replace('替代模型检查source_value改为空','不再把替代模型的结果与官方读数直接比较').replace('本项audit保留partial','本项仍有未确定内容').replaceAll('numerical_checks','数值核对').replaceAll('source_value','来源数值').replaceAll('mismatch','不一致');
  const body=el('section',undefined,'source-adjudication');body.dataset.category=value.category;
  body.append(el('h4','来源复核结论：'+labels[value.category]),formattedText(value.summary));
  for(const [key,label] of [['system_findings','系统问题'],['source_findings','原始资料问题'],['actions','本次处理'],['remaining','仍有限制']]){
    if(value[key].length){body.append(el('h5',label));for(const text of value[key])body.append(formattedText(readable(text)));}
  }
  const evidence=el('div');for(const row of value.evidence){evidence.append(formattedText(row.observation),pageLink(row.document_id,row.page,(docs[row.document_id]?.relative_path.split('/').pop()||'来源')+' · '+row.page));}
  body.append(details('查看本次复核的原页证据',evidence));return body;
}
function supplementView(data){
  const audit=data.audit,content=el('div',undefined,'supplement-content');
  content.append(el('p',({text:'文字或标题页',diagram:'图像与示意图',mixed:'文字、图表或公式混合',blank:'已确认空白页'})[audit.category]+' · 代理分类与关键内容核查 · 专家验收待完成','small'),formattedText(audit.summary));
  if(audit.transcription)content.append(details('查看代理核对转录',formattedText(audit.transcription)));
  for(const latex of audit.formulas||[])content.append(formattedText('\\('+latex+'\\)'));
  for(const warning of audit.warnings||[])content.append(formattedText('核查注记：'+warning));
  if(audit.recovery){const r=audit.recovery,body=el('div');body.append(el('p',({source_transcribed:'原图文字与公式已逐项转录',diagram_described:'图示与标注已补充说明',partially_legible:'已复核可辨内容，仍有局部不确定'})[r.status]+'；原始 OCR 保留，独立专家验收待完成。','small'));
    if(r.adjudication)body.append(adjudicationView(r.adjudication));
    for(const block of r.blocks){body.append(formattedText(block.text));if(block.latex)body.append(formattedText('\\('+block.latex+'\\)'));}
    for(const note of r.unresolved)body.append(el('p','仍需核对：'+note,'notice recovery-warning'));
    const review=details('查看低置信度内容逐项复核',body);review.className='page-recovery';review.open=true;content.append(review);}
  const d=details('查看低文本页补充说明',content);d.className='page-supplement';d.open=true;return d;
}
function auditView(record){
  const audit=record.details.audit,body=el('div',undefined,'audit-content');
  if(audit.adjudication && !audit.status)return adjudicationView(audit.adjudication);
  if(audit.adjudication)body.append(adjudicationView(audit.adjudication));
  body.append(el('p',({checked:'已按来源逐项核对',source_conflict:'发现来源条件或答案冲突',partial:'仍有未能确认的内容'})[audit.status]+' · 代理复核，独立专家验收待完成',audit.status==='checked'?'small':'notice'));
  for(const note of audit.warnings)body.append(el('p',note,'notice source-warning'));
  body.append(el('h4','题目条件与约定'));for(const text of audit.conditions)body.append(formattedText(text));
  if(audit.formula_checks.length)body.append(el('h4','公式与适用条件'));
  for(const f of audit.formula_checks)body.append(formattedText('\\('+f.latex+'\\)'),formattedText(f.note));
  if(audit.numerical_checks.length){
    body.append(el('h4','按列明条件独立复算'),el('p','数值一致只表示列明算式与来源数值相符；公式是否适用、条件是否一致，请结合上方核查注记。','small'));
    for(const check of audit.numerical_checks){const section=el('section',undefined,'numeric-check');
      section.dataset.comparison=check.comparison;section.append(el('h5',check.label),el('p','输入：'+Object.entries(check.inputs||{}).map(([k,v])=>k+' = '+v).join('；'),'small'),el('code',check.expression));
      const table=el('table'),tr=el('tr');for(const t of ['复算值','来源答案值','单位','数值比较']){const th=el('th',t);th.scope='col';tr.append(th);}const head=el('thead');head.append(tr);table.append(head);
      const row=el('tr');for(const value of [Number(check.computed_value.toPrecision(10)),check.source_value??'未报告',check.unit,({agrees:'在容差内一致',mismatch:'不一致',not_reported:'来源未报告数值，不判定一致'})[check.comparison]])row.append(el('td',String(value)));const tbody=el('tbody');tbody.append(row);table.append(tbody);const wrap=el('div',undefined,'table-wrap');wrap.append(table);section.append(wrap);
      section.append(el('p','绝对容差 '+(check.atol??.000001)+'；相对容差 '+(check.rtol??.001),'small'));if(check.note)section.append(formattedText(check.note));
      const refs=el('div',undefined,'refs');for(const ref of check.source_refs||[])refs.append(pageLink(ref.document_id,ref.page,(docs[ref.document_id]?.relative_path.split('/').pop()||'来源')+' · '+ref.page));section.append(refs);body.append(section);
    }
  }else if(record.details.audit_checks_deferred_count){body.append(el('p','这里保留父题公共条件；'+record.details.audit_checks_deferred_count+' 项父题计算可单独打开，当前小问的复算已完整显示。','small'));const b=el('button','查看此父题完整核对 →','linkbtn');b.onclick=()=>search(record.details.exam_year+' Q'+record.details.number+(record.details.part||'').split('.').filter(Boolean).map(p=>'('+p+')').join('')+' 答案');body.append(b);}
  else body.append(el('p',({qualitative:'本小问为定性解释，不以数值检查代替内容核对。',symbolic:'本小问为符号推导；已记录公式与条件。',unresolved:'数值结果暂未能确认，请查看以下注记。'})[audit.numerical_status]||'本小问无数值复算项。','small'));
  if(audit.previous_assessment)body.append(details('查看上一版核查记录（历史结论，不作为当前答案）',el('pre',JSON.stringify(audit.previous_assessment,null,2),'pageText')));
  else if(record.details.audit_history_deferred){const b=el('button','查看本条完整核查与修改历史','linkbtn');b.onclick=async()=>{const token=++viewToken;try{const data=await api('/api/record/'+encodeURIComponent(record.id));if(token===viewToken)render([data.record],'来源复核与修改历史');}catch(e){if(token===viewToken)showError(e);}};body.append(b);}
  const d=details('查看小问条件、公式与答案核对',body);d.className='subquestion-audit';d.open=true;return d;
}
function render(records,title,limitations=[]){
  $('cards').setAttribute('aria-busy','false');
  $('sectionTitle').textContent=title;$('count').textContent=records.length+' 条结果';$('cards').replaceChildren();$('resultLimitations').replaceChildren();
  if(limitations.length){const d=details('本次检索的说明',el('div'));d.open=true;d.className='notice';for(const note of limitations)d.lastChild.append(el('p',human(note),'small'));$('resultLimitations').append(d);}
  if(!records.length)$('cards').append(el('div','没有找到足够证据。请核对年份、题号或改用课程术语。','empty'));
  for(const r of records){
    const card=el('article',undefined,'card');card.dataset.kind=r.kind;card.dataset.recordId=r.id;
    const role = r.details?.locator_role;
    const badge = role==='question' ? '原卷题干' : role==='answer_candidate' ? '答案候选' : labels[r.kind]||r.kind;
    card.append(el('span',badge,'badge'),el('span',hasReviewedTranscription(r)?'原页核对转录':r.review==='machine_checked'?'自动抽取':'待独立核查','tag'),el('h3',r.title));
    if(r.details?.marks!=null)card.append(el('p',r.details.marks+' 分','small'));
    if(r.details?.shared_stem&&r.parent_id)card.append(details('公共题干',formattedText(r.details.shared_stem)));
    card.append(formattedText(r.text));
    for(const note of r.details?.warnings||[])card.append(el('p',note,'notice source-warning'));
    if(r.details?.audit)card.append(auditView(r));
    if(r.details?.audit_unavailable)card.append(el('p',r.details.audit_unavailable,'notice'));
    if(r.details?.audit_on_record_id){const b=el('button','查看上方对应小问的条件与复算 ↑','linkbtn');b.onclick=()=>[...document.querySelectorAll('article[data-record-id]')].find(node=>node.dataset.recordId===r.details.audit_on_record_id)?.scrollIntoView({behavior:'smooth'});card.append(b);}
    if(r.details?.derivation)card.append(derivationView(r));
    if(r.details?.latex){
      const math=el('div',undefined,'math-block');
      try{if(typeof katex==='undefined')throw new Error('renderer unavailable');katex.render(r.details.latex,math,{displayMode:true,throwOnError:true,trust:false,maxExpand:1000});}
      catch(error){math.append(el('p','公式暂未排版，请查看表达式或原页。','render-warning'),el('code',r.details.latex));}
      const d=details('查看公式表达与适用条件',math);for(const x of r.details.conditions||[])d.append(el('p',x,'small'));d.append(details('查看 LaTeX 表达式',el('pre',r.details.latex,'pageText')));card.append(d);
    }
    const refs=el('div',undefined,'refs');
    for(const ref of r.refs){const doc=docs[ref.document_id],name=doc?doc.relative_path.split('/').pop():ref.document_id;const b=el('button',name+' · '+ref.page,'ref');b.dataset.document=ref.document_id;b.dataset.page=ref.page;b.onclick=()=>openPage(ref.document_id,ref.page,b);refs.append(b);}card.append(refs);
    if(['concept','formula','example'].includes(r.kind)){const b=el('button','查看关联考题 →','linkbtn');b.onclick=async()=>{const token=++viewToken;try{const data=await api('/api/related/'+encodeURIComponent(r.id));if(token===viewToken)render(data.records,'相关考题 · '+r.title,data.limitations);}catch(e){if(token===viewToken)showError(e);}};card.append(b);}
    if(r.kind==='question'){
      if(r.details?.exam_topic_evidence?.length){
        const body=el('div');
        for(const item of r.details.exam_topic_evidence){
          const origin=item.label_origin==='printed_title'?'卷面标题':'题干短引';
          body.append(el('p',item.topic+' · '+origin+'：“'+item.quote+'”'),
                      pageLink(item.document_id,item.page,'查看原卷第 '+item.page+' 页',item.source_id));
        }
        card.append(details('本题复习主题与原文',body));
      }
      if(r.details?.children_count){const b=el('button','查看 '+r.details.children_count+' 个下一级小问 →','linkbtn children-link');b.onclick=async()=>{const token=++viewToken;try{const [children,context]=await Promise.all([api('/api/records?kind=question&parent='+encodeURIComponent(r.id)),api('/api/question/'+encodeURIComponent(r.id))]);if(token===viewToken){render(children,'小问 · '+r.title,context.limitations);const body=el('div');for(const parent of context.records){body.append(el('h4',parent.title),formattedText(parent.text));for(const condition of parent.details.audit?.conditions||[])body.append(formattedText(condition));const refs=el('div',undefined,'refs');for(const ref of parent.refs)refs.append(pageLink(ref.document_id,ref.page,(docs[ref.document_id]?.relative_path.split('/').pop()||'原卷')+' · '+ref.page));body.append(refs);}const shared=details('公共题干与上级条件',body);shared.className='shared-question-context';shared.open=true;$('cards').prepend(shared);}}catch(e){if(token===viewToken)showError(e);}};card.append(b);}
      if(r.details?.has_answer){const b=el('button','查看本题配对答案 →','linkbtn answer-link');b.onclick=async()=>{const token=++viewToken;try{const bundle=await api('/api/answer/'+encodeURIComponent(r.id));if(token===viewToken)render(bundle.records,'题目与配对答案 · '+r.title,bundle.limitations);}catch(e){if(token===viewToken)showError(e);}};card.append(b,el('p',r.details.audit?'请对照上方条件、公式、复算与来源注记。':'已核对大题与来源对应；可进入小问查看逐项核对。','small'));}
      else card.append(el('div','未提供已配对的官方答案；请结合原卷与课程材料核对。','warning'));
    }
    if(hasReviewedTranscription(r))card.append(details('查看原始抽取文本（未修正）',el('pre',r.details.raw_text,'raw-text')));
    if(r.limitations?.length){const notes=details('查看内容限制与核查状态',el('div'));for(const note of r.limitations)notes.lastChild.append(el('p',human(note),'small'));card.append(notes);}
    $('cards').append(card);
  }
}
async function showKinds(kinds,title,topic){const token=++viewToken;$('cards').setAttribute('aria-busy','true');$('count').textContent='加载中…';$('cards').replaceChildren(el('div','正在加载课程内容…','empty'));try{const groups=await Promise.all(kinds.map(k=>api('/api/records?kind='+k+(k==='question'&&courseMode==='source_pages'?'&roots=true':'')+(topic?'&topic='+encodeURIComponent(topic):''))));if(token===viewToken)render(groups.flat(),title);}catch(e){if(token===viewToken)showError(e);}}
async function search(query,selection=null){
  const token=++viewToken;
  active(null);
  if(!selection)$('query').value=query;
  $('count').textContent='查找中…';
  const params=new URLSearchParams({q:query});
  if(selection)for(const [key,value] of Object.entries(selection))params.set(key,String(value));
  try{
    const bundle=await api('/api/search?'+params);
    if(token!==viewToken)return;
    render(bundle.records,selection?'所选试卷 · '+query:'检索结果',bundle.limitations);
    if(bundle.sufficiency==='insufficient')$('count').textContent='证据不足';
  }catch(e){if(token===viewToken)showError(e);}
}

function configurePaperPicker(documents,available){
  const visible=documents.filter(d=>d.first_visible_page && ['unknown','exam','exam_solution'].includes(d.kind));
  if(!available || !visible.some(d=>d.kind!=='exam_solution'))return;
  const picker=$('paperPicker'),form=$('paperForm'),paper=$('paperFile'),solution=$('solutionFile');
  picker.hidden=false;
  $('openPaperPicker').hidden=false;
  $('openPaperPicker').onclick=()=>{
    active(null);
    picker.open=true;
    $('paperYear').focus();
  };
  function fill(select,kind,prompt){
    select.add(new Option(prompt,''));
    for(const doc of visible.filter(d=>d.kind==='unknown'||d.kind===kind)){
      const name=doc.relative_path+(doc.exam_year?' · '+doc.exam_year:'')+' · '+doc.pages+' 页';
      select.add(new Option(name,doc.id));
    }
  }
  fill(paper,'exam','请选择试卷');
  fill(solution,'exam_solution','只查题目');
  for(const [select,button] of [[paper,$('previewPaper')],[solution,$('previewSolution')]]){
    select.onchange=()=>{button.disabled=!select.value;$('paperMessage').textContent='';};
    button.onclick=()=>{const doc=docs[select.value];if(doc)openPage(doc.id,doc.first_visible_page,button);};
  }
  function request(){
    $('paperMessage').textContent='';
    if(!form.reportValidity())return null;
    if(solution.value && (paper.value===solution.value || docs[paper.value].sha256===docs[solution.value].sha256)){
      $('paperMessage').textContent='请选择内容不同的试卷和答案。';return null;
    }
    const selection={paper_id:paper.value,exam_year:Number($('paperYear').value)};
    if(solution.value)selection.solution_id=solution.value;
    const part=$('paperQuestion').value.trim();
    if(!part){$('paperMessage').textContent='请填写题号或小问编号。';return null;}
    return {selection,query:part+(solution.value?' 答案':' 只给题目')};
  }
  form.onsubmit=e=>{e.preventDefault();const req=request();if(req)search(req.query,req.selection);};
  $('paperToChat').onclick=()=>{
    const req=request();if(!req)return;
    const input=$('chatInput');
    if(input.value.trim()){$('paperMessage').textContent='对话里已有草稿，请先发送或清空草稿。';return;}
    if(input.disabled){$('paperMessage').textContent='当前对话正在处理请求，请稍后发送。';return;}
    $('chatNav').click();
    $('chatForm').dispatchEvent(new CustomEvent('selected-paper',{detail:req}));
  };
}

function setZoom(value){zoom=Math.min(4,Math.max(.5,value));$('zoomLevel').textContent=Math.round(zoom*100)+'%';for(const viewer of document.querySelectorAll('.image-viewer'))for(const img of viewer.querySelectorAll('img'))img.style.width=Math.round(viewer.clientWidth*zoom)+'px';$('zoomOut').disabled=zoom<=.5;$('zoomIn').disabled=zoom>=4;}
function closeSource(){sourceToken++;if($('overlay').open)$('overlay').close();}
function studyFileLink(id){
  const link=el('a','下载本文件的对话学习资料（TXT）','download');
  link.href=basePath+'/api/study-file/'+encodeURIComponent(id);
  link.download='';
  return link;
}
async function openPage(id,number,trigger=null,sourceId=null){
  const token=++sourceToken;
  const prior=!trigger&&sourceState?.id===id?sourceState:null;
  const anchorId=sourceId||prior?.anchorId,anchorPage=sourceId?number:prior?.anchorPage;
  if(!$('overlay').open){opener=trigger||document.activeElement;zoom=1;$('overlay').showModal();$('close').focus();}
  sourceState={id,number,anchorId,anchorPage};$('pageTitle').textContent='正在读取原文…';$('pageContent').replaceChildren();$('previous').disabled=true;$('next').disabled=true;$('pageJump').disabled=true;$('jumpGo').disabled=true;$('pageJumpError').textContent='';
  try{
    const query=new URLSearchParams();
    if(anchorId){query.set('source_id',anchorId);if(anchorPage!==number)query.set('source_page',anchorPage);}
    const path='/api/page/'+encodeURIComponent(id)+'/'+number+(query.size?'?'+query:'');
    const p=await api(path);if(token!==sourceToken||!$('overlay').open)return;
    if(anchorId&&(!/^src_[0-9a-f]{64}$/.test(p.source_id)||anchorPage===number&&p.source_id!==anchorId)){
      throw new Error('服务未确认本页的来源编号，请重新打开课程后回测。');
    }
    $('pageTitle').textContent=p.document.relative_path.split('/').pop()+' · '+number;$('pagePosition').textContent=number+' / '+p.document.pages;
    $('previous').disabled=number<=1;$('next').disabled=number>=p.document.pages;
    $('pageJump').max=p.document.pages;$('pageJump').value=number;$('pageJump').disabled=false;$('jumpGo').disabled=false;
    const currentId=p.source_id,checked=currentId?'?source_id='+encodeURIComponent(currentId):'';
    const body=$('pageContent'),download=el('a','下载原始文件','download');download.href=basePath+'/api/source/'+encodeURIComponent(id)+(checked?checked+'&page='+number:'');download.target='_blank';download.rel='noopener';body.append(download);
    body.append(document.createTextNode(' · '),studyFileLink(id));
    if(p.preview_url){
      const imageLink=el('a','下载本页原图（PNG）','download');
      imageLink.href=basePath+'/api/study-image/'+encodeURIComponent(id)+'/'+number+checked;
      imageLink.download='';
      body.append(document.createTextNode(' · '),imageLink);
    }
    if($('learningNav') && p.learning_source_id)body.append(learningEditor(id,number,p.learning_source_id));
    const isSlide=p.preview_kind==='pptx_full_slide',record=p.bundle.records[0],review=record.details.visual_review;
    body.append(el('p',isSlide?'完整幻灯片 · 保留原版式的静态预览，可放大、翻页或直接输入页码。':p.preview_url?'可放大原卷并翻页，核对公式、表格与题干。':'以下为提取的图片和文字，尚未恢复完整幻灯片布局。','notice'));
    if(p.page_erratum){const note=el('aside',undefined,'notice audit-warnings');note.append(el('strong','原页勘误（代理核查）'),formattedText(p.page_erratum));body.append(note);}
    if(isSlide&&record.details.render?.animation_steps>0)body.append(el('p','本页包含动画；这里只显示静态合成，不能重现逐步播放。可下载原始文件查看动画。','notice'));
    if(review?.warnings?.length){const warnings=el('div',undefined,'notice audit-warnings');warnings.append(el('strong','原页核查注记'));for(const note of review.warnings)warnings.append(formattedText(note));body.append(warnings);}
    const urls=(p.preview_url?[p.preview_url]:p.media_urls).map(url=>basePath+url);
    for(const url of urls){const viewer=el('div',undefined,'image-viewer'),img=el('img');img.src=url;img.alt=isSlide?'完整幻灯片 第 '+number+' 张':p.preview_url?'原始 PDF 第 '+number+' 页':'幻灯片嵌入图';img.className='pageimg';img.onload=()=>{if(token===sourceToken)setZoom(zoom);};img.onerror=()=>{if(token!==sourceToken)return;img.replaceWith(el('p',currentId?'当前原图无法核验或显示，请查看已收录的原页文字。':'此图无法预览，请下载原文件查看。','small'));const raw=body.querySelector('.raw-section');if(raw)raw.open=true;};viewer.append(img);body.append(viewer);}
    if(review)body.append(reviewView(review,id));
    if(record.details.supplement){
      const supplement=record.details.supplement;body.append(supplementView(supplement));
      const content=el('div');content.append(el('p','自动识别候选，公式、数字和顺序可能有误；置信度不是正确率。'+(supplement.ocr_indexed?'已纳入关键词检索，请对照原页。':'本页识别置信度不足或为空白；OCR文字未纳入检索。'),'small'),el('pre',supplement.ocr.text||'本次 OCR 未识别到文字，请以原页与补充说明为准。','pageText'));
      const ocr=details('查看 OCR 自动识别（未核验）',content);ocr.className='ocr-section';body.append(ocr);
    }
    const raw=details('查看原始抽取文字（可能含识别误差）',el('pre',record.details.raw_text??record.text??'此页未提取到可用文字。','pageText'));raw.className='raw-section';raw.open=!p.preview_url&&!urls.length;body.append(raw);setZoom(zoom);body.scrollTop=0;
  }catch(error){if(token===sourceToken){$('pageTitle').textContent='原文读取失败';$('pageContent').append(el('p',error.message,'notice'));}}
}
if($('learningNav')){
  $('learningNav').onclick=showLearning;
  $('overlay').addEventListener('close',()=>queueMicrotask(refreshLearningList));
}
$('close').onclick=closeSource;
$('overlay').addEventListener('cancel',()=>{sourceToken++;});
$('overlay').addEventListener('close',()=>{sourceToken++;sourceState=null;if(opener?.isConnected)opener.focus();});
$('overlay').addEventListener('click',e=>{if(e.target===$('overlay'))closeSource();});
$('overlay').addEventListener('keydown',event=>{
  if(event.key!=='Tab')return;
  const items=[...$('overlay').querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),summary')].filter(node=>node.getClientRects().length&&getComputedStyle(node).visibility!=='hidden');
  const first=items[0],last=items[items.length-1];
  if(!first)return;
  if(event.shiftKey&&(document.activeElement===first||!items.includes(document.activeElement))){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&(document.activeElement===last||!items.includes(document.activeElement))){event.preventDefault();first.focus();}
});
$('previous').onclick=()=>{if(sourceState)openPage(sourceState.id,sourceState.number-1);};
$('next').onclick=()=>{if(sourceState)openPage(sourceState.id,sourceState.number+1);};
function jumpPage(){if(!sourceState||$('pageJump').disabled)return;const n=Number($('pageJump').value),max=Number($('pageJump').max);if(!Number.isInteger(n)||n<1||n>max){$('pageJumpError').textContent='请输入 1—'+max+' 之间的整数页码。';return;}openPage(sourceState.id,n);}
$('jumpGo').onclick=jumpPage;$('pageJump').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();jumpPage();}};
$('zoomIn').onclick=()=>setZoom(zoom+.5);$('zoomOut').onclick=()=>setZoom(zoom-.5);$('zoomFit').onclick=()=>setZoom(1);
$('wide').onclick=()=>{$('overlay').classList.toggle('wide');$('wide').textContent=$('overlay').classList.contains('wide')?'收起阅读':'展开阅读';requestAnimationFrame(()=>setZoom(zoom));};
window.addEventListener('resize',()=>{if($('overlay').open)setZoom(zoom);});
$('searchForm').onsubmit=e=>{e.preventDefault();const q=$('query').value.trim();if(q)search(q);};
if($('chatNav'))$('chatNav').onclick=()=>active($('chatNav'));
function showCourseView(examsOnly){
  active($(examsOnly?'exam':'all'));
  if(metadataError){viewToken++;showError(metadataError);return;}
  if(!metadataReady){
    pendingCourseView={token:++viewToken,examsOnly};
    $('cards').setAttribute('aria-busy','true');$('count').textContent='加载资料…';
    $('resultLimitations').replaceChildren();$('cards').replaceChildren(el('div','正在读取课程资料…','empty'));
    return;
  }
  if(courseMode==='source_pages')showSourceDocuments(examsOnly);
  else showKinds(examsOnly?['question']:['concept','example'],examsOnly?'历年真题 · '+examYears.join(' / '):'课程知识');
}
$('all').onclick=()=>showCourseView(false);
$('exam').onclick=()=>showCourseView(true);
$('formulas').onclick=()=>{active($('formulas'));showKinds(['formula'],'公式索引');};
function showSourceDocuments(examsOnly=false){
  $('cards').setAttribute('aria-busy','false');
  viewToken++;if(!examsOnly)active($('sources'));$('resultLimitations').replaceChildren();$('sectionTitle').textContent=examsOnly?'试卷、练习与答案资料':'原始资料';$('cards').replaceChildren();
  if(metadataError){showError(metadataError);return;}
  if(!metadataReady){pendingSourceToken=viewToken;$('count').textContent='加载资料…';$('cards').append(el('div','正在读取资料清单…','empty'));return;}
  const documents=Object.values(docs).filter(doc=>!examsOnly||['exam','exam_solution','practice','mock_exam','exam_guidance','tutorial_feedback','formula_sheet'].includes(doc.kind));$('count').textContent=documents.length+' 份';
  if(examsOnly&&courseMode==='source_pages')$('resultLimitations').append(el('p',hasQuestionPilot?'这里按原文件浏览；已核对的题答对应请进入“已整理题目”。旧年份仍保留文件名依据。':'按文件级审阅分类；年份与逐题对应尚未验证。练习、模拟卷和正式试卷分别标注。','notice'));
  for(const doc of documents){
    const card=el('article',undefined,'card');
    card.append(el('span',({lecture:'教学资料',exam:'正式试卷',formula_sheet:'公式数据表',tutorial_feedback:'习题反馈',practice:'练习题',mock_exam:'模拟试卷',exam_guidance:'考试指导与示例',exam_solution:'答案与评分反馈',unknown:'未分类资料'})[doc.kind]||doc.kind,'badge'),
      el('h3',doc.relative_path.split('/').pop()),el('p',doc.pages+' 页／张'+(doc.exam_year?' · '+doc.exam_year:''),'small'));
    if(doc.availability) card.append(availabilityDetails(doc.availability));
    else if(doc.kind==='exam') card.append(el('p','可得日期待核实。','small'));
    if(doc.first_visible_page===null){
      card.append(el('p','当前范围内没有可见原页。','small'));
    }else{
      const first=doc.first_visible_page??1;
      const open=el('button',first===1?'查看第一页 →':'查看第 '+first+' 页 →','linkbtn');
      open.onclick=()=>openPage(doc.id,first,open);
      card.append(open,document.createTextNode(' · '),studyFileLink(doc.id));
    }
    $('cards').append(card);
  }
}
$('sources').onclick=()=>showSourceDocuments(false);
$('courseSelect').onchange=()=>{const url=$('courseSelect').value;if(url==='/'||/^\/courses\/[a-z0-9_-]+\/$/.test(url))location.assign(url);};
(async()=>{try{
  const bootstrapToken=viewToken;
  const [status,documents,courses]=await Promise.all([api('/api/status'),api('/api/documents'),api('/api/courses')]);docs=Object.fromEntries(documents.map(d=>[d.id,d]));metadataReady=true;configurePaperPicker(documents,status.paper_selection_available);courseMode=status.structure_mode;examYears=status.exam_years||[];hasQuestionPilot=!!status.pilot_records&&!!status.counts.question;$('notice').textContent=status.notice;
  $('courseName').textContent=status.course;$('courseCode').textContent=status.course_key||'';document.title='押题宝 v2 · '+status.course;$('topicHeading').textContent=status.topics.length?'课程主题':'课程资料';
  if(status.recovery_pages)$('notice').textContent+='已逐项复核 '+status.recovery_pages+' 个低置信度页，仍有 '+(status.recovery_states.partially_legible||0)+' 页局部未确定。';
  if(status.pilot_records){const questionPilot=!!status.counts.question;const button=el('button',questionPilot?'已整理题目':'跨页推导试点','navbtn');button.id='pilots';button.onclick=()=>{active(button);showKinds(questionPilot?['question']:['concept','formula','example'],questionPilot?'已整理大题 · 可逐级查看小问':'跨页推导试点');};$('nav').insertBefore(button,$('sources'));$('notice').textContent+=(questionPilot?'已整理 '+(status.whole_questions??status.counts.question)+' 道大题、'+(status.subquestions||0)+' 个编号小问；'+status.pilot_answer_pairs+' 组题答对应。旧年份保留文件名依据；复算与来源冲突见小问。':'已提供板块弯曲跨页推导试点。');}
  for(const course of courses){const option=el('option',course.name);option.value=course.url;option.selected=course.url===(basePath?basePath+'/':'/');$('courseSelect').append(option);}
  $('formulas').disabled=courseMode==='source_pages';$('formulas').title=courseMode==='source_pages'?'尚未整理独立公式索引，请通过原始资料和检索查看':'';
  if(courseMode==='source_pages'){$('all').textContent='课程资料';$('exam').textContent='试卷与练习';$('query').placeholder=status.suggested_queries?.length?'例如：'+status.suggested_queries.slice(0,2).join('、'):'输入本课程的知识点或资料关键词';}
  for(const button of document.querySelectorAll('.ref[data-document]')){const doc=docs[button.dataset.document];if(doc)button.textContent=doc.relative_path.split('/').pop()+' · '+button.dataset.page;}
  for(const [n,label] of [[status.documents,'原始资料'],[status.pages,'页 / 幻灯片'],[(status.counts.concept||0)+(status.counts.example||0),'知识与案例'],[status.counts.question||0,'大题与编号小问']]){const d=el('div',undefined,'stat');d.append(el('b',n),el('span',label));$('stats').append(d);}
  for(const t of status.topics){const b=el('button',t.title.split(' / ')[0],'navbtn');b.onclick=()=>{active(b);showKinds(['concept','example','formula'],t.title,t.id);};$('topics').append(b);}
  for(const q of (courseMode==='source_pages'?status.suggested_queries:['孔隙度与孔隙流速','2024 Q1 地下水年龄','反应前缘公式','Ozark 流动驱动力'])){const b=el('button',q,'chip');b.onclick=()=>search(q);$('examples').append(b);}
  if(viewToken===bootstrapToken){const query=new URLSearchParams(location.search).get('q');if(query?.trim()&&query.length<=4000)await search(query);else if(!$('chatView')){if(courseMode==='source_pages')showSourceDocuments();else await showKinds(['concept','example'],'课程知识');}}
  else if(pendingSourceToken===viewToken)$('sources').onclick();
  else if(pendingCourseView?.token===viewToken)showCourseView(pendingCourseView.examsOnly);
}catch(e){metadataError=e;$('notice').textContent='课程概览读取失败，请刷新重试。';if(viewToken===0||pendingSourceToken===viewToken||pendingCourseView?.token===viewToken)showError(e);}})();

