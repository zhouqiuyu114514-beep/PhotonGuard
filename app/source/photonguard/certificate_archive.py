"""Read-only research archive, separate from every historical case verdict."""
import hashlib,html,json
from decimal import Decimal,ROUND_CEILING
from pathlib import Path

ARCHIVE=Path(__file__).with_name('research_archive')
MODEL_HASH='5c189d2ce2f2969d8282ad69899f3315b876786d8137641199a7ffc9f37b9ff5'
CERTIFICATE_HASH='7636632cfb878df245e9c7566b5c0de1942aca43928fb5ff04bb729afe784a90'
QUESTIONS=[
 ('efficiency','所以转换效率只有 0.0499%？','F 是归一化相位因子，不是转换效率。此处不计算输出功率或绝对转换效率。'),
 ('order','改成五阶就算通过吗？','原目标锁定一阶 QPM。五阶是另一个任务，不能用来宣布原设计通过。'),
 ('length','把器件缩短就可以了吗？','原器件长度锁定 1000 μm。缩短器件需要新任务与新证书，原结论保持不变。'),
 ('geometry','改了宽度或膜厚，旧证书还能用吗？','不能直接沿用。几何改变会产生新模型哈希，必须重新完成适用检查与连续认证。'),
 ('unknown','我的真实器件参数不全，能套这个结果吗？','这份结果针对公开合成模型。请保存未知参数，补充实际截面、晶轴、材料与边界资料后另建任务；不猜测实物条件。'),
 ('window','再点一次，把耗尽的实验重新跑起来？','已结束的研究窗口只读保留，不能重放旧批准。新实验需要独立计划、资源上限与输入绑定；此页面不会启动计算。'),
 ('history','旧报告说证据不足，新证书怎么又能排除？','两个判断回答不同问题。旧数值流程仍为 INCONCLUSIVE；新连续证书证明该固定模型达不到目标，不把旧报告改成 PASS，也不计为 AI 修复成功。'),
 ('replay','打开这个页面是在实时计算吗？','这里展示保存实跑与证书回放结果。打开页面新增求解 0、付费 AI 0；模拟测试也不是真人使用。'),
]

def overview(root=None):
    root=Path(root or ARCHIVE);manifest=json.loads((root/'manifest.json').read_text())
    for name,entry in manifest['files'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('ARCHIVE_PATH')
        content=path.read_bytes()
        if len(content)!=entry['bytes'] or hashlib.sha256(content).hexdigest()!=entry['sha256']:raise ValueError('ARCHIVE_BYTES')
    cert=json.loads((root/'original-certificate.json').read_text())
    if hashlib.sha256((root/'original-certificate.json').read_bytes()).hexdigest()!=CERTIFICATE_HASH or cert['continuous_model_hash']!=MODEL_HASH:raise ValueError('ORIGINAL_CERTIFICATE_BINDING')
    design=json.loads((root/'design-result.json').read_text())
    if design['actual_workers']!=6 or design['status']!='NO_FEASIBLE_CANDIDATE_OBSERVED_IN_THIS_WINDOW':raise ValueError('FROZEN_DESIGN_ARCHIVE')
    return {'kind':'SAVED_RESEARCH_ARCHIVE','applies_to_current_case':False,'model_sha256':MODEL_HASH,
        'conclusion':'这个固定模型中的原设计达不到所设相位因子目标；不是求解失败，也不是证明全部器件不可行。',
        'historical':{'verification_status':'INCONCLUSIVE','design_goal_status':'NOT_EVALUATED','S':'原记录保持原值，未被本侧车替换'},
        'strict':{'decision':cert['research_goal_decision'],'phase_factor_upper':cert['certified_phase_factor_upper'],'phase_factor_target':.8,'certificate_sha256':CERTIFICATE_HASH},
        'design':{'status':design['status'],'target_d':.03875,'workers':6,'baseline_d':design['baseline_d'],
            'candidates':[{k:r[k] for k in ('id','task_id','model_sha256','d','residual','eligible_both','strict_certificate','numerical_policy')} for r in design['candidates']]},
        'fixed_goal':cert['original_goal'],'questions':[{'id':i,'question':q,'answer':a} for i,q,a in QUESTIONS],
        'archive_actions':{'new_solver_calls':0,'new_paid_AI_calls':0,'human_participants':0},
        'limitations':cert['limits'],'source_manifest':manifest}

def render(value):
    e=html.escape;s=value['strict'];d=value['design']
    display_upper=Decimal(str(s['phase_factor_upper'])).quantize(Decimal('0.000000001'),rounding=ROUND_CEILING)
    rows=''.join(f'<tr><th>{e(r["id"])}</th><td>{r["d"]:.9f}</td><td>{r["residual"]:+.9f}</td><td>基础实跑完成；未进入严格认证</td></tr>' for r in d['candidates'])
    questions=''.join(f'<details data-trial="{e(q["id"])}"><summary>{e(q["question"])}</summary><p>{e(q["answer"])}</p></details>' for q in value['questions'])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>冻结模型证据档案 · PhotonGuard</title>
<link rel="stylesheet" href="/assets/certificate-report.css"></head><body><main>
<a href="/">← 返回 PhotonGuard</a><p class="eyebrow">研究档案 · 保存实跑 / 证书回放</p><h1>原模型已排除，研究证据已冻结</h1><p class="lead">{e(value['conclusion'])}</p><p class="quiet">当前主线：薄膜新手流程、真实AI对照与可复跑交付。固定20 μm周期的新几何搜索已暂停；以下保留历史探索记录。</p><p class="quiet">公开合成模型：长度 1000 μm，周期 20 μm，一阶 QPM，目标 F ≥ 0.8。F 是相位因子，不是转换效率。</p>
<div class="cards"><article class="card history"><span class="tag">01 · 原数值流程</span><h2>历史判断保留</h2><p class="number">INCONCLUSIVE</p><p>已测试数值精度不足以判断达标。原 S、原始报告与失败记录保持原样。</p><p class="quiet">没有因新增证书改为 PASS。</p></article>
<article class="card strict"><span class="tag">02 · 固定模型严格侧车</span><h2>原目标被排除</h2><p class="number">F ≤ {display_upper}</p><p>严格上界低于 0.8。结论绑定原模型、原选中场与原目标。显示数值已向上取整。</p><p class="quiet">EXCLUDED · 不计为 AI 修复成功</p></article>
<article class="card design"><span class="tag">03 · 新设计研究</span><h2>本窗口未发现可行点</h2><p class="number">3 个方案 / 6 次实跑</p><p>各方案保留四个候选模式。没有进入后续搜索或新几何严格认证。</p><p class="quiet">不推断全部几何无解。</p></article></div>
<section><h2>三个新方案离目标还有多远？</h2><p>两波长有效折射率差 d 的目标约为 0.03875；下表为基础求解值，尚未通过原数值精度政策。</p><div class="scroll"><table><thead><tr><th>方案</th><th>d</th><th>距目标的差</th><th>阶段</th></tr></thead><tbody>{rows}</tbody></table></div><p class="quiet">G-W：增宽至 2.2 μm；G-S：平板增厚至 0.45 μm；G-H：总膜厚增至 0.9 μm。原基准 d ≈ {d['baseline_d']:.9f}。</p><p>AI 可以提出方案；是否通过由模型、数值检查与严格证据决定。本轮研究新增付费 AI 调用 0。</p></section>
<section><h2>读懂这份结论</h2>{questions}</section><section><h2>适用边界</h2><p>结果只覆盖指定的冻结材料系数、4×4 μm 周期连续模型。实物材料不确定性、开放边界与新几何仍需要各自的证据。</p><p class="quiet">本页只读；打开页面新增求解 0、付费请求 0。确定性模拟试用与真人试用分别计数，真人参与 0。</p><details><summary>查看模型绑定与原始状态</summary><pre>{e(json.dumps(value,ensure_ascii=False,indent=2))}</pre></details><a href="/api/research-certificate">下载本页结构化研究摘要</a></section></main></body></html>'''
