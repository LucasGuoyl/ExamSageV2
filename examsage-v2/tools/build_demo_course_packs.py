"""Create four clearly labelled teaching examples; never overwrite existing files."""
import argparse
from hashlib import sha256
import json
from pathlib import Path


def record(rid, kind, title, text, refs, **kwargs):
    return dict(id=rid, kind=kind, title=title, text=text, refs=refs, **kwargs)


def build(output):
    if output.exists():
        raise FileExistsError('Choose a new examples directory')
    for discipline, title in [('physics', '物理：线性弹簧'), ('mathematics', '数学：归纳法'),
                              ('literature', '文学：原创短诗的两种解释'), ('history', '历史：区分史料主张与社会事实')]:
        folder = output / discipline
        folder.mkdir(parents=True)
        p1, p2 = [{'document_id': 'lesson', 'page': i} for i in [1, 2]]
        refs = [p1, p2]
        documents, relations = [], []
        if discipline == 'physics':
            pages = ['原创教学演示，非大学真题。\nHooke spring：理想线性弹簧，静力平衡，处于弹性限度内。刚度 k=200 N/m，外加拉力 F=10 N。求伸长量 x，不求位移随时间变化。',
                     '原创推导：回复力 Fs=-kx；静力平衡 F+Fs=0，所以 x=F/k=0.05 m。若同一假设下 F=20 N，x=0.10 m。单位 N/(N/m)=m。超出线性区或动态情形不能直接套用此结论。']
            focus = record('focus','proof','Hooke spring 静力平衡推导', 'Hooke spring：由 Fs=-kx 与 F+Fs=0 得 x=F/k。',refs,
                details={'academic': {'nature':'derivation','assumptions':['理想线性弹簧，静力平衡，弹性限度内'],
                'steps':[{'text':'回复力 Fs=-kx。','refs':[p2]}, {'text':'静力平衡 F-kx=0，故 x=F/k。','refs':[p2]}]}})
            condition, question, answer = pages[0], '求伸长量 x，给出单位和适用条件。', 'x=10/200=0.05 m。仅在题设静态线性弹性条件下成立。'
            extra = []
        elif discipline == 'mathematics':
            pages = ['原创教学演示，非大学真题。\nInduction sum：证明对正整数 n，S_n=1+2+...+n=n(n+1)/2。基例 n=1，两边都是1。假设对某个 k>=1 成立。',
                     '归纳步：S_(k+1)=S_k+(k+1)=k(k+1)/2+(k+1)=(k+1)(k+2)/2。因此由数学归纳法，对所有正整数 n 成立。n=10 时55；n=20 时210。这个证明没有主张任意实数 n 都是有限序列的项数。']
            focus = record('focus','proof','Induction sum 正整数求和证明','Induction sum：基例与归纳步共同证明正整数有限求和公式。',refs,
                details={'academic':{'nature':'derivation','assumptions':['n 是正整数'],
                'steps':[{'text':'n=1 时 S_1=1=1(1+1)/2；假设 S_k=k(k+1)/2。','refs':[p1]},
                         {'text':'S_(k+1)=k(k+1)/2+(k+1)=(k+1)(k+2)/2。','refs':[p2]}]}})
            condition, question, answer = pages[0], '计算 n=10 的有限和，并说明证明为何需要正整数条件。', 'S_10=55。归纳法的基例和后继步骤覆盖正整数；未证明实数项数的有限和。'
            extra = []
        elif discipline == 'literature':
            pages = ['原创演示诗《窗》，作者：押题宝开发演示（AI生成），2026-11-16。非真实文学课程或出版作品。\n1 雨停了，窗还开着。\n2 灯把空椅照成一封未寄的信。\n3 我把钥匙放回门外。\n4 风没有回答。',
                     '原创讨论题，无官方答案。解释甲：开窗与未寄的信可支持等待或联系的愿望；钥匙在门外使归属仍不稳定。解释乙：门外的钥匙与没有回答的风可支持离开或拒绝归属；开窗则使彻底关闭的解释受到挑战。两者都不是唯一确定的作者意图。']
            focus = record('focus','interpretation','窗：等待联系的读法','开窗、空椅与未寄的信可以读作对联系的等待。门外的钥匙使这一读法受到挑战。',refs,
                details={'academic':{'nature':'interpretation','evidence_record_ids':['quote'],'counter_record_ids':['alternative'] }},
                limitations=['原创诗的一个可争辩解释，不是唯一作者意图或官方答案。'])
            extra = [record('quote','block','窗：原创诗原句',pages[0],[p1]),
                     record('alternative','interpretation','窗：离开归属的读法','门外的钥匙和没有回答的风可支持离开；开窗对彻底隔绝构成反证。',refs,
                         details={'academic':{'nature':'interpretation','evidence_record_ids':['quote']}})]
            relations.append(dict(id='readings',kind='contradicts',source='focus',target='alternative',refs=refs,origin='inferred'))
            condition, question, answer = '只依据这首原创诗，区分原句、解释与反证。', '比较两种读法并给出行号；不要把一种读法称为唯一正确答案。', None
        else:
            quote = 'We hold these truths to be self-evident, that all men are created equal,'
            raw = 'Declaration of Independence, 1776. Public-domain excerpt.\nSource: https://www.archives.gov/founding-docs/declaration-transcript\nAccessed: 2026-11-16.\nExcerpt from the paragraph beginning "We hold".\n'+quote+'\n'
            (folder/'declaration-excerpt.txt').write_bytes(raw.encode())
            documents.append(dict(id='declaration',relative_path='declaration-excerpt.txt',sha256=sha256(raw.encode()).hexdigest(),kind='primary_source',pages=1))
            original_ref = {'document_id':'declaration','page':1}
            pages = ['原创史料分析演示，非大学真题。配套 declaration-excerpt.txt 是美国国家档案馆转录的1776年《独立宣言》公共领域节选；此处页码是本地节选页码，不是档案手稿页码。',
                     '只依据这一段，能确认文件表达了平等主张，不能据此确认当时所有人的实际社会处境。需要其他类型的资料来检验实践。思考：原文主张、作者立场、社会事实分别是什么？本例没有配套评分标准或官方答案。']
            refs = [original_ref, p2]
            focus = record('focus','claim','equal：原文中的平等主张','原文说 all men are created equal；这里标注的是文献主张，而不是对1776年社会实践的证实。',refs,
                details={'academic':{'nature':'author_claim','evidence_record_ids':['quote']}},
                limitations=['文献中的平等主张不等于已证明当时社会实践平等；需要其他来源。'])
            extra = [record('quote','block','原文节选：equal',quote,[original_ref])]
            condition, question, answer = '只使用给定《独立宣言》节选；明确资料的目的与证明范围。', '能否据此断言所有人实际享有平等待遇？说明还缺什么证据。', None
        text = '\f'.join(pages)+'\n'
        (folder/'lesson.txt').write_bytes(text.encode())
        documents.append(dict(id='lesson',relative_path='lesson.txt',sha256=sha256(text.encode()).hexdigest(),kind='literary_text' if discipline=='literature' else 'lecture',pages=2))
        records = [focus, *extra, record('q','question','演示讨论/计算题',condition,[p1]),
                   record('q-a','question','小问 a',question,[p2],parent_id='q')]
        if answer:
            records.append(record('a-a','answer','原创练习参考解答（非官方）',answer,[p2], limitations=['开发演示参考解答，独立专家验收待完成。']))
            relations.append(dict(id='pair-a',kind='has_answer',source='q-a',target='a-a',refs=[p2],origin='explicit'))
        cid = 'demo-'+discipline
        pack = {'workspace':'cross-discipline-demo', 'profile':{'course_id':cid,'curriculum_system':'demonstration',
            'institution':None,'stage':'演示：非认证课程','language':'zh/en','syllabus_version':'2026-demo-v1',
            'disciplines':[discipline],'material_status':'demonstration',
            'outcomes':[{'id':'reason-with-sources','description':'区分原文、条件、推理与证据不足。','refs':refs,'record_ids':['focus']}]},
            'manifest':{'course_key':cid,'course_name':'演示 / '+title,'documents':documents},
            'records':records,'relations':relations}
        (folder/'pack.json').write_text(json.dumps(pack,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'README.md').write_text('''# 跨学科演示课程包

这四份材料用于验证导入、引用、条件继承和证据边界，不是帝国理工或其他学校真实课程，不构成专家教学验收。
数学、物理练习与文学短诗/解读由开发代理原创；历史采用公共领域原文节选及原创分析题。
历史节选来源：[美国国家档案馆转录](https://www.archives.gov/founding-docs/declaration-transcript)，核对日期 2026-11-16。
TXT 中分页符 `\\f` 定义本地页码，不能冒充原始书籍或档案页码。所有整理记录导入后保持 candidate。
每个 pack.json 都包含具体来源哈希、学习目标和记录关系，可作为新课程包的格式示例。
''',encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
