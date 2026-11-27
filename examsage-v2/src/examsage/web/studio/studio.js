'use strict';

const $ = id => document.getElementById(id);
const el = (tag, cls, text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = text;
  return element;
};
const paths = {
  bookmark: 'M6 3h12v18l-6-4-6 4z',
  book: 'M3 5c3-1 6-1 9 1 3-2 6-2 9-1v14c-3-1-6-1-9 1-3-2-6-2-9-1z M12 6v14',
  stack: 'm3 8 9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5',
  compose: 'M12 5H6a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-6 M11 14l1-4 7-7 3 3-7 7z',
  chevron: 'm8 10 4 4 4-4',
  upload: 'M12 16V3 M7 8l5-5 5 5 M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4',
  desktop: 'M3 4h18v13H3z M8 21h8 M12 17v4',
  chat: 'M4 4h16v12H9l-5 4z',
  close: 'm6 6 12 12 M18 6 6 18',
  menu: 'M3 6h18 M3 12h18 M3 18h18',
  panel: 'M3 4h18v16H3z M14 4v16',
  up: 'M12 19V5 M5 12l7-7 7 7',
  stop: 'M6 6h12v12H6z',
  attach: 'm8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9',
  left: 'm14 6-6 6 6 6',
  right: 'm10 6 6 6-6 6',
  arrow: 'M5 12h14 M14 7l5 5-5 5',
  doc: 'M5 3h9l5 5v13H5z M14 3v6h5 M8 13h8 M8 16h6',
  spark: 'm12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3z',
  quote: 'M4 7h6v6H7l-2 4 M14 7h6v6h-3l-2 4',
  check: 'm5 12 4 4 10-10'
};
function icon(name) {
  const ns = 'http://www.w3.org/2000/svg',
    svg = document.createElementNS(ns, 'svg'),
    line = document.createElementNS(ns, 'path');
  for (const [k, v] of Object.entries({
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.65',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'aria-hidden': 'true'
  })) svg.setAttribute(k, v);
  line.setAttribute('d', paths[name]);
  svg.append(line);
  return svg;
}
document.querySelectorAll('[data-icon]').forEach(n => n.append(icon(n.dataset.icon)));
function button(label, cls, action, symbol) {
  const b = el('button', cls);
  b.type = 'button';
  if (symbol) b.append(icon(symbol));
  b.append(label);
  b.onclick = action;
  return b;
}
const mark = () => {
  const b = el('span', 'hero-mark');
  b.setAttribute('aria-hidden', 'true');
  b.append(el('i'), el('i'), el('i'));
  return b;
};
const entry = location.hash.slice(1);
if (entry) {
  sessionStorage.setItem('studio-entry', entry);
  history.replaceState(null, '', location.pathname);
}
const capability = entry || sessionStorage.getItem('studio-entry') || '';
$('language').value = studyLanguage;
$('language').onchange = () => {
  if (state && $('question').value) {
    sessionStorage.setItem('studio-language-draft', JSON.stringify([draftKey(), $('question').value]));
  }
  location.assign($('language').value === 'en' ? '/en/' : '/zh/');
};
let state = null,
  pending = false,
  pollTimer,
  readSequence = 0,
  selection = null,
  pageData = null,
  imageMode = false,
  lastTrigger = null;
const drafts = new Map();
let activePoint = null,
  readerPreference = null,
  selectedAnchor = null;
const draftKey = () => JSON.stringify([state?.course_id, state?.session_id]);
const slim = () => matchMedia('(max-width:740px)').matches;
function feedback(message = '') {
  const n = $('notice');
  n.textContent = message;
  n.hidden = !message;
}
async function api(action, fields = {}) {
  const r = await fetch('/api/studio', {
    method: 'POST',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      'X-ExamSage-Local': capability
    },
    body: JSON.stringify({
      action,
      language: studyLanguage,
      revision: state?.revision,
      course_id: state?.course_id,
      session_id: state?.session_id,
      ...fields
    })
  });
  const data = await r.json();
  if (!r.ok) {
    const e = new Error(serviceError(data.error, data.code) || ui('请求失败，请重试。'));
    e.status = r.status;
    e.code = data.code;
    throw e;
  }
  return data;
}
async function report(error) {
  feedback(error.message || ui('连接中断，请重新打开学习窗口。'));
  if (error.status === 409) {
    try {
      await refresh(await api('state'));
      feedback(ui('对话已同步，请核对课程后重试。'));
    } catch {
      feedback(ui('无法同步，请重新打开学习窗口。'));
    }
  }
}
function nav(open) {
  $('app').classList.toggle('nav-open', open);
  $('navShade').hidden = !open;
  if (open) $('closeNav').focus();
}
function reader(open, focus = false) {
  $('app').classList.toggle('reader-off', !open);
  $('app').classList.toggle('reader-open', open && slim());
  $('toggleReader').setAttribute('aria-expanded', String(open));
  if (open && pageData) locateQuote($('readerBody'));
  if (focus) (open ? $('closeReader') : lastTrigger?.isConnected ? lastTrigger : $('toggleReader')).focus();
}
function resizeText() {
  const q = $('question');
  q.style.height = 'auto';
  q.style.height = Math.min(q.scrollHeight, 140) + 'px';
}
function controls() {
  const busy = !!state?.run_id,
    locked = pending || busy,
    course = !!state?.course_id;
  $('courses').disabled = locked || !state?.courses.length;
  $('newChat').disabled = locked || !course;
  $('addCourse').disabled = $('attach').disabled = locked || !state;
  document.querySelectorAll('.session,.welcome button').forEach(b => b.disabled = locked);
  $('openReview').disabled = locked || !course;
  $('sample').disabled = locked || !state;
  $('question').readOnly = pending;
  $('question').disabled = !course;
  $('question').placeholder = course ? ui('问一个课程问题…') : ui('先选择或导入一门课程…');
  const send = $('send');
  send.disabled = pending || !busy && (!course || !$('question').value.trim());
  send.replaceChildren(icon(busy ? 'stop' : 'up'));
  send.title = busy ? ui('停止回答') : ui('发送问题');
  send.setAttribute('aria-label', send.title);
}
function noteDraft() {
  drafts.set(draftKey(), $('question').value);
}
function showCurrentNav() {
  const current = state.courses.find(c => c.slug === state.course_id);
  $('courseName').textContent = current?.name || ui('课程问答');
  const list = $('courses');
  list.replaceChildren();
  if (!current) list.append(new Option(state.courses.length ? ui('选择课程') : ui('暂无课程'), '', true, true));
  state.courses.forEach(c => list.add(new Option(c.name, c.slug, false, c.slug === state.course_id)));
  const sessions = $('sessions');
  sessions.replaceChildren();
  for (const s of state.sessions) {
    const b = button('', 'session', () => change('session', {
      id: s.id
    }), 'chat');
    const t = s.title || ui('未命名对话');
    b.append(el('span', '', t));
    b.title = t;
    b.setAttribute('aria-current', String(s.id === state.session_id));
    sessions.append(b);
  }
  if (!state.sessions.length) sessions.append(el('p', 'empty-nav', ui('提问后，对话会保存在这里。')));
}
function emptyReader(title = ui('选择回答中的要点'), description = ui('点「对照出处」查看相关考题、讲义和原文。')) {
  const box = el('div', 'reader-empty'),
    art = el('span', 'art');
  art.append(icon('book'));
  box.append(art, el('h3', '', title), el('p', '', description));
  $('readerBody').replaceChildren(box);
  $('readerFoot').hidden = true;
}
function clearSource() {
  activePoint = null;
  selectedAnchor = null;
  readSequence++;
  selection = pageData = null;
  imageMode = false;
  lastTrigger = null;
  emptyReader();
}
function rich(parent, value) {
  for (const part of String(value || '').split(/(\*\*[^*\n]+\*\*)/g)) {
    if (part.startsWith('**') && part.endsWith('**')) parent.append(el('strong', '', part.slice(2, -2)));else parent.append(part);
  }
  if (window.renderMathInElement) window.renderMathInElement(parent, {
    delimiters: [{
      left: '$$',
      right: '$$',
      display: true
    }, {
      left: '\\[',
      right: '\\]',
      display: true
    }, {
      left: '\\(',
      right: '\\)',
      display: false
    }, {
      left: '$',
      right: '$',
      display: false
    }],
    throwOnError: false,
    trust: false
  });
}
function welcome() {
  const has = !!state.course_id,
    w = el('div', 'welcome'),
    options = el('div', 'suggests');
  w.append(mark(), el('h1', '', has ? ui('从哪道题开始？') : ui('打开你的第一门课')), el('p', '', has ? ui('边提问，边对照课件。也可以从下面的问题开始。') : ui('用自己的课件提问，或先用两页弹簧课件试一遍。')));
  if (!has) {
    options.append(button(ui('试用弹簧课件'), 'primary', () => change('example'), 'book'), button(ui('导入我的课件'), 'suggest', openImport, 'upload'));
  } else {
    const spring = ['物理示例 · 线性弹簧', 'Physics example · Linear spring'].includes(state.courses.find(c => c.slug === state.course_id)?.name);
    const prompts = spring ? [ui('拉力为 10 N 时，弹簧伸长多少？'), ui('胡克定律有哪些适用条件？')] : [ui('解释课件中的一个核心概念'), ui('用课件里的例子带我做一道题')];
    for (const q of prompts) options.append(button(q, 'suggest', () => {
      $('question').value = q;
      noteDraft();
      resizeText();
      controls();
      $('question').focus();
    }, 'arrow'));
  }
  w.append(options);
  return w;
}
function inlineQuote(ref, data) {
  document.querySelectorAll('.inline-quote').forEach(e => e.remove());
  const raw = data.highlight || data.text;
  if (!raw) return;
  const block = el('blockquote', 'inline-quote'),
    label = el('div', 'quote-label');
  label.append(icon('quote'), data.filename + ui(' · 第 ') + data.cited_page + ui(' 页') + (data.highlight ? ui(' · 引用原句') : ui(' · 页首节选')));
  block.append(label, el('p', '', raw.length > 240 ? raw.slice(0, 240) + '…' : raw));
  (ref.point?.node || ref.article).append(block);
}
function locateQuote(area) {
  const hit = area.querySelector('mark');
  if (hit && area.clientHeight > 0) {
    const delta = hit.getBoundingClientRect().top - area.getBoundingClientRect().top;
    if (delta < 0 || delta > area.clientHeight * 0.65) area.scrollTop = Math.max(0, area.scrollTop + delta - area.clientHeight * 0.3);
  }
}
function paintPage(data) {
  const area = $('readerBody'),
    doc = el('div', 'doc'),
    tile = el('span', 'doc-icon'),
    meta = el('div');
  tile.append(icon('doc'));
  meta.append(el('strong', '', data.filename), el('small', '', data.page !== data.cited_page ? ui('正在浏览相邻页') : selection.item?.relationship === 'related' ? ui('关联资料原页') : ui('本段引用原页')));
  doc.append(tile, meta);
  const paper = el('article', 'paper'),
    bar = el('div', 'paper-bar');
  bar.append(el('span', '', ui('第 ') + data.page + ui(' 页')), el('span', '', imageMode && data.png ? ui('原图') : ui('原文')));
  paper.append(bar);
  if (imageMode && data.png) {
    const img = el('img', 'page-image');
    img.src = 'data:image/png;base64,' + data.png;
    img.alt = data.filename + ui(' 第 ') + data.page + ui(' 页原图');
    paper.append(img);
  } else {
    const text = el('div', 'page-text'),
      raw = data.text || '',
      quote = data.highlight || '',
      i = quote ? raw.indexOf(quote) : -1;
    if (i >= 0) text.append(raw.slice(0, i), el('mark', '', quote), raw.slice(i + quote.length));else text.textContent = raw || ui('这一页没有可提取的文字。');
    paper.append(text);
    if (imageMode && data.image_reason) paper.append(el('p', 'notes', ui('原图暂时无法显示，已保留本页原文。')));
  }
  const actions = el('div', 'reader-actions');
  const savePage = reviewBookmark(data, selection.point?.answer.question || '');
  actions.append(savePage);
  if (data.image_supported) actions.append(button(imageMode ? ui('查看文字') : ui('查看原图'), 'quiet', () => openPage(selection, {
    page: data.page,
    image: !imageMode
  })));
  if (imageMode && data.png) actions.append(button(ui('放大原图'), 'quiet', event => {
    const zoom = paper.classList.toggle('zoom');
    event.currentTarget.textContent = zoom ? ui('适应宽度') : ui('放大原图');
  }));
  if (data.page !== data.cited_page) actions.append(button(ui('返回引用页'), 'quiet', () => openPage(selection, {
    page: data.cited_page
  })));
  if (selection) actions.append(button(ui('定位到回答'), 'quiet', () => {
    const target = selectedAnchor?.isConnected ? selectedAnchor : activePoint?.action || selection.trigger;
    if (slim()) reader(false);
    target?.scrollIntoView({
      block: 'center'
    });
    target?.focus({
      preventScroll: true
    });
  }, 'chat'));
  if (activePoint) {
    const returning = selection;
    const back = button(ui('返回出处对照'), 'map-back', () => returning.fromOverview ? showOverview(returning.point.answer, {
      reveal: true
    }) : selectPoint(activePoint, {
      focusBoard: true
    }), 'left');
    area.replaceChildren(back, doc, paper, actions);
  } else {
    area.replaceChildren(doc, paper, actions);
  }
  area.scrollTop = 0;
  locateQuote(area);
  $('readerFoot').hidden = false;
  $('pageCount').textContent = ui('第 ') + data.page + ' / ' + data.pages + ui(' 页');
  $('prev').disabled = !data.can_previous;
  $('next').disabled = !data.can_next;
}
async function openPage(ref, {
  page,
  image = false,
  reveal = false,
  trigger = null
} = {}) {
  if (!ref) return;
  const seq = ++readSequence,
    changed = selection !== ref;
  if (ref.point) markPoint(ref.point);
  selection = ref;
  pageData = null;
  imageMode = image;
  if (trigger) lastTrigger = trigger;
  if (changed || trigger) selectedAnchor = trigger || ref.trigger;
  document.querySelectorAll('.cite').forEach(b => {
    const selected = b === trigger || b.dataset.key === ref.key && ref.point?.node.contains(b);
    b.classList.toggle('selected', selected);
    b.setAttribute('aria-pressed', String(selected));
  });
  if (changed) document.querySelectorAll('.inline-quote').forEach(e => e.remove());
  emptyReader(ui('正在打开原页…'), '');
  if (reveal) {
    readerPreference = true;
    reader(true, slim());
  }
  try {
    const lookup = ref.item ? {
      action: 'linked_page',
      run_id: ref.point.run,
      paragraph_index: ref.point.index,
      key: ref.item.key
    } : {
      action: 'citation',
      run_id: ref.run,
      evidence_id: ref.id,
      ref_index: ref.index
    };
    const data = await api(lookup.action, {
      ...lookup,
      ...(page == null ? {} : {
        page
      }),
      image
    });
    if (seq !== readSequence) return;
    if (ref.item && data.highlight) {
      const preview = previewQuote(ref.item, ref.point);
      if (preview && data.highlight.includes(preview)) data.highlight = preview;
    }
    pageData = data;
    paintPage(data);
    if (data.page === data.cited_page && ref.item?.relationship !== 'related') inlineQuote(ref, data);
  } catch (e) {
    if (seq === readSequence) {
      emptyReader(ui('未能打开课件'), e.message);
      if (e.status === 409) await report(e);
    }
  }
}
const pointNames = {
  source: ui('原文解读'),
  derivation: ui('推导'),
  assumption: ui('前提'),
  insufficient: ui('证据不足')
};
const materialNames = {
  exam: ui('真题'),
  lecture: ui('讲义'),
  textbook: ui('教材'),
  exam_solution: ui('试卷答案'),
  mock_exam: ui('模拟卷'),
  practice: ui('练习'),
  formula_sheet: ui('公式表'),
  tutorial_feedback: ui('习题反馈'),
  exam_guidance: ui('考试说明'),
  primary_source: ui('原始文献'),
  literary_text: ui('文学文本'),
  assessment_rubric: ui('评分标准'),
  unknown: ui('其他资料')
};
function pointName(point) {
  return ui('要点 ') + (point.index + 1) + ' · ' + (pointNames[point.kind] || ui('回答'));
}
function markPoint(point) {
  if (activePoint !== point) {
    activePoint?.node.classList.remove('is-current');
    activePoint?.action.setAttribute('aria-pressed', 'false');
  }
  activePoint = point;
  point.node.classList.add('is-current');
  point.action.setAttribute('aria-pressed', 'true');
}
function boardTabs(answer, point, overview) {
  const tabs = el('div', 'source-tabs');
  tabs.setAttribute('role', 'group');
  tabs.setAttribute('aria-label', ui('对照范围'));
  const all = button(ui('本题总览'), '', () => showOverview(answer, {
    reveal: true
  }));
  const one = button(ui('要点对照'), '', () => selectPoint(point, {
    reveal: true
  }));
  all.setAttribute('aria-pressed', String(overview));
  one.setAttribute('aria-pressed', String(!overview));
  tabs.append(all, one);
  return tabs;
}
function groupedLocations(answer, rows) {
  const found = new Map();
  for (const row of rows) {
    const point = answer.points[row.paragraph_index];
    if (!point) continue;
    for (const item of row.items) {
      const key = JSON.stringify([item.document_id, item.page, item.question, item.quote, item.basis]);
      if (!found.has(key)) found.set(key, {
        item,
        point,
        where: new Set()
      });
      found.get(key).where.add(point);
    }
  }
  return [...found.values()];
}
async function showOverview(answer, {
  reveal = false,
  autoPoint = null
} = {}) {
  if (!answer.points.length) return;
  const seq = ++readSequence;
  activePoint?.node.classList.remove('is-current');
  activePoint?.action.setAttribute('aria-pressed', 'false');
  activePoint = null;
  selection = pageData = selectedAnchor = null;
  imageMode = false;
  lastTrigger = answer.action;
  document.querySelectorAll('.inline-quote').forEach(q => q.remove());
  document.querySelectorAll('.cite.selected').forEach(b => {
    b.classList.remove('selected');
    b.setAttribute('aria-pressed', 'false');
  });
  if (reveal) {
    readerPreference = true;
    reader(true, slim());
  }
  emptyReader(ui('正在整理本题引用…'), '');
  try {
    const data = await api('answer_sources', {
      run_id: answer.run
    });
    if (seq !== readSequence) return;
    for (const row of data.paragraphs) if (answer.points[row.paragraph_index]) answer.points[row.paragraph_index].directItems = row.items;
    const locations = groupedLocations(answer, data.paragraphs);
    const groups = new Set(locations.map(({
      item
    }) => sourceGroup(item)));
    if (autoPoint && !(groups.has('exam') && groups.has('lecture'))) {
      await selectPoint(autoPoint);
      return;
    }
    const board = el('section', 'answer-overview');
    board.setAttribute('aria-label', ui('本题出处总览'));
    board.append(boardTabs(answer, autoPoint || answer.points[0], true));
    const head = el('div', 'overview-intro');
    head.append(el('h2', '', ui('本题引用')), el('p', '', answer.question));
    board.append(head);
    for (const [key, title, symbol] of [['exam', ui('历年真题'), 'compose'], ['lecture', ui('课程讲义'), 'book'], ['other', ui('其他资料'), 'stack']]) {
      const entries = locations.filter(({
        item
      }) => sourceGroup(item) === key);
      if (!entries.length && key === 'other') continue;
      const section = el('section', 'map-group');
      section.dataset.group = key;
      const heading = el('h3', 'map-heading');
      heading.append(icon(symbol), title, el('small', '', String(entries.length)));
      heading.setAttribute('aria-label', title);
      section.append(heading);
      if (!entries.length) section.append(el('p', 'group-empty', ui('本题回答未直接引用') + title + '。'));
      for (const {
        item,
        point,
        where
      } of entries) {
        const row = el('div', 'overview-entry'),
          card = makeSourceCard(point, item, true);
        const jump = el('div', 'jump-points');
        jump.append(el('span', '', ui('对应回答')));
        for (const p of where.keys()) {
          jump.append(button(ui('要点 ') + (p.index + 1), 'jump-point', () => {
            p.node.scrollIntoView({
              block: 'center'
            });
            selectPoint(p, {
              reveal: true,
              focusBoard: true
            });
          }));
        }
        row.append(card, jump);
        section.append(row);
      }
      board.append(section);
    }
    $('readerBody').replaceChildren(board);
    $('readerBody').scrollTop = 0;
    $('readerFoot').hidden = true;
    if (reveal && !slim()) $('readerBody').focus({
      preventScroll: true
    });
  } catch (e) {
    if (seq !== readSequence) return;
    if (e.status === 409) await report(e);else emptyReader(ui('无法整理本题出处'), e.message);
  }
}
function sourceGroup(item) {
  if (item.kind === 'exam') return 'exam';
  if (['lecture', 'textbook'].includes(item.kind)) return 'lecture';
  return 'other';
}
function previewQuote(item, point) {
  const quote = item.quote.trim();
  if (!quote || item.question || item.relationship !== 'cited') return quote;
  const printed = [...quote.matchAll(/[^\r\n]+/g)];
  let start = 0;
  // Skip copyright furniture only when it occupies the first two printed lines.
  const copyright = printed.slice(0, 2).find(line => line[0].includes('©'));
  if (copyright) {
    const pos = printed.indexOf(copyright) + 1;
    const following = printed[pos];
    const date = following && /^\s*(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(?:19|20)\d{2}\s*$/i.test(following[0]);
    const first = printed[pos + (date ? 1 : 0)];
    if (first) start = first.index;
  }
  for (const hit of point.text.matchAll(/[“"]([^”"\n]{12,180})[”"]/g)) {
    const at = quote.indexOf(hit[1], start);
    if (at >= 0) return quote.slice(at, at + hit[1].length);
  }
  return quote.slice(start, start + 235).trim();
}
async function openPointCitation(point, ref, trigger) {
  const seq = ++readSequence;
  markPoint(point);
  lastTrigger = selectedAnchor = trigger;
  selection = pageData = null;
  readerPreference = true;
  reader(true, slim());
  emptyReader(ui('正在打开原页…'), '');
  try {
    if (!point.directItems) {
      const data = await api('answer_sources', {
        run_id: point.run
      });
      if (seq !== readSequence) return;
      point.directItems = data.paragraphs.find(row => row.paragraph_index === point.index)?.items || [];
    }
    const item = point.directItems.find(it => it.evidence_id === ref.id && it.ref_index === ref.index);
    if (!item) throw new Error(ui('这条引文在当前课程中无法核验。'));
    showItem(point, item, false, trigger);
  } catch (e) {
    if (seq !== readSequence) return;
    if (e.status === 409) await report(e);else emptyReader(ui('未能打开这条引文'), e.message);
  }
}
function sourceLine(item) {
  const meta = [materialNames[item.kind] || ui('其他资料')];
  if (item.exam_year) meta.push(String(item.exam_year));
  if (item.question) meta.push(item.question);
  meta.push(ui('第 ') + item.page + ui(' 页'));
  return meta.join(' · ');
}
function showItem(point, item, fromOverview = false, trigger = point.action) {
  const ref = {
    point,
    item,
    fromOverview,
    article: point.article,
    trigger,
    run: point.run,
    key: JSON.stringify([point.run, point.index, item.key])
  };
  openPage(ref, {
    reveal: true,
    trigger
  });
}
function makeSourceCard(point, item, fromOverview = false) {
  const card = button('', 'source-card', () => showItem(point, item, fromOverview));
  const top = el('span', 'source-card-head');
  const relationship = item.relationship === 'cited' ? ui('回答引用') : ui('关联线索');
  top.append(el('strong', 'source-location', sourceLine(item)), el('span', 'relation-label', relationship));
  const file = el('span', 'source-file');
  file.append(icon('doc'), el('span', '', item.filename), icon('right'));
  card.append(top, file);
  if (item.quote) card.append(el('span', 'card-quote', previewQuote(item, point)));
  if (item.basis && (item.relationship === 'related' || !['本段回答标注的出处', '本段计算引用的原页'].includes(item.basis))) card.append(el('span', 'relation-basis', relationLabel(item.basis)));
  if (!item.quote) card.append(el('span', 'relation-basis', ui('展开原页核查')));
  return card;
}
function renderBoard(point, data, focusBoard) {
  const board = el('section', 'mapping-board');
  board.setAttribute('aria-label', ui('当前要点的出处对照'));
  const context = el('div', 'point-context');
  const line = el('div', 'context-head');
  line.append(el('strong', '', pointName(point)), button(ui('定位到回答'), 'locate-point', () => {
    if (slim()) reader(false);
    point.action.focus({
      preventScroll: true
    });
    point.node.scrollIntoView({
      block: 'center'
    });
  }, 'chat'));
  context.append(line);
  const excerpt = el('div', 'context-text');
  rich(excerpt, point.text);
  context.append(excerpt);
  board.append(boardTabs(point.answer, point, false), context);
  const groups = [['exam', ui('历年真题'), ui('本段暂未定位到对应真题。'), 'compose'], ['lecture', ui('课程讲义'), ui('本段暂未定位到对应讲义或教材。'), 'book'], ['other', ui('其他资料'), '', 'stack']];
  for (const [key, title, empty, symbol] of groups) {
    const items = data.items.filter(item => sourceGroup(item) === key);
    if (!items.length && !empty) continue;
    const section = el('section', 'map-group');
    section.dataset.group = key;
    const heading = el('h3', 'map-heading');
    heading.append(icon(symbol), title, el('small', '', String(items.length)));
    // The heading's accessible name stays stable as the count changes.
    heading.setAttribute('aria-label', title);
    section.append(heading);
    if (!items.length) section.append(el('p', 'group-empty', empty));
    if (items.length) section.append(makeSourceCard(point, items[0]));
    if (items.length > 1) {
      const rest = el('details', 'more-sources');
      rest.open = false;
      rest.append(el('summary', '', ui('其余 ') + (items.length - 1) + ui(' 条出处')));
      for (const item of items.slice(1)) rest.append(makeSourceCard(point, item));
      section.append(rest);
    }
    board.append(section);
  }
  if (data.items.some(item => item.relationship === 'related')) {
    board.append(el('p', 'coverage-note', ui('另列最多 8 条可核对的关联线索。')));
  }
  $('readerBody').replaceChildren(board);
  $('readerBody').scrollTop = 0;
  $('readerFoot').hidden = true;
  if (focusBoard) $('readerBody').focus({
    preventScroll: true
  });
  const direct = data.items.filter(it => it.relationship === 'cited' && it.quote);
  if (direct.length) {
    const item = point.kind === 'derivation' ? direct.at(-1) : direct[0];
    document.querySelectorAll('.inline-quote').forEach(node => node.remove());
    const quote = el('blockquote', 'inline-quote');
    const label = el('div', 'quote-label');
    label.append(icon('quote'), sourceLine(item) + ui(' · 引用原文'));
    quote.append(label, el('p', '', previewQuote(item, point)));
    point.node.append(quote);
  }
}
async function selectPoint(point, {
  reveal = false,
  focusBoard = false
} = {}) {
  if (!point) return;
  const seq = ++readSequence;
  markPoint(point);
  selection = pageData = null;
  imageMode = false;
  selectedAnchor = point.action;
  lastTrigger = point.action;
  document.querySelectorAll('.inline-quote').forEach(node => node.remove());
  document.querySelectorAll('.cite.selected').forEach(b => {
    b.classList.remove('selected');
    b.setAttribute('aria-pressed', 'false');
  });
  if (reveal) {
    readerPreference = true;
    reader(true, slim());
  }
  emptyReader(ui('正在核对本段出处…'), '');
  try {
    const data = await api('paragraph_sources', {
      run_id: point.run,
      paragraph_index: point.index
    });
    if (seq !== readSequence) return;
    point.directItems = data.items.filter(item => item.relationship === 'cited');
    renderBoard(point, data, focusBoard);
  } catch (e) {
    if (seq !== readSequence) return;
    if (e.status === 409) await report(e);else emptyReader(ui('无法读取这段的出处'), e.message);
  }
}
function answerBlock(msg, question) {
  const a = msg.answer || {},
    article = el('article', 'answer'),
    name = el('div', 'byline'),
    av = el('span', 'assistant-mark');
  av.append(icon('spark'));
  name.append(av, ui('押题宝'));
  if (a.subscription_verified) name.append(el('small', '', ui('· ChatGPT 套餐')));
  article.append(name);
  const refs = [],
    points = [],
    used = new Set();
  const view = {
    run: msg.run_id,
    article,
    question,
    points
  };
  if (a.paragraphs?.length) {
    view.action = button(ui('本题出处总览'), 'overview-action', () => showOverview(view, {
      reveal: true
    }), 'stack');
    name.append(view.action);
  }
  for (const ev of a.evidence || []) (ev.refs || []).forEach((r, i) => refs.push({
    article,
    run: msg.run_id,
    id: ev.id,
    index: i,
    doc: r.document_id,
    file: r.filename,
    page: r.page,
    part: ev.refs.length > 1 ? '/' + (i + 1) : '',
    calc: ev.kind === 'calculation',
    key: JSON.stringify([msg.run_id, ev.id, i])
  }));
  function appendLinks(container, items, point) {
    const group = el('div', 'cites');
    const direct = new Set(items.filter(r => !r.calc && r.doc).map(r => JSON.stringify([r.doc, r.page])));
    for (const ref of new Set(items)) {
      used.add(ref);
      if (ref.calc && direct.has(JSON.stringify([ref.doc, ref.page]))) continue;
      const same = items.some(other => other !== ref && other.page === ref.page && (!other.calc || !direct.has(JSON.stringify([other.doc, other.page]))));
      const label = ui('第 ') + ref.page + ui(' 页') + (same ? ' · ' + ref.id + ref.part : '');
      const b = button(label, 'cite', () => {
        if (point) {
          openPointCitation(point, ref, b);
          return;
        }
        clearSource();
        openPage({
          ...ref,
          trigger: b
        }, {
          reveal: true,
          trigger: b
        });
      }, 'book');
      b.dataset.key = ref.key;
      b.title = ref.file + ' · ' + label;
      group.append(b);
    }
    if (group.childElementCount) container.append(group);
  }
  for (const [index, p] of (a.paragraphs || []).entries()) {
    const node = el('section', 'answer-point'),
      body = el('p', 'passage' + (p.kind === 'derivation' ? ' derivation' : ''));
    const items = (p.citations || []).flatMap(k => refs.filter(r => r.id === k));
    const point = {
      article,
      answer: view,
      run: msg.run_id,
      index,
      kind: p.kind,
      text: p.text,
      node,
      refs: items
    };
    const head = el('div', 'point-head');
    const action = button(ui('对照出处'), 'point-action', () => selectPoint(point, {
      reveal: true
    }), 'panel');
    action.setAttribute('aria-label', pointName(point) + ui('，对照出处'));
    action.setAttribute('aria-pressed', 'false');
    action.setAttribute('aria-controls', 'reader');
    point.action = action;
    head.append(el('span', 'point-label', pointName(point)), action);
    rich(body, p.text);
    node.append(head, body);
    appendLinks(node, items, point);
    article.append(node);
    points.push(point);
  }
  if (!a.paragraphs?.length) {
    const body = el('p', 'passage');
    rich(body, msg.content);
    article.append(body);
  }
  for (const row of a.exam_outlook?.ranking || []) article.append(el('p', 'passage', row.topic + ' · ' + row.years.join('、')));
  const extra = refs.filter(r => !used.has(r));
  if (extra.length) {
    const details = el('details', 'notes'),
      title = el('summary', '', points.length ? ui('本轮其他检索资料') : ui('本轮保存的引用'));
    details.append(title);
    appendLinks(details, extra, null);
    article.append(details);
  }
  const diagnostics = {
    'page_visuals_not_verified': ui('试卷原页的图表和版面仍需对照原图。'),
    'visual_layout_not_verified': ui('讲义的图文位置仍需对照原页。'),
    'embedded_equations_may_require_visual_review': ui('讲义里的嵌入公式建议打开原图核对。'),
    'Semantic content not independently reviewed.': ui('课件解析内容尚未经过独立学术核查。'),
    'Embeddings are not configured; indexed keyword and course-alias retrieval is active.': ui('本次使用关键词和课程别名检索。'),
    '请一次指定一个明确的题号或小问编号。': ui('查找试卷题目时，可提供题号或小问编号。'),
    '计算由受限算术工具复算；公式适用性和单位解释仍需核对。': ui('计算工具已复算数值；公式前提和单位仍需核对。')
  };
  const details = el('details', 'notes');
  details.append(el('summary', '', ui('回答说明')));
  for (const n of a.limitations || []) {
    if (Object.hasOwn(diagnostics, n)) details.append(el('p', '', diagnostics[n]));else article.append(el('p', 'academic-note', n));
  }
  if (details.childElementCount > 1) article.append(details);
  return {
    article,
    point: points.findLast(p => p.kind === 'derivation' && p.refs.length) || points.findLast(p => p.refs.length) || points.at(-1),
    fallback: refs.at(-1)
  };
}
function transcript() {
  clearSource();
  const flow = $('flow');
  flow.replaceChildren();
  let latest = null,
    fallback = null,
    question = '';
  if (!state.messages.length) {
    flow.append(welcome());
    return null;
  }
  flow.append(el('h1', 'sr', ui('课程对话')));
  for (const msg of state.messages) {
    if (msg.role === 'user') {
      question = msg.content;
      fallback = null;
      const row = el('div', 'question');
      row.append(el('div', 'bubble', msg.content));
      flow.append(row);
      latest = null;
    } else if (msg.role === 'assistant') {
      const answer = answerBlock(msg, question);
      flow.append(answer.article);
      latest = answer.point;
      fallback = answer.fallback;
    }
  }
  return latest || fallback;
}
function schedulePoll() {
  clearTimeout(pollTimer);
  if (state?.run_id) pollTimer = setTimeout(poll, 1100);
}
async function refresh(next) {
  const oldKey = draftKey(),
    newKey = JSON.stringify([next.course_id, next.session_id]);
  if (state && oldKey !== newKey) noteDraft();
  if (oldKey !== newKey && $('reviewDialog').open) $('reviewDialog').close();
  state = next;
  if (oldKey !== newKey) {
    $('question').value = drafts.get(newKey) || '';
    resizeText();
  }
  showCurrentNav();
  const ref = transcript();
  if (!slim() && readerPreference === null) reader(!!ref);
  controls();
  schedulePoll();
  if (ref?.node && ref.answer.points.length > 1) await showOverview(ref.answer, {
    autoPoint: ref
  });else if (ref?.node) await selectPoint(ref);else if (ref) await openPage(ref);
  const c = $('conversation');
  c.scrollTop = c.scrollHeight;
}
async function change(action, fields = {}) {
  if (pending || !state) return false;
  pending = true;
  controls();
  feedback();
  try {
    const next = await api(action, fields);
    if (action === 'send') {
      drafts.delete(draftKey());
      $('question').value = '';
      resizeText();
    }
    nav(false);
    await refresh(next);
    if (next.run_id) feedback(ui('正在查阅课程资料并生成回答…'));else if (next.run?.error) feedback(serviceError(next.run.error.message, next.run.error.code) || ui('本轮未完成。'));else if (next.run?.status === 'cancelled') feedback(ui('已停止回答。'));
    return true;
  } catch (e) {
    await report(e);
    return false;
  } finally {
    pending = false;
    controls();
    schedulePoll();
  }
}
async function poll() {
  if (pending || !state?.run_id) {
    schedulePoll();
    return;
  }
  const rid = state.run_id,
    rev = state.revision;
  try {
    const next = await api('poll', {
      run_id: rid
    });
    if (state.run_id !== rid || state.revision !== rev) return;
    if (!next.run_id) {
      await refresh(next);
      feedback(serviceError(next.run?.error?.message, next.run?.error?.code) || (next.run?.status === 'cancelled' ? ui('已停止回答。') : ''));
    }
  } catch (e) {
    if (state.run_id === rid && state.revision === rev) await report(e);
  } finally {
    schedulePoll();
  }
}

function samePage(a, b) {
  return a.document_id === b.document_id && a.page === b.page;
}
async function syncChangedReview(error) {
  if (error.code !== 'stale_view') return false;
  if (reviewDialog.open) reviewDialog.close();
  clearSource();
  $('flow').replaceChildren();
  await report(error);
  return true;
}
function reviewBookmark(data, question) {
  const control = button(ui('加入本课复习'), 'quiet bookmark-action', async () => {
    if (saved) return openReview();
    control.disabled = true;
    try {
      await api('review_save', {document_id: data.document_id, page: data.page, version: null,
        status: 'review', cue: question.trim().slice(0, 10000)});
      showSaved();
    } catch (error) {
      if (control.isConnected && !await syncChangedReview(error)) {
        feedback(error.message);
        if (error.code === 'review_conflict') await sync();
      }
    } finally {
      control.disabled = false;
    }
  }, 'bookmark');
  let saved = false;
  function showSaved() {
    saved = true;
    control.replaceChildren(icon('check'), ui('已加入复习'));
    control.title = ui('打开本课复习');
  }
  async function sync() {
    try {
      const rows = await api('review_list');
      if (rows.items.some(item => samePage(item, data))) showSaved();
    } catch (error) {
      if (control.isConnected && !await syncChangedReview(error)) feedback(error.message);
    }
  }
  sync();
  return control;
}

const reviewDialog = $('reviewDialog'), reviewBody = $('reviewBody');
let reviewSerial = 0;
function reviewNotice(message = '') {
  $('reviewFeedback').textContent = message;
  $('reviewFeedback').hidden = !message;
}
function reviewHere(serial) {
  return reviewDialog.open && serial === reviewSerial;
}
function showReviewList(rows, mastered = false, focus = false) {
  ++reviewSerial;
  const tabs = el('div', 'review-tabs'), list = el('div', 'review-list');
  const done = rows.filter(row => row.status === 'confident').length;
  for (const [value,label,count] of [[false,ui('待复习'),rows.length-done],[true,ui('已掌握'),done]]) {
    const tab = button(label + ' ' + count, 'review-tab', () => {
      reviewNotice();
      showReviewList(rows, value, true);
    });
    tab.setAttribute('aria-pressed', String(value === mastered));
    tabs.append(tab);
  }
  const items = rows.filter(row => (row.status === 'confident') === mastered);
  for (const item of items) {
    const row = button('', 'review-row', () => practiseReview(item, rows, mastered));
    const words = el('span', 'review-row-text');
    words.append(el('strong', '', item.cue || ui('回忆这一页的关键内容')),
      el('small', '', item.filename + ui(' · 第 ') + item.page + ui(' 页')));
    row.append(words, icon('right'));
    list.append(row);
  }
  if (!items.length) {
    const blank = el('div', 'review-empty'), tile = el('span', 'review-tile');
    tile.append(icon(mastered ? 'check' : 'bookmark'));
    blank.append(tile, el('h3', '', mastered ? ui('还没有标记为已掌握的原页') : ui('还没有待复习的原页')),
      el('p', '', mastered ? ui('核对原页后，可以自己标记掌握程度。') :
        (done ? ui('已练过的页面可以在「已掌握」中再次打开。') : ui('从回答里打开一页考卷或讲义，点「加入本课复习」。'))));
    list.append(blank);
  }
  reviewBody.replaceChildren(tabs, list);
  if (focus) tabs.querySelector('[aria-pressed="true"]').focus();
}
async function openReview() {
  nav(false);
  const serial = ++reviewSerial;
  $('reviewCourse').textContent = $('courseName').textContent;
  reviewNotice();
  reviewBody.replaceChildren(el('p','review-empty',ui('正在读取复习记录…')));
  if (!reviewDialog.open) reviewDialog.showModal();
  try {
    const {items} = await api('review_list');
    if (reviewHere(serial)) showReviewList(items);
  } catch (error) {
    if (reviewHere(serial) && !await syncChangedReview(error)) {
      reviewBody.replaceChildren(button(ui('重新读取'), 'quiet', openReview));
      reviewNotice(error.message);
    }
  }
}
function practiseReview(item, rows, mastered) {
  const serial = ++reviewSerial;
  reviewNotice();
  const back = button(ui('复习列表'),'quiet review-back',() => {
    reviewNotice();
    showReviewList(rows, mastered, true);
  }, 'left');
  const card = el('section', 'recall-card');
  const title = el('h3', '', item.cue || ui('不看原页，你能回忆出哪些要点？'));
  const file = el('p', 'review-file', item.filename + ui(' · 第 ') + item.page + ui(' 页'));
  const label = el('label', 'review-label', ui('我的回忆')), draft = el('textarea', 'recall-draft');
  draft.rows = 3;
  draft.placeholder = ui('可以写下解题思路，也可以先口头回答。');
  label.append(draft);
  const reveal = button(ui('揭开原页核对'),'primary',async () => {
    reveal.disabled = true;
    try {
      const source = await api('review_page',{document_id:item.document_id,page:item.page,image:true});
      if (!reviewHere(serial)) return;
      const original = el('section','review-original');
      const head = el('div','review-source-title');
      head.append(icon('doc'),el('strong','',ui('原页核对')),el('span','',ui('第 ')+source.page+ui(' 页')));
      original.append(head);
      if (source.text) original.append(el('div','review-source-text',source.text));
      if (source.png) {
        const details = el('details','review-facsimile'), img = el('img');
        img.alt = source.filename + ui(' 第 ') + source.page + ui(' 页原图');
        img.src = 'data:image/png;base64,' + source.png;
        details.append(el('summary','',ui('查看原图')),img);
        details.open = !source.text;
        original.append(details);
      }
      if (!source.text && !source.png) original.append(el('p','',ui('本页暂无可显示的正文或原图。')));
      const cueLabel = el('label','review-label',ui('下次复习的问题'));
      const cue = el('textarea','review-cue');
      cue.rows = 2;
      cue.maxLength = 10000;
      cue.value = item.cue || '';
      cue.placeholder = ui('写一个下次能考考自己的问题');
      cueLabel.append(cue);
      const controls = el('div','review-grade');
      const retry = button(ui('还要练'),'quiet',() => rate('review'));
      const confident = button(ui('已掌握这页'),'primary',() => rate('confident'),'check');
      async function rate(status) {
        retry.disabled = confident.disabled = true;
        try {
          const saved = await api('review_save',{document_id:item.document_id,page:item.page,
            version:item.version,cue:cue.value.trim(),status});
          if (!reviewHere(serial)) return;
          showReviewList(rows.map(row => samePage(row,saved) ? saved : row),mastered,true);
          reviewNotice(status === 'confident' ? ui('这页已标记为掌握。') : ui('已保存在待复习中。'));
        } catch (error) {
          if (reviewHere(serial) && !await syncChangedReview(error)) {
            reviewNotice(error.message);
            if (error.status === 409 && !controls.querySelector('.reload-review'))
              controls.append(button(ui('读取最新记录'),'quiet reload-review',openReview));
          }
        } finally {
          retry.disabled = confident.disabled = false;
        }
      }
      controls.append(retry,confident);
      reveal.replaceWith(original,cueLabel,controls);
      head.tabIndex = -1;
      head.focus({preventScroll:true});
      original.scrollIntoView({block:'nearest'});
    } catch (error) {
      if (reviewHere(serial) && !await syncChangedReview(error)) reviewNotice(error.message);
      reveal.disabled = false;
    }
  },'book');
  card.append(file,title,label,reveal);
  reviewBody.replaceChildren(back,card);
  draft.focus();
}
$('openReview').onclick = openReview;
$('closeReview').onclick = () => reviewDialog.close();
reviewDialog.addEventListener('close', () => {
  ++reviewSerial;
  reviewBody.replaceChildren();
  reviewNotice();
  if (slim()) $('menu').focus();
});

function openImport() {
  if (pending || state?.run_id) return;
  nav(false);
  $('importError').textContent = '';
  $('importDialog').showModal();
}
function fileRows() {
  const area = $('fileRoles');
  area.replaceChildren();
  for (const f of $('files').files) {
    const row = el('div', 'file-row'),
      role = el('select'),
      year = el('input');
    role.setAttribute('aria-label', f.name + ui(' 类别'));
    for (const [k, v] of Object.entries({
      lecture: ui('课件'),
      exam: ui('真题'),
      exam_solution: ui('答案'),
      mock_exam: ui('模拟卷'),
      unknown: ui('其他')
    })) role.add(new Option(v, k));
    year.disabled = true;
    role.onchange = () => {
      year.disabled = !['exam', 'exam_solution', 'mock_exam'].includes(role.value);
      if (year.disabled) year.value = '';
    };
    year.type = 'number';
    year.placeholder = ui('年份');
    year.min = 1900;
    year.max = 2200;
    year.setAttribute('aria-label', f.name + ui(' 年份（可选）'));
    row.append(el('span', '', f.name), role, year);
    area.append(row);
  }
}
function encode(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result.split(',')[1]);
    r.onerror = () => reject(new Error(ui('无法读取所选文件。')));
    r.readAsDataURL(file);
  });
}
async function submitImport(event) {
  event.preventDefault();
  if ($('confirmImport').disabled) return;
  const files = [...$('files').files],
    rows = [...$('fileRoles').children];
  $('confirmImport').disabled = true;
  try {
    if (files.length > 24 || files.reduce((n, f) => n + f.size, 0) > 64 * 1024 * 1024) throw new Error(ui('每次最多 24 份资料，共 64 MiB。'));
    const data = [];
    for (const [i, f] of files.entries()) {
      const year = rows[i].querySelector('input').value;
      data.push({
        name: f.name,
        data: await encode(f),
        role: rows[i].querySelector('select').value,
        ...(year ? {
          exam_year: Number(year)
        } : {})
      });
    }
    const ok = await change('import', {
      name: $('importName').value.trim(),
      subject: $('subject').value.trim(),
      files: data
    });
    if (ok) {
      $('importDialog').close();
      $('importForm').reset();
      fileRows();
      $('question').focus();
    } else $('importError').textContent = $('notice').textContent;
  } catch (e) {
    $('importError').textContent = e.message;
  } finally {
    $('confirmImport').disabled = false;
  }
}
$('menu').onclick = () => nav(true);
$('closeNav').onclick = $('navShade').onclick = () => {
  nav(false);
  $('menu').focus();
};
$('toggleReader').onclick = () => {
  lastTrigger = $('toggleReader');
  readerPreference = slim() ? !$('app').classList.contains('reader-open') : $('app').classList.contains('reader-off');
  reader(readerPreference, true);
};
$('closeReader').onclick = () => {
  readerPreference = false;
  reader(false, true);
};
$('sample').onclick = () => change('example');
$('courses').onchange = e => change('course', {
  id: e.target.value
});
$('newChat').onclick = async () => {
  if (await change('session', {
    id: null
  })) $('question').focus();
};
$('prev').onclick = () => pageData && openPage(selection, {
  page: pageData.page - 1,
  image: imageMode
});
$('next').onclick = () => pageData && openPage(selection, {
  page: pageData.page + 1,
  image: imageMode
});
$('question').oninput = () => {
  noteDraft();
  resizeText();
  controls();
};
$('composer').onsubmit = e => {
  e.preventDefault();
  if ($('send').disabled) return;
  state.run_id ? change('stop', {
    run_id: state.run_id
  }) : change('send', {
    question: $('question').value.trim()
  });
};
$('question').onkeydown = e => {
  if (!e.isComposing && e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !state?.run_id) {
    e.preventDefault();
    $('composer').requestSubmit();
  }
};
$('addCourse').onclick = $('attach').onclick = openImport;
$('cancelImport').onclick = () => $('importDialog').close();
$('files').onchange = fileRows;
$('importForm').onsubmit = submitImport;
document.addEventListener('keydown', e => {
  if (e.isComposing || $('importDialog').open || $('reviewDialog').open) return;
  if (e.key === 'Escape') {
    if ($('app').classList.contains('nav-open')) {
      nav(false);
      $('menu').focus();
    } else if ($('app').classList.contains('reader-open')) reader(false, true);
  }
  if (e.altKey && e.key.toLowerCase() === 'r') {
    e.preventDefault();
    reader(true, true);
  }
  if (e.altKey && e.key.toLowerCase() === 'q') {
    e.preventDefault();
    if (slim()) reader(false);
    $('question').focus();
  }
});
const narrow = matchMedia('(max-width:740px)');
narrow.addEventListener('change', () => reader(!narrow.matches));
reader(!slim());
(async () => {
  try {
    await refresh(await api('state'));
    const savedDraft = sessionStorage.getItem('studio-language-draft');
    sessionStorage.removeItem('studio-language-draft');
    if (savedDraft) {
      const [key, text] = JSON.parse(savedDraft);
      if (key === draftKey() && typeof text === 'string') {
        $('question').value = text;
        noteDraft();
        resizeText();
        controls();
      }
    }
    setInterval(() => api('heartbeat').catch(() => {}), 45000);
  } catch (e) {
    await report(e);
    emptyReader(ui('等待连接'), ui('请从学生包里的「开始学习」打开。'));
  }
})();
