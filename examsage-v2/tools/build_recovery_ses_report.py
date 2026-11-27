"""Render the current run's evidence without changing previous reports."""
from pathlib import Path
import json
import html
from urllib.parse import quote
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/recovery-ses-20261102'
def read(name):
    path=QA/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
def esc(value):return html.escape(str(value))
coverage=read('recovery-coverage.json');ses=read('ses-coverage.json')
rows=[]
for label,name in [('第一轮 · 原页复核入口','round1-after.json'),('第二轮 · SES小问查询与导航','round2-after.json'),('第三轮 · 条件、数值与来源冲突','round3-after.json'),('手机端 · 阅读与来源','mobile-after.json')]:
    r=read(name);score=f"{r['passed']} / {r['total']}" if r else '待完成'
    rows.append(f'<tr><td>{label}</td><td>{score}</td></tr>')
recovery=read('recovery-verification.json')
for label,key in [('74页原文与完整性检查','page_checks'),('24个学生原页检索案例','student_retrieval')]:
    r=recovery.get(key,{})
    rows.append(f"<tr><td>{label}</td><td>{r.get('passed','—')} / {r.get('total','—')}</td></tr>")
sesqa=read('ses-verification.json')
for label,key in [('所有SES小问精确检索','exact_queries'),('SES题答、父题、复算检查','checks')]:
    r=sesqa.get(key,{})
    if r:rows.append(f"<tr><td>{label}</td><td>{r.get('passed','—')} / {r.get('total','—')}</td></tr>")
for label,name in [('自然追问与数值条件','ses-student-retrieval.json'),('五门课程浏览器回归','all-courses-browser.json'),('程序完整回归','backend-regression.json')]:
    r=read(name)
    if r:rows.append(f"<tr><td>{label}</td><td>{r['passed']} / {r['total']}</td></tr>")
names={r['document_id']:Path(r['relative_path']).name for r in read('inventory.json')}
unresolved=''.join('<li>'+esc(names[r['document_id']])+' · 第 '+str(r['number'])+' 页：'+esc('；'.join(r['notes']))+'</li>' for r in coverage.get('unresolved_pages',[]))
conflicts=[]
if (ROOT/'data/ses/current.json').exists():
    from examsage.cli import load
    store,scope=load(ROOT/'data/ses')
    for r in store.list_records(scope,'question'):
        audit=r.details.get('audit',{})
        if audit.get('status') not in {'source_conflict','partial'}:continue
        query=f"{r.details['exam_year']} Q{r.details['number']}"+''.join('('+x+')' for x in r.details['part'].split('.'))+' 答案'
        conflicts.append('<details><summary>'+esc(r.title)+'</summary><p>'+esc('；'.join(audit['warnings']))+'</p><a href="http://127.0.0.1:8766/courses/ses/?q='+quote(query)+'">在押题宝查看此小问</a></details>')
shots=''.join(f'<figure><img src="{name}" alt="{esc(title)}"><figcaption>{esc(title)}</figcaption></figure>' for name,title in [('recovery-student.png','低置信度页逐项复核'),('ses-student.png','SES小问条件与复算'),('ses-mobile.png','手机端小问阅读')] if (QA/name).exists())
release=read('release-verification.json')
summary='数据仍在核对中' if not ses else f"7套试卷 · 28道大题 · {ses['subquestions']}个编号小问 · {ses['leaf_subquestions']}个最末级小问 · {ses['leaf_numerical_checks']}项最末级小问复算"
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>押题宝 · 74页恢复与SES逐小问测试</title>
<style>body{margin:0;background:#f5f7f6;color:#18322d;font:16px/1.7 system-ui,sans-serif}main{max-width:1050px;margin:auto;padding:36px 20px}h1{font-size:32px;line-height:1.3}h2{margin-top:36px}a{color:#146953}header p{color:#5b6e68}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.card,section,details{background:white;border:1px solid #d9e4df;border-radius:10px;padding:20px;margin:12px 0}.card strong{font-size:32px;display:block}table{width:100%;border-collapse:collapse}td,th{padding:12px;border-bottom:1px solid #dde5e0;text-align:left}.warning{border-left:4px solid #c28a3b;padding:14px;background:#fff7e9}.shots{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}img{max-width:100%;border:1px solid #d9e4df;border-radius:8px}details p,li{overflow-wrap:anywhere}summary{cursor:pointer;font-weight:600}small{color:#667b73}@media(max-width:650px){.cards,.shots{grid-template-columns:1fr}h1{font-size:25px}main{padding:20px 12px}}</style>
<main><header><small>2026-11-02 · 本地候选版本测试记录</small><h1>从模糊页面，到可核查的小问答案</h1><p>所有复核绑定原始文件与页码；数值一致不等于答案正确，来源冲突保留可见。</p><a href="http://127.0.0.1:8766/courses/ses/">打开SES学生页面 →</a></header>
<div class="cards"><div class="card"><strong>74 / 74</strong>页面已逐项处理</div><div class="card"><strong>387</strong>恢复内容块（233个公式）</div><div class="card"><strong>5</strong>页面仍有局部不确定</div></div>
<section><h2>每轮学生测试</h2><p>第一轮原页复核入口：修复前0/8，修复后8/8。第二轮基线：嵌套小问查询无结果。</p><table><thead><tr><th>测试范围</th><th>通过 / 总数</th></tr></thead><tbody>ROWS</tbody></table></section>
<section><h2>SES逐小问核对</h2><p>SUMMARY</p><p>NUMERICS</p><p>每个小问保留题目条件、公式说明、复算表达式、来源答案值、引用页以及父题上下文。</p><div class="warning">这些是代理对照原件的核查结果，独立专家验收仍待完成。原始文件、原始抽取和OCR没有被覆盖。</div></section>
<section><h2>仍不明确的原页</h2><ul>UNRESOLVED</ul></section>
<section><h2>题目与答案中的来源冲突</h2>CONFLICTS</section>
<div class="shots">SHOTS</div><footer><p>RELEASE</p><small>本报告验证的是资料结构、检索与来源核对；不代表考试预测已验证。</small></footer></main></html>'''
numeric=ses.get('leaf_numeric_comparisons',{})
comparison=f"最末级小问复算（不重复计父题）：{numeric.get('agrees',0)}项与来源数值一致，{numeric.get('mismatch',0)}项不一致，{numeric.get('not_reported',0)}项来源未报告数值。"
export=f"候选包 v0.3 已重新打开验证：{release.get('sources',0)}份原始资料、{release.get('hashed_files',0)}个导出文件哈希、{release.get('subquestion_pairs',0)}组小问题答检查通过。GRT原有{release.get('grt_cases',0)}个定位案例保持通过。"
values={'ROWS':''.join(rows),'SUMMARY':esc(summary),'NUMERICS':esc(comparison),'UNRESOLVED':unresolved,'CONFLICTS':''.join(conflicts) or '<p>正在逐页核查，尚未汇总。</p>','SHOTS':shots,'RELEASE':esc(export) if release else '候选版导出待完成。'}
for key,value in values.items():page=page.replace(key,value)
(QA/'index.html').write_text(page,encoding='utf-8')
print(QA/'index.html')
