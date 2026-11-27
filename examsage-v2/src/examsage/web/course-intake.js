'use strict';
const byId = id => document.getElementById(id);
const chosen = [];
let busy = false;
const kinds = [
  ['unknown','待确认'], ['lecture','课程讲义'], ['exam','正式试卷'], ['exam_solution','试卷答案'],
  ['mock_exam','模拟试卷'], ['practice','练习'], ['formula_sheet','公式表'], ['textbook','教材'],
  ['primary_source','原始史料'], ['literary_text','文学作品'], ['assessment_rubric','评分标准'],
  ['tutorial_feedback','习题反馈'], ['exam_guidance','考试指导']
];
const yearKinds = new Set(['exam','exam_solution','mock_exam']);

function renderFiles() {
  const list = byId('selection');
  list.replaceChildren();
  chosen.forEach((item, index) => {
    const file = item.file;
    const row = document.createElement('li');
    const title = document.createElement('span');
    title.textContent = file.name + ' · ' + Math.ceil(file.size / 1024) + ' KiB';
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '移除';
    remove.setAttribute('aria-label', '移除 ' + file.name);
    remove.disabled = busy;
    remove.onclick = () => { chosen.splice(index, 1); renderFiles(); };
    const controls = document.createElement('div');
    controls.className = 'material-controls';
    const label = document.createElement('label');
    label.textContent = '资料类别';
    const select = document.createElement('select');
    select.setAttribute('aria-label','资料类别 · ' + file.name);
    for (const [value, text] of kinds) select.add(new Option(text,value));
    select.value = item.kind;
    label.append(select);
    const yearLabel = document.createElement('label');
    yearLabel.textContent = '考年（选填）';
    const year = document.createElement('input');
    year.type = 'number'; year.min = 1900; year.max = 2200;
    year.setAttribute('aria-label','考年 · ' + file.name);
    year.value = item.year;
    yearLabel.append(year);
    const updateYear = () => {
      yearLabel.hidden = !yearKinds.has(item.kind);
      year.disabled = yearLabel.hidden || busy;
    };
    select.onchange = () => {
      item.kind = select.value;
      if (!yearKinds.has(item.kind)) { item.year = ''; year.value = ''; }
      updateYear();
    };
    year.oninput = () => { item.year = year.value; };
    updateYear();
    controls.append(label,yearLabel);
    row.append(title, controls, remove);
    list.append(row);
  });
}

byId('files').onchange = event => {
  for (const file of event.target.files) chosen.push({file, kind:'unknown', year:''});
  event.target.value = '';
  renderFiles();
};
byId('intake').onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  byId('result').hidden = true;
  const status = byId('status');
  if (!chosen.length || chosen.length > 24 || chosen.some(item => !item.file.size)
      || chosen.reduce((total, item) => total + item.file.size, 0) >= 64 * 1024 * 1024) {
    status.textContent = '请选择 1 至 24 个非空课件，并将总量控制在 64 MiB 以内。';
    return;
  }
  const form = new FormData();
  form.set('name', byId('name').value);
  form.set('discipline', byId('discipline').value);
  for (const input of byId('curriculum').querySelectorAll('input[name]')) {
    const value = input.value.trim();
    if (value) form.set(input.name, value);
  }
  chosen.forEach(({file}) => form.append('files',file,file.name));
  form.set('materials',JSON.stringify(chosen.map(({file,kind,year}) =>
    ({filename:file.name,kind,exam_year:year ? Number(year) : null}))));
  busy = true;
  for (const control of byId('intake').elements) control.disabled = true;
  status.textContent = '正在保存课件并提取原页…';
  try {
    const response = await fetch('/import/', {method:'POST', body:form});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '导入失败，请检查所选课件。');
    byId('result-title').textContent = data.name;
    byId('counts').textContent = data.documents + ' 份资料，共 ' + data.pages + ' 页。部分提取 '
      + data.extraction.partial_pages + ' 页，提取失败 ' + data.extraction.failed_pages + ' 页。学术内容待审核。';
    if (data.received_on_utc) {
      byId('counts').textContent += ' 项目收件日 ' + data.received_on_utc + '（UTC）。此日期记录本次收到的文件版本，学校首次发布日期仍待核实。';
    }
    byId('reader').href = data.reader_url;
    byId('study').href = data.study_url;
    byId('result').hidden = false;
    status.textContent = '课程已导入。可收藏下方链接，以后继续学习。';
    chosen.length = 0;
    byId('intake').reset();
    byId('curriculum').open = false;
  } catch (error) {
    status.textContent = error.message || '连接中断，请确认本机服务是否仍在运行。';
  } finally {
    busy = false;
    for (const control of byId('intake').elements) control.disabled = false;
    renderFiles();
  }
};
