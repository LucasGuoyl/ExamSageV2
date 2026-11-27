'use strict';
const progressLabels = {new:'待学习', practising:'练习中', review:'需复习', confident:'已掌握'};

let learningListChanged=false;

function refreshLearningList() {
  if(learningListChanged && $('learningNav').classList.contains('active') && !$('overlay').open){
    learningListChanged=false;
    showLearning();
  }
}

function learningEditor(documentId, page, sourceId) {
  const box = el('details', undefined, 'learning-editor');
  const title = el('summary','我的复习进度');
  const statusLabel = el('label','本页学习状态');
  const select = el('select');
  for (const [value,label] of Object.entries(progressLabels)) select.add(new Option(label,value));
  statusLabel.append(select);
  const noteLabel = el('label','个人笔记');
  const note = el('textarea');
  note.maxLength=10000;
  noteLabel.append(note);
  const save = el('button','保存复习记录');
  const reload = el('button','重新读取');
  const message = el('p','','small');
  message.setAttribute('role','status');
  save.type=reload.type='button';
  box.append(title,statusLabel,noteLabel,save,reload,message);
  const path='/api/learning/'+encodeURIComponent(documentId)+'/'+page;
  let previous=null, loaded=false, busy=false;
  function controls(ready) {
    select.disabled=note.disabled=save.disabled=!ready;
  }
  async function read() {
    if(busy)return;
    busy=true; controls(false); reload.hidden=true; message.textContent='正在读取复习记录…';
    try {
      const data=await api(path+'?source_id='+encodeURIComponent(sourceId));
      previous=data.revision; select.value=data.status; note.value=data.note;
      title.textContent=data.revision?'我的复习进度 · '+progressLabels[data.status]:'我的复习进度';
      message.textContent=data.revision?'已读取上次保存的记录。':'尚未保存这页的复习记录。';
      loaded=true; controls(true);
    } catch(error) {
      message.textContent=error.message; reload.hidden=false;
    } finally {busy=false;}
  }
  async function write() {
    if(!loaded||busy)return;
    busy=true;controls(false);message.textContent='正在保存…';
    try {
      const data=await api(path,{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({source_id:sourceId,revision:previous,status:select.value,note:note.value})});
      previous=data.revision; title.textContent='我的复习进度 · '+progressLabels[data.status];
      message.textContent='已保存复习记录。'; controls(true);
      learningListChanged=true;
      refreshLearningList();
    } catch(error) {
      message.textContent=error.message;
      if(error.status===409){
        reload.textContent='用已保存记录替换草稿';reload.hidden=false;
        note.disabled=false;note.readOnly=true;
      } else {controls(true);}
    } finally {busy=false;}
  }
  controls(false);reload.hidden=true;
  save.onclick=write;
  reload.onclick=()=>{note.readOnly=false;read();};
  box.addEventListener('toggle',()=>{if(box.open&&!loaded&&!busy)read();});
  if($('learningNav').classList.contains('active'))box.open=true;
  return box;
}

async function showLearning() {
  active($('learningNav'));
  const token=++viewToken;
  $('sectionTitle').textContent='我的复习';$('count').textContent='';
  $('resultLimitations').replaceChildren();
  $('cards').setAttribute('aria-busy','true');
  try {
    const {pages}=await api('/api/learning');
    if(token!==viewToken)return;
    const focused=document.activeElement?.dataset.learningSource;
    $('cards').replaceChildren();
    $('cards').setAttribute('aria-busy','false');$('count').textContent=pages.length+' 页';
    if(!pages.length)$('cards').append(el('p','打开课件原页，在“我的复习进度”中保存状态和笔记。','empty'));
    for(const row of pages){
      const card=el('article',undefined,'card');
      const resume=pageLink(row.document_id,row.page,'继续复习 · 第 '+row.page+' 页',row.source_id);
      resume.dataset.learningSource=row.source_id;
      card.append(el('span',progressLabels[row.status],'badge'),el('h3',row.filename),resume);
      $('cards').append(card);
      if(focused===row.source_id)resume.focus();
    }
  } catch(error){if(token===viewToken)showError(error);}
}
