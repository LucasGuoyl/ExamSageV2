"""Build the reviewable v0.4 experiment report from this run's saved evidence."""
from pathlib import Path
from collections import Counter
from urllib.parse import quote
import json,html
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/adjudication-20261102'
LABELS={'system_error':'系统错误','source_error':'原始资料错误','both':'两者都有','insufficient_evidence':'证据仍不足'}
def read(p):return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
def esc(x):
    text=str(x).replace('逐页目视原PDF渲染；按原始参数独立复算；完整替换本叶audit，保留明确的原文差异与未决条件。','已对照原页，按原始参数重新计算；保留原文差异和仍未确定的条件。').replace('替代模型检查source_value改为空','不再把替代模型的结果与官方读数直接比较').replace('本项audit保留partial','本项仍有未确定内容')
    return html.escape(text.replace('numerical_checks','数值核对').replace('source_value','来源数值').replace('mismatch','不一致'))
def findings(v):
    out='<p>'+esc(v['summary'])+'</p>'
    for key,label in [('system_findings','系统问题'),('source_findings','来源问题'),('actions','本次处理'),('remaining','仍有限制')]:
        if v[key]:out+='<h4>'+label+'</h4><ul>'+''.join('<li>'+esc(x)+'</li>' for x in v[key])+'</ul>'
    out+='<details><summary>原页证据</summary>'+''.join('<p>'+esc(e['observation'])+'<small> · '+esc(e['document_id'])+' / 第 '+str(e['page'])+' 页</small></p>' for e in v['evidence'])+'</details>'
    return out
def main():
    b=read(QA/'baseline.json');frozen={r['id']:r for r in b['conflicts']+b['gaps']};overlays=[]
    for name in ['2019_2020','2021_2023','2024_2025','gaps']:
        overlays+=read(ROOT/'courses'/f'adjudication_{name}.json') or []
    conflict_ids={r['id'] for r in b['conflicts']};conflicts=[e for e in overlays if e['record_id'] in conflict_ids]
    counts=Counter(e['adjudication']['category'] for e in conflicts)
    cards=''.join('<div class="stat"><strong>'+str(counts[k])+'</strong>'+v+'</div>' for k,v in LABELS.items())
    rows=''
    for label,file in [('第一轮 · 5页与3个缺口','round1-after.json'),('第二轮 · 46个争议小问','round2-after.json'),('第三轮 · 浏览器与手机端','round3-after.json')]:
        result=read(QA/file);rows+='<tr><td>'+label+'</td><td>'+ (f"{result['passed']} / {result['total']}" if result else '待执行')+'</td></tr>'
    for label,file,key in [('SES全部编号小问检索','ses-verification.json','exact_queries'),('题答、父题与复算完整性','ses-verification.json','checks')]:
        result=read(QA/file).get(key,{});rows+='<tr><td>'+label+'</td><td>'+(f"{result['passed']} / {result['total']}" if result else '待执行')+'</td></tr>'
    plain=read(QA/'readability-after.json').get('after',{})
    if plain:rows+=f"<tr><td>第三轮补测 · 学生可读说明</td><td>{plain['passed']} / {plain['total']}</td></tr>"
    records='';gaps=''
    for entry in overlays:
        original=frozen[entry['record_id']];d=original['details'];v=entry['adjudication']
        query=f"{d['exam_year']} Q{d['number']}"+''.join('('+p+')' for p in d['part'].split('.'))+' 答案'
        body='<details class="case" data-category="'+v['category']+'"><summary><span>'+esc(query[:-3])+'</span><b>'+LABELS[v['category']]+'</b></summary>'+findings(v)
        body+='<details><summary>上一版为何标记</summary><ul>'+''.join('<li>'+esc(x)+'</li>' for x in original['details']['audit']['warnings'])+'</ul></details>'
        body+='<p><a href="http://127.0.0.1:8766/courses/ses/?q='+quote(query)+'">打开题干、复算与原页 →</a></p></details>'
        if entry['record_id'] in conflict_ids:records+=body
        else:gaps+=body
    pages=''
    for item in read(ROOT/'courses/adjudication_pages.json'):
        original=next(p for p in b['pages'] if p['document_id']==item['document_id'] and p['number']==item['number'])
        pages+='<details><summary>'+esc(Path(original['relative_path']).name)+' · 第 '+str(item['number'])+' 页</summary>'+findings(item['recovery']['adjudication'])+'</details>'
    verification=read(QA/'release-verification.json');release='候选包验证待完成。'
    if verification:release=f"v0.4候选包已重新打开：{verification['sources']}份原始资料、{verification['hashed_files']}项导出文件哈希、{verification['subquestion_pairs']}组小问题答验证通过。"
    tests=read(QA/'backend-regression.json');testnote=f"程序回归：{tests['passed']} / {tests['total']}。" if tests else ''
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>押题宝 · 来源冲突复核实验</title><style>
body{margin:0;background:#f3f5f2;color:#172f28;font:16px/1.7 system-ui,sans-serif}main{max-width:1120px;margin:auto;padding:40px 22px}h1{font-size:36px;line-height:1.3;margin:10px 0}h2{margin-top:10px}h4{margin-bottom:4px}p{margin:10px 0}a{color:#086951}header{padding:15px 0 26px}.eyebrow,small{color:#64776d}small{display:block;overflow-wrap:anywhere}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.stat{background:#153e32;color:#f4fbf6;border-radius:12px;padding:20px}.stat strong{display:block;font-size:34px}section{background:white;border:1px solid #dae3dc;border-radius:14px;padding:24px;margin:22px 0}details{border:1px solid #dce5df;padding:15px;border-radius:8px;margin:10px 0}details details{background:#f7f9f7}summary{cursor:pointer;font-weight:600}summary b{font-size:13px;margin-left:14px;padding:4px 8px;background:#eef2eb;border-radius:5px}ul{padding-left:24px}li{margin:7px 0;overflow-wrap:anywhere}.note{border-left:4px solid #c08a3f;background:#fff7e8;padding:15px}.filter{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}button{padding:9px 14px;border:1px solid #a9c1b4;border-radius:6px;color:#174b38;background:white;cursor:pointer}button.active{background:#174b38;color:white}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #dce5df}.shots{display:grid;grid-template-columns:1fr 1fr;gap:15px}img{max-width:100%;border:1px solid #ccc;border-radius:8px}[hidden]{display:none!important}@media(max-width:640px){main{padding:20px 12px}h1{font-size:28px}.stats{grid-template-columns:1fr 1fr}.shots{grid-template-columns:1fr}section{padding:16px}summary b{display:block;width:fit-content;margin:8px 0}}
</style><main><header><div class="eyebrow">押题宝 v0.4 · 2026-11-02 · 本地实验</div><h1>哪里是系统错，哪里是资料错？</h1><p>46个既有冲突逐项重审，保留原始资料、上一版判断与当前证据。</p><a href="http://127.0.0.1:8766/courses/ses/">进入SES学生测试 →</a></header><div class="stats">CARDS</div>
<section><h2>每轮学生测试</h2><p>第一轮首次7/8：校正式缺少 X₂₃ 与 0.1 的对应步骤，补充后8/8。</p><table><thead><tr><th>情境</th><th>通过 / 总数</th></tr></thead><tbody>ROWS</tbody></table><p>TESTNOTE</p><p class="note">通过表示检索、证据显示和所列校验满足预期，不表示不确定原文已经恢复，也不表示答案经过教师验收。</p></section>
<section><h2>5页不确定内容</h2><p>4页的教学含义可明确说明；地温例题的指数与结果仍无法唯一纠正。5页的字面不确定均保留。</p>PAGES</section>
<section><h2>3个小问来源缺口</h2><p>补充了教学解释，官方原文缺口关闭0项。后期课件的假设不能冒充往年考试给定量。</p>GAPS</section>
<section><h2>46项冲突逐项结论</h2><p id="shown">已核查 REVIEWED / 46 项。</p><div class="filter"><button class="active" data-filter="all">全部</button>FILTERS</div><div id="cases">CASES</div></section>
SHOTS<footer><p>RELEASE</p><p>原件与历史版本保持可追溯；独立专家验收待完成。本实验不验证下一年考试预测。</p></footer></main>
<script>document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));let n=0;document.querySelectorAll('#cases .case').forEach(x=>{x.hidden=b.dataset.filter!=='all'&&x.dataset.category!==b.dataset.filter;if(!x.hidden)n++});document.getElementById('shown').textContent='显示 '+n+' 项 / 本轮固定46项';});</script></html>'''
    shots=''.join('<img src="'+name+'" alt="'+label+'">' for name,label in [('ses-review.png','题答来源复核界面'),('ses-mobile.png','手机端题答核对')] if (QA/name).exists())
    for key,value in {'CARDS':cards,'ROWS':rows,'PAGES':pages,'GAPS':gaps,'CASES':records,'REVIEWED':str(len(conflicts)),
                      'FILTERS':''.join('<button data-filter="'+k+'">'+v+'</button>' for k,v in LABELS.items()),
                      'RELEASE':esc(release),'TESTNOTE':esc(testnote),'SHOTS':'<section><h2>学生界面</h2><div class="shots">'+shots+'</div></section>' if shots else ''}.items():page=page.replace(key,value)
    (QA/'index.html').write_text(page,encoding='utf-8')
    print({'conflicts':len(conflicts),'categories':dict(counts)})
if __name__=='__main__':main()
