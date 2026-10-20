"""Derived, explicitly labeled E-field maps and mathematical phase-factor curve."""
from pathlib import Path
import hashlib,html,json,math
import numpy as np
from .core import load,digest
from .runner import verify_evidence
from .adapters.qpm_phase import phase_factor

def field_svg(folder,mode):
    with np.load(Path(folder)/mode['fields_npz'],allow_pickle=False) as data:
        raw=np.sum(abs(data['E'][:,:,0,:])**2,axis=-1);x,y=data['x_um'],data['y_um']
    stride=max(1,math.ceil(max(raw.shape)/100));values=raw[::stride,::stride];peak=float(raw.max())
    if not peak>0:raise ValueError('No finite nonzero electric field.')
    cells=[];width=400/values.shape[0];height=300/values.shape[1]
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v=math.sqrt(float(values[i,j])/peak);color=f'rgb({round(20+225*v)},{round(30+210*v)},{round(110-60*v)})'
            cells.append(f'<rect x="{50+i*width:.3f}" y="{25+(values.shape[1]-1-j)*height:.3f}" width="{width+.02:.3f}" height="{height+.02:.3f}" fill="{color}"/>')
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 380" role="img"><title>实际MPB电场模平方，除以本图峰值；显示抽取，非新求解点</title>'+''.join(cells)+f'<g font-family="sans-serif" font-size="12"><text x="50" y="348">x: {x[0]:.2f} 到 {x[-1]:.2f} μm</text><text x="50" y="367">y: {y[0]:.2f} 到 {y[-1]:.2f} μm；|E|² / 峰值</text></g></svg>'

def phase_svg(task,result):
    length=task['requirements']['length_um'];current=result['residual_delta_beta_rad_per_um']
    bound=max(2*math.pi/length,abs(current)*1.2);xs=np.linspace(-bound,bound,301)
    values=[phase_factor(float(x),length) for x in xs]
    sx=lambda x:55+(x+bound)/(2*bound)*640;sy=lambda f:280-230*f
    points=' '.join(f'{sx(x):.3f},{sy(y):.3f}' for x,y in zip(xs,values))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 740 350" role="img"><title>归一化相位匹配因子F；公式计算曲线，不是非线性功率仿真</title><rect width="740" height="350" fill="white"/><path d="M55 50 V280 H695" stroke="#333" fill="none"/><polyline points="{points}" stroke="#187058" fill="none" stroke-width="2"/><circle cx="{sx(current):.3f}" cy="{sy(result["phase_factor_NOT_efficiency"]):.3f}" r="5" fill="#b93830"/><g font-family="sans-serif" font-size="13"><text x="55" y="315">残余 Δβ：{-bound:.4g} 到 {bound:.4g} rad/μm</text><text x="55" y="335">F∈[0,1]；红点是本任务；301个公式计算展示点，新增MPB点0</text><text x="8" y="54">F=1</text><text x="8" y="280">F=0</text></g></svg>'

def render(bundle,qpm_task,qpm_result,destination,*,repair_context=None):
    if not verify_evidence(bundle):raise ValueError('Mode evidence changed; no derived report.')
    from .adapters.mpb_modes import qpm_sources
    from .adapters.qpm_phase import evaluate
    _,receipts=qpm_sources(bundle)
    if evaluate(qpm_task,verified_mode_sources=receipts)!=qpm_result:raise ValueError('QPM result cannot be rebuilt from its mode evidence.')
    root=Path(bundle);out=Path(destination);out.mkdir(parents=True,exist_ok=False);report=load(root/'report.json')
    if qpm_result['task_sha256']!=digest(qpm_task):raise ValueError('QPM task and result differ.')
    figures=[];rows=[]
    for mode in report['mode_inputs']:
        wave=mode['wavelength_um'];folder=root/('base-'+str(wave));raw=load(folder/'result.json');filename='field-'+str(wave)+'.svg'
        (out/filename).write_text(field_svg(folder,raw['selected_mode']))
        figures.append(f'<figure><img src="{filename}" alt="{wave} μm实际MPB电场分布"><figcaption>{wave} μm；实际带号{mode["selected_band"]}；图为电场模平方相对峰值，非功率或1 W场。</figcaption></figure>')
        rows.append(f'<tr><td>{wave}</td><td>{mode["neff"]:.10f}</td><td>{mode["beta_rad_per_um"]:.10f}</td><td>{mode["neff_sensitivity_estimate"]:.6g}</td></tr>')
    (out/'phase-factor.svg').write_text(phase_svg(qpm_task,qpm_result));r=qpm_task['requirements']
    device=load(root/'task.json')['requirements']
    judgment=('计算检查通过，但独立设计目标未达到。' if qpm_result['design_goal_status']=='NOT_MET' else
        '在已测试条件下达到独立归一化相位目标；不代表绝对效率。' if qpm_result['design_goal_status']=='MET' else
        '精度或来源不足，独立设计目标尚不能判断。')
    repair_html=''
    if repair_context is not None:
        permit=load(root/'permit.json');candidate=load(root/'numerical-candidate.json')
        if (permit.get('phase')!='repair' or permit.get('card_sha256')!=repair_context['approved_card_sha256']
            or permit.get('candidate_sha256')!=digest(candidate) or repair_context['task_sha256']!=digest(load(root/'task.json'))
            or repair_context['qpm_goal_sha256']!=digest(r)):
            raise ValueError('Repair report binding changed.')
        (out/'repair-context.json').write_text(json.dumps(repair_context,ensure_ascii=False,indent=2))
        repair_html='<h2>一次批准的数值修复</h2><p>只修改独立数值候选，器件、目标、长度、制造周期与验收器未变。原任意脚本没有修复或执行；批准后新增模型请求0。</p><pre>'+html.escape(json.dumps(repair_context,ensure_ascii=False,indent=2))+'</pre>'
    text=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MPB模态与QPM证据报告</title><style>body{{font:16px/1.7 sans-serif;max-width:1050px;margin:35px auto;padding:15px;color:#173b33}}table{{border-collapse:collapse}}th,td{{padding:9px;border:1px solid #bbb}}img{{max-width:100%}}figure{{display:inline-block;max-width:46%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.warning{{padding:15px;background:#fff1cf}}</style><link rel="stylesheet" href="/assets/mode-report.css">
    <h1>二维脊波导模态 → QPM归一化相位响应</h1><p class="warning">公开合成教学例。确认类型：{html.escape(report['confirmation_kind'])}。不是用户实际器件；本报告不计算绝对变频效率。</p>
    <p>模态验证：<b>{report['verification_status']}</b>；QPM计算可信性：<b>{qpm_result['verification_status']}</b>；设计目标：<b>{qpm_result['design_goal_status']}</b>。</p>
    <p>MPB实际求解两个指定波长，每个基础/加密/加大超胞三设置。全矢量、NO_PARITY，按场、主偏振与局域性选模，跨设置核对重叠与身份，带号不是身份。</p>
    <table><tr><th>真空波长 μm</th><th>基础 n_eff</th><th>β rad/μm</th><th>已测设置敏感度估计</th></tr>{''.join(rows)}</table><div>{''.join(figures)}</div>
    {repair_html}<h2>目标与结果分别判断</h2><p>已确认长度{r['length_um']} μm、极化周期{r['poling_period_um']} μm，目标F≥{r['target_phase_factor_min']}。F={qpm_result['phase_factor_NOT_efficiency']:.8g}。{judgment}不会擅自改制造周期。</p>
    <p>残余Δβ={qpm_result['residual_delta_beta_rad_per_um']:.8g} rad/μm；模式设置敏感度传播到相位的估计为{qpm_result['phase_sensitivity_estimate_rad']:.6g} rad，检查限值{qpm_result['phase_sensitivity_limit_rad']} rad。网格差不是严格真误差上界。</p><img src="phase-factor.svg" alt="公式计算的相位因子曲线，红点标任务结果">
    <h2>边界</h2><p>材料为Zelmon1997未掺杂同成分LN、21℃；每个波长单独冻结介电张量。总膜厚{device['film_thickness_um']} μm、残余平板{device['slab_thickness_um']} μm、矩形脊宽{device['ridge_width_um']} μm，上方空气/下方人工无色散n=1.44。没有真实SiO2/Si有限基底、非线性张量重叠、功率归一化、泵浦耗尽、损耗或实验校验。F=1只表示理想归一化相位因子，不能说转换效率100%。</p>
    <details><summary>实际检查、运行次数、原始来源与哈希</summary><pre>{html.escape(json.dumps({'checks':report['checks'],'solver_counts':report['solver_counts'],'source_binding_sha256':report['source_binding_sha256'],'mode_bundle_manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),'qpm':qpm_result},ensure_ascii=False,indent=2))}</pre></details></html>'''
    (out/'report.html').write_text(text,encoding='utf-8')
    manifest={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'manifest.json').write_text(json.dumps({'schema_version':1,'files':manifest},indent=2))
    for p in out.iterdir():p.chmod(0o444)
    out.chmod(0o555);return out
