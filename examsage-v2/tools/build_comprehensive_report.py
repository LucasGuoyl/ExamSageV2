"""Build the local, explicitly qualified comprehensive QA report."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
import json,html

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'data/qa/comprehensive-20261106'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def result(name):return json.loads((QA/name).read_text(encoding='utf-8').split('### Result',1)[1].strip())
def esc(value):return html.escape(str(value))

def main():
    files=['browser_smoke-candidate-final.txt','browser_student_round-candidate-final.txt','browser_groundwater_deep-candidate-final.txt','browser_ses_subquestions-candidate-final.txt','browser-extra-candidate-final.txt','bootstrap-boundaries-green.txt']
    rounds=[result(f) for f in files]
    total=sum(r['total'] for r in rounds);passed=sum(r['passed'] for r in rounds)
    data=read(QA/'offline-data.json');ses=read(QA/'ses-verification.json');release=read(QA/'release-verification.json');versions=read(QA/'current-version-check.json');math=result('browser_recovery_math-replay-final.txt')
    assert passed==total==63 and data['passed']==data['total']==4485
    assert not ses['failures'] and release['status']=='passed' and not math['errors']
    assert all(v['snapshot_unchanged'] and v['live_matches_v5_records'] for v in versions)
    regression=(QA/'regression-final.log').read_text(encoding='utf-8')
    assert '167 passed, 9 deselected' in regression
    manifest={'date':'2026-11-10','result':'partial_verification_live_http_blocked','data_candidate':'library-v0.5-20261102','runtime':'local working copy with navigation fixes','offline_regression':{'passed':167,'http_not_run':13},'browser_replay':{'passed':passed,'total':total,'is_live_http':False},'data_checks':Counter(r['name'] for r in data['results']),'review':'Read-only independent reviewer: no new blocking issues after two fix reviews; browser not independently rerun','files':{str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in [*ROOT.glob('src/examsage/*.py'),*ROOT.glob('src/examsage/web/*.*'),*ROOT.glob('tests/test_*.py'),*ROOT.glob('tests/browser_*.js'),ROOT/'tools/comprehensive_qa.py',Path(__file__),ROOT/'README.md']}}
    (QA/'run-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[('离线程序回归','167 / 167','13 项 HTTP 用例未运行，不计入通过'),('浏览器学生流程','63 / 63','当前真实数据响应回放；非实际 HTTP 联通'),('SES 精确小问检索','329 / 329','题号、学年与层级定位'),('SES 配对、条件与数值检查','3,199 / 3,199','包含范围限制与公共题干；非专家验收'),('页面公式排版','238 个公式 / 74 页','仅验证数学排版，无解析错误'),('数据与资源逐项检查','4,485 / 4,485','3,315 来源引用、421 PPTX 解码、553 预览、98 原件哈希、98 页码唯一性'),('v0.5 导出包','通过','1,172 文件哈希、208 补充页、74 恢复页、329 配对；GRT 40 项定位')]
    fixes=['加载未完成时提前点课程／试卷导航：保留用户选择，读取课程类型后再显示正确列表。SES 从错误的 357 个题节点恢复为 14 份文件；行星科学从空列表恢复为 17 份资料。','概览加载失败后再次点导航：立即显示错误及刷新提示，不再永久等待。公式入口在课程类型确定前禁用，随后按课程能力启用。','审计工具发现失败时以失败状态退出；补全回放中的查询来源页，保留旧失败记录。手机放大测试先等待图片解码，原放大与翻页断言未放宽。','README 改为 v0.5 当前数据候选，更新验证范围和剩余来源问题。']
    limitations=['8766 实际服务在清除全部回放路由后仍拒绝连接。已请用户提供启动窗口状态；未扩大权限或绕过限制。','完整程序套件曾尝试启动，受本机通信阻塞停止。13 项 HTTP 用例尚未运行；本轮未完成真实中间件、参数校验、下载链路和完整端到端验证。','5 页字面不确定内容、6 项条件不足冲突、3 个小问官方来源缺口仍保留，未虚构原文或正式勘误。','当前是五门课的本地课程证据库。云端账户、自动适配全球课程、生成式辅导、模拟考试评分及可靠年度预测尚未实现；真实语义模型未启用，未调用付费 API。','数据引用、数值复算与排版通过，不等同于知识结论正确或独立专家验收通过；553 个预览包含全部恢复页及查询来源，未逐页视觉验收全部 2,530 页。']
    body=''.join('<tr><th>'+esc(a)+'</th><td>'+esc(b)+'</td><td>'+esc(c)+'</td></tr>' for a,b,c in rows)
    details=''
    for f,r in zip(files,rounds):
        details+='<details><summary>'+esc(f.replace('-candidate-final.txt',''))+' · '+str(r['passed'])+'/'+str(r['total'])+'</summary><ul>'
        for item in r['results']:details+='<li>'+('✓ ' if item['passed'] else '✗ ')+esc(item.get('name') or ' / '.join(str(item.get(k,'')) for k in ['scenario','course','button']))+'</li>'
        details+='</ul><a href="'+esc(f)+'">原始记录</a></details>'
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>押题宝 · 全面测试报告</title><link rel="icon" href="data:,"><style>body{margin:0;background:#f6f8f3;color:#203831;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1120px;margin:auto;padding:36px 24px}h1{font-size:34px;margin:10px 0}h2{margin-top:32px;font-size:22px}.eyebrow{color:#507367;font-size:13px}.notice{background:#fff4d9;border-left:4px solid #b78320;padding:18px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}.card{padding:22px;background:white;border:1px solid #d8e3d8;border-radius:10px}.card b{display:block;font-size:30px}.card span{font-size:13px;color:#527365}.table{overflow:auto}table{border-collapse:collapse;width:100%;background:white}td,th{padding:13px;border:1px solid #d8e3d8;text-align:left}th{min-width:155px}details{background:#fff;padding:15px;margin:9px 0;border:1px solid #d8e3d8;border-radius:8px}summary{cursor:pointer}a{color:#12664e}img{max-width:100%;border:1px solid #d8e3d8;border-radius:8px}.shots{display:grid;grid-template-columns:2fr 1fr;gap:18px}li{margin:8px 0}footer{font-size:13px;color:#5a7068;margin-top:30px}@media(max-width:650px){main{padding:22px 14px}h1{font-size:27px}.cards{grid-template-columns:1fr}.shots{grid-template-columns:1fr}}</style><main><div class="eyebrow">押题宝 v2 · 数据 v0.5 · 2026-11-10</div><h1>已实现功能的全面测试</h1><p class="notice"><strong>部分验证完成，实际服务联通待补。</strong><br>离线数据、程序回归和响应回放通过；不能据此宣称完整验收通过。</p><div class="cards"><div class="card"><b>167 / 167</b><span>离线回归；另有 13 项 HTTP 未跑</span></div><div class="card"><b>63 / 63</b><span>浏览器响应回放学生流程</span></div><div class="card"><b>329 / 329</b><span>SES 编号小问精确定位</span></div></div>'''
    page+='<h2>实际结果</h2><div class="table"><table>'+body+'</table></div><h2>本轮修复</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in fixes)+'</ul><p>独立只读审查提出问题后已复现并修复；两次复审后，本次修改范围内未发现新的阻断问题。审查者没有独立重跑浏览器。</p><h2>仍未验证与能力边界</h2><ul>'+''.join('<li>'+esc(x)+'</li>' for x in limitations)+'</ul><h2>逐轮学生流程</h2>'+details
    page+='<h2>响应回放截图</h2><p>下图展示当前前端与真实数据，非实际服务联通截图。</p><div class="shots"><img src="desktop-replay.png" alt="桌面课程证据库响应回放"><img src="ses-mobile-390-replay.png" alt="手机 SES 来源冲突阅读响应回放"></div><h2>保留证据</h2><p><a href="bootstrap-red.txt">初始化导航原始失败</a> · <a href="bootstrap-boundaries-red.txt">边界失败</a> · <a href="bootstrap-boundaries-green.txt">边界复验</a> · <a href="browser_smoke.txt">初次放大超时</a> · <a href="browser-extra-replay.txt">回放脚本最初缺页／隐藏按钮记录</a> · <a href="regression-final.log">程序回归</a> · <a href="offline-data.json">逐项资源检查</a> · <a href="run-manifest.json">当前版本指纹</a></p><footer>原始课程资料、旧候选包和旧结果保留。本轮没有推送、发布云端版本或新建候选导出包。</footer></main></html>'
    (QA/'index.html').write_text(page,encoding='utf-8')
    md='# 押题宝全面功能测试 · 2026-11-10\n\n当前数据为 v0.5，五门课程记录与候选包一致；运行代码含本轮导航修复。**离线与回放验证通过，完整 HTTP 验收未完成。**\n\n[可视化报告](../data/qa/comprehensive-20261106/index.html) · [版本指纹](../data/qa/comprehensive-20261106/run-manifest.json)\n\n## 检查结果\n\n| 检查 | 结果 | 限定 |\n|---|---|---|\n'+''.join('| '+a+' | '+b+' | '+c+' |\n' for a,b,c in rows)+'\n## 修改与复验\n\n'+''.join('- '+x+'\n' for x in fixes)+'\n初始化导航先复现 0/2，修复后 2/2；独立复审补充边界从 4/9 到 9/9。最终 63 项页面流程在当前修复代码上重跑。最初手机放大 1.5 秒点击超时保留；等待图片解码后的复测通过，不据此声称已确认生产缺陷。\n\n独立只读审查完成两次修复复审，最终未发现新的阻断问题；审查者未独立重跑浏览器。\n\n## 未完成项\n\n'+''.join('- '+x+'\n' for x in limitations)+'\n## 复现与范围\n\n离线回归命令：\n\n```powershell\npython -X utf8 -m pytest --basetemp=data/qa/comprehensive-20261106/unit-final --ignore=tests/test_api.py -k "not scoped_status_and_export and not course_routes_isolate and not source_course_export_preserves and not reopened_release_retains and not native_preview_survives and not browser_api_offers and not question_api_retains and not corrupted_supplement_image"\n```\n\n退出 0；167 passed，9 deselected，另 test_api.py 的 4 项未收集，合计 13 项待跑；保留 1 个上游弃用警告。完整验收仍需正常环境执行 `./run.ps1 -Action test`，再清除回放路由运行真实服务浏览器流程。没有删除或降低任何验收标准。\n\n数据检查使用 `tools/comprehensive_qa.py`；SES 验证使用 `tools/verify_ses_subquestions.py --qa data/qa/comprehensive-20261106 --data data/ses`；导出包使用 `tools/verify_v3_candidate.py --release data/releases/library-v0.5-20261102 --qa data/qa/comprehensive-20261106`。这三项退出 0，原始记录在报告目录。\n\nGit 元数据沿用既有错误；未提交。原件与旧包未修改，没有新增云端发布或付费调用。\n'
    (ROOT/'docs/comprehensive-test-2026-11-10.md').write_text(md,encoding='utf-8')
    print(json.dumps({'browser_replay':passed,'data_checks':data['passed'],'report':str(QA/'index.html')},ensure_ascii=False))

if __name__=='__main__':main()
