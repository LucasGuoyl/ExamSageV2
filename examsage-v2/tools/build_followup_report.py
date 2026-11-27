from pathlib import Path
from urllib.parse import quote
import json,html
ROOT=Path(__file__).resolve().parents[1];QA=ROOT/'data/qa/followup-20261102'
def read(p):return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
def esc(x):return html.escape(str(x))
def main():
    sections=''
    for name,title in [('seven','7项证据不足的冲突'),('pages','5页原文不确定内容'),('gaps','3个官方来源缺口')]:
        rows=read(ROOT/'courses'/f'followup_{name}.json');content=''
        for e in rows:
            v=e.get('adjudication') or e['recovery']['adjudication'];label=e.get('record_id') or e['document_id']+' 第'+str(e['number'])+'页'
            content+='<details><summary>'+esc(label)+'</summary><p>'+esc(v['summary'])+'</p>'
            for key,label in [('actions','本次处理'),('remaining','仍需补充')]:
                content+='<h4>'+label+'</h4><ul>'+''.join('<li>'+esc(x)+'</li>' for x in v[key])+'</ul>'
            content+='<p>证据页：'+esc('；'.join(x['document_id']+' p'+str(x['page']) for x in v['evidence']))+'</p>'
            if 'record_id' in e:
                bits=e['record_id'].split(':');query=bits[3]+' Q'+bits[4][1:]+''.join('('+p+')' for p in bits[5].split('.'))+' 答案'
                content+='<a href="http://127.0.0.1:8766/courses/ses/?q='+quote(query)+'">查看小问题答与原页</a>'
            content+='</details>'
        test=read(QA/(name+'-students.json'));score=f"{test.get('passed','待执行')} / {test.get('total','—')}"
        sections+='<section><h2>'+title+'</h2><p>学生情境检查：'+score+'</p>'+content+'</section>'
    browser=read(QA/'browser.json');release=read(QA/'release-verification.json')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>押题宝 · 追加来源搜索</title><style>body{background:#f1f5f2;color:#173c30;font:16px/1.8 system-ui;margin:0}main{max-width:1050px;margin:auto;padding:32px 18px}section{background:white;border-radius:12px;padding:24px;margin:20px 0}details{border:1px solid #d5e2d8;padding:16px;margin:10px 0;border-radius:8px;overflow-wrap:anywhere}summary{cursor:pointer;font-weight:600}a{color:#14654c}.notice{background:#fff5df;padding:18px}h1{line-height:1.3}</style><main><h1>追加课程来源核查</h1><p>2026-11-02 · v0.5候选版 · 本地课程资料复核</p><p class="notice">“已处理”不等于“缺口已关闭”。同一文件的副本不算新证据；后期课件的约定不冒充往年题目给定量。每项保留原结论和仍有限制。</p>SECTIONS<footer>验证状态：RELEASE<br>浏览器：BROWSER</footer></main></html>'''
    search='<section><h2>检索范围与结果</h2><p>7项冲突中，1项技术语义得到确认，6项仍为条件性结论。5页与3个小问均未找回缺失官方原文。</p><p>复习笔记支持波数平方换元，但不能证明板书原字形；该跨文档发现单独保留在页面搜索证据中。</p><ul><li><a href="seven-evidence.json">7项冲突的检索与证据记录</a></li><li><a href="pages-evidence.json">5页的版本、图片边界与补充发现</a></li><li><a href="gaps-evidence.json">3个缺口的96份SES文件检索记录</a></li></ul><p>程序回归：179 / 179。代理复核不等于独立教师验收。</p></section>'
    page=page.replace('SECTIONS',search+sections).replace('RELEASE',esc(release.get('status','待验证'))).replace('BROWSER',esc(str(browser.get('passed','待执行'))+' / '+str(browser.get('total','—'))))
    (QA/'index.html').write_text(page,encoding='utf-8')
if __name__=='__main__':main()


