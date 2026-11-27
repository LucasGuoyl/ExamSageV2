from pathlib import Path
from html import escape
import json
import shutil
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/low-text-20261028';OUT=ROOT/'data/qa/visual-test-20261028'
def read(name):return json.loads((QA/name).read_text(encoding='utf-8-sig'))
coverage=read('coverage.json');release=read('release-verification.json')
if not (OUT/'library-v0.1.html').exists():shutil.copyfile(OUT/'index.html',OUT/'library-v0.1.html')
names={'geodynamics':'地球动力学','planetary_science':'行星科学','sea_level':'海平面','ses':'可持续电力系统'}
rows=''.join(f'<tr><td>{names[k]}</td><td>{v["pages"]}/{v["pages"]}</td><td>{v["categories"].get("text",0)}</td><td>{v["categories"].get("diagram",0)}</td><td>{v["categories"].get("mixed",0)}</td><td>{v["ocr_indexed"]}</td></tr>' for k,v in coverage['courses'].items())
rounds=[('01','低文本页能否找到与读懂','0/6 → 6/6','补充导读、原文与 OCR 分开；赤道虹吸与锶同位素图像页可检索。','round1-after.json'),
('02','推导与题答能否回到正确来源','3/13 → 13/13','12 步推导跨两份课件。SES 同年同号题答导航，来源冲突直接展示。','round2-after.json'),
('03','换成自然提问与学年写法','29/29 最终通过','首测 11/28。修复中文长句、学年误读、完整推导遗漏；3 个未拆分小问预期改为明确拒绝，另加 1 条父题冲突检查。','round3-after.json'),
('04','模拟多名学生同时打开原页','256/256','首测发现 PDF 并发渲染导致服务退出。加互斥与原子写入，同样 6 路并发重测通过。涵盖 208 页、28 对题答、20 个旧学年查询。','round4-after.json'),
('05','小屏与既有课程回归','11 + 68 + 110 全部通过','11 项移动端、68 项旧交互、110 次代表页预览。旧脚本改为点击可见链接；GRT 40 条来源定位保持通过。','round5-mobile.json')]
cards=''
for number,title,score,note,file in rounds:
    shutil.copyfile(QA/file,OUT/'lowtext'/file)
    cards+=f'<article class="round"><span class="num">{number}</span><div><h3>{title}</h3><b>{score}</b><p>{note}</p><a href="lowtext/{file}">查看本轮原始结果 ↗</a></div></article>'
shots=[('ses-pair.png','SES：原题与答案的条件冲突同时可见'),('geodynamics.png','地球动力学：完整推导与每步原页引用'),('sea-level-supplement.png','低文本页：图像导读、OCR、原始抽取分别查看'),('ses-mobile.png','320px：题答警示与来源按钮'),('geodynamics-mobile.png','320px：推导公式与跨文档步骤')]
gallery=''.join(f'<figure class="{"phone" if "mobile" in file else ""}"><a href="lowtext/{file}"><img src="lowtext/{file}" alt="{title}" loading="lazy"></a><figcaption>{title}</figcaption></figure>' for file,title in shots)
html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>押题宝 · 208页补充与课程试点实验</title><link rel="icon" href="data:,"><style>
:root{--ink:#173a35;--muted:#627773;--green:#14795c;--line:#d8e4dc;--bg:#f5f7f1}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif}a{color:var(--green)}main{max-width:1160px;margin:auto;padding:40px 28px 70px}.top{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.logo{font-weight:750;font-size:22px}.tag{font:12px monospace;color:var(--green)}h1{font-size:clamp(32px,5vw,56px);line-height:1.2;letter-spacing:-1.3px;margin:35px 0 18px}h2{font-size:26px;margin:45px 0 18px}h3{font-size:18px;margin:0 0 7px}p{margin:8px 0 15px}.lead{max-width:860px;font-size:19px;color:var(--muted)}.actions{display:flex;gap:12px;flex-wrap:wrap;margin:25px 0}.button{padding:10px 19px;border:1px solid var(--green);border-radius:9px;text-decoration:none}.button.primary{background:var(--green);color:white}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:30px 0}.metric,.panel{background:white;padding:23px;border:1px solid var(--line);border-radius:14px}.metric b{display:block;font-size:38px;line-height:1.2}.metric span{font-size:13px;color:var(--muted)}.notice{background:#eee8d8;border-left:4px solid #aa8132;padding:18px 22px;border-radius:4px}.rounds{display:grid;grid-template-columns:1fr 1fr;gap:15px}.round{display:flex;gap:17px;background:white;border:1px solid var(--line);border-radius:14px;padding:24px}.num{font:20px monospace;color:var(--green)}.round b{color:var(--green);font-size:24px}.round p,.round a{font-size:14px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{padding:13px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--muted);font-weight:500}.gallery{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0;background:white;border:1px solid var(--line);border-radius:13px;overflow:hidden}figure img{display:block;width:100%;height:370px;object-fit:cover;object-position:top}figure.phone img{object-fit:contain;background:#e6eee7}figcaption{padding:14px 18px;font-size:14px;color:var(--muted)}footer{margin-top:40px;color:var(--muted);font-size:13px}.small{font-size:14px;color:var(--muted)}@media(max-width:720px){main{padding:24px 18px}.metrics{grid-template-columns:1fr 1fr}.rounds,.gallery{grid-template-columns:1fr}.metric{padding:18px}.metric b{font-size:30px}.round{padding:19px}}
</style></head><body><main><div class="top"><div class="logo">押题宝 <span class="tag">v2 / LOCAL CANDIDATE</span></div><span class="small">2026.10.28 · 实际浏览器实验</span></div>
<h1>208 页补上证据。<br>再用真实课程检验它。</h1><p class="lead">地球动力学验证跨页推导，SES 验证题目与答案对应。每一轮保留失败、修复与复测结果。</p>
<div class="actions"><a class="button primary" href="http://127.0.0.1:8766/courses/geodynamics/">打开地球动力学</a><a class="button" href="http://127.0.0.1:8766/courses/ses/">打开 SES</a><a class="button" href="library-v0.1.html">上一轮报告</a></div>
<div class="metrics"><div class="metric"><b>208/208</b><span>页面分类与导读覆盖</span></div><div class="metric"><b>12 步</b><span>跨两份课件的推导</span></div><div class="metric"><b>28 对</b><span>SES 大题与答案来源</span></div><div class="metric"><b>103/103</b><span>后端测试通过</span></div></div>
<div class="notice">这是数据与检索试点。OCR 置信度不是正确率，答案导读不是完整解答；独立专家验收仍待完成。当前尚未部署云端 Agent，也未验证考试预测。</div>
<h2>五轮实验，逐项修复</h2><div class="rounds">ROUND_CARDS</div>
<h2>四门课程的 208 个页面</h2><div class="panel table-wrap"><table><thead><tr><th>课程</th><th>已补充</th><th>文字/标题</th><th>图像</th><th>混合</th><th>OCR 纳入索引</th></tr></thead><tbody>ROWS</tbody></table><p class="small">全部页面都有原图和独立导读。没有真正空白页。134 页 OCR 达到索引门槛；另外 74 页保留候选文字供对照，只检索已核查导读。原生文字始终保留。</p></div>
<h2>真实界面截图</h2><p class="small">点击图片查看原尺寸。截图来自本次实际运行，包含 320px 手机视口。</p><div class="gallery">GALLERY</div>
<h2>候选包与剩余边界</h2><div class="panel"><p><strong>library-v0.2-20261028</strong>：五门课、98 份原资料、2,657 个可见记录、1,172 个哈希文件。重新打开后，208 页补充、28 对答案与 40 条 GRT 来源定位再次验证通过。</p><p>SES 的 2024/2025 年份由封面支持，旧五套只保留文件名学年依据。6 道大题有来源警告；未拆分的小问与一次多题请求明确提示不足。</p><p>下一步：对 SES 子题逐项核对条件、单位、数值和评分，并引入独立学科审阅，再扩展教学 Agent 与云端任务。</p></div>
<footer>课程资料仅在本地处理。原始文件与 v0.1 候选包均保留。每轮 JSON 可从上方卡片下载；完整执行记录在项目 docs/low-text-and-pilots-2026-10-28.md。</footer></main></body></html>'''
html=html.replace('ROUND_CARDS',cards).replace('ROWS',rows).replace('GALLERY',gallery)
(OUT/'index.html').write_text(html,encoding='utf-8')
print('Updated report',OUT/'index.html')
