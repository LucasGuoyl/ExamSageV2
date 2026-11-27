"""Record live service checks separately from the earlier response replay."""
from pathlib import Path
from hashlib import sha256
import json,html

ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/live-20261110'
def read(name):return json.loads((QA/(name+'.txt')).read_text(encoding='utf-8').split('### Result',1)[1].strip())
def esc(value):return html.escape(str(value))

names=['browser_smoke','browser_student_round','browser_groundwater_deep','browser_ses_subquestions','browser-extra','browser_bootstrap_navigation','browser_async_round']
rows=[read(n) for n in names];http=read('http');previews=read('browser_library_inventory')
assert sum(r['passed'] for r in rows)==sum(r['total'] for r in rows)==69
assert http['total']==http['passed']==33 and previews['total']==previews['passed']==110
assert len({(r['course'],r['document']) for r in previews['results']})==98
summary={'date':'2026-11-10','service':'http://127.0.0.1:8766/','mode':'live service with deliberate delay/failure injection in resilience cases; no snapshot response replay','browser':{'passed':69,'total':69},'http':{'passed':33,'total':33},'preview':{'passed':110,'total':110,'documents':98},'remaining':'13 isolated TestClient tests remain unrun in the agent environment; these live checks are distinct and do not assert the full pytest suite passed','code_hashes':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in [*ROOT.glob('src/examsage/*.py'),*ROOT.glob('src/examsage/web/*.*')]},'snapshots':{r['name'].split('：')[0]:r['snapshot'] for r in http['results'] if 'snapshot' in r}}
(QA/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
details=''
for n,r in zip(names+['http','browser_library_inventory'],rows+[http,previews]):
 details+='<details><summary>'+esc(n)+' · '+str(r['passed'])+'/'+str(r['total'])+'</summary><ul>'
 for x in r['results']:details+='<li>✓ '+esc(x.get('name') or (x.get('document','')+' '+str(x.get('page','')) if 'document' in x else ' / '.join(str(x.get(k,'')) for k in ['scenario','course','button'])))+'</li>'
 details+='</ul><a href="'+esc(n)+'.txt">原始结果</a></details>'
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>押题宝 · 真实服务补测</title><link rel="icon" href="data:,"><style>body{margin:0;background:#f6f8f3;color:#203831;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1080px;margin:auto;padding:32px 22px}h1{font-size:34px}.notice{background:#e5f2e9;padding:18px;border-left:4px solid #277b4b}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.card,details{background:white;border:1px solid #d8e3d8;padding:18px;border-radius:10px;margin:10px 0}.card b{display:block;font-size:30px}summary{cursor:pointer}a{color:#12664e}img{max-width:100%;border:1px solid #d8e3d8}.shots{display:grid;grid-template-columns:2fr 1fr;gap:16px}li{margin:7px 0}@media(max-width:650px){.cards,.shots{grid-template-columns:1fr}h1{font-size:27px}}</style><main><p>押题宝 v2 · 数据 v0.5 · 2026-11-10</p><h1>真实服务已连通，学生流程通过</h1><p class="notice">截图中的“Uvicorn running”表示启动成功。保持黑色服务窗口打开，然后在浏览器访问 <a href="http://127.0.0.1:8766/">押题宝首页</a>。当前启动器不会自动打开网页。</p><div class="cards"><div class="card"><b>69 / 69</b>浏览器学生流程</div><div class="card"><b>33 / 33</b>实际 HTTP 接口检查</div><div class="card"><b>110 / 110</b>来源预览，覆盖 98 份文件</div></div><p>已清除上一阶段的快照响应回放，测试连接用户启动的实际服务。异常恢复用例有意注入延迟或失败，其余读取、检索、预览与下载来自实际服务。</p><h2>本轮确认</h2><ul><li>五门课程、GRT 地下水推导、SES 小问与父题上下文、手机原页阅读均通过。</li><li>每门课抽取一份原件下载，共 5 份，内容哈希与登记来源一致；4 门非 GRT 课程均拒绝获取 GRT 原件。</li><li>非法 Host/Origin、空或超长查询、无效页码、未知记录、写入方法均按预期处理。</li><li>加载过程中导航、加载失败后再次导航、公式入口就绪状态，以及较早请求覆盖较新操作的问题均通过真实服务复验。</li></ul><h2>仍有限制</h2><p>本轮没有发现新的产品缺陷。先前代码修复已有独立只读复审；本轮实测由主 agent 执行。13 项依赖本机通信的隔离 TestClient 用例仍未在 agent 环境跑通；这 33 项实际 HTTP 检查不能等同于那 13 项，因此不宣称完整 pytest 套件通过。</p><p>原有 167 项离线回归、数据审计、来源不确定项及云端 Agent 尚未实现的边界，见<a href="../comprehensive-20261106/index.html">前阶段完整报告</a>。服务成功启动不代表已实现自由生成辅导、自动适配所有课程或可靠押题。</p><h2>逐项记录</h2>'''+details+'''<h2>实际服务截图</h2><div class="shots"><img src="desktop-live.png" alt="实际服务桌面首页"><img src="ses-mobile-390-live.png" alt="实际服务SES手机页面"></div><p><a href="summary.json">代码指纹、快照与结果汇总</a></p></main></html>'''
(QA/'index.html').write_text(page,encoding='utf-8')
print(json.dumps({'browser':69,'http':33,'previews':110,'remaining_testclient':13}))
