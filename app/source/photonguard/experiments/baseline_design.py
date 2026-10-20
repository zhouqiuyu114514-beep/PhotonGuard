"""Source-bound baselines and a predeclared conservative finite-design policy."""
import copy
from ..core import digest
from . import goal_design as gd,inverse_models as m

ASSUMPTIONS=[{'id':'nominal','noise_multiplier':1.,'amplitude_multiplier':1.},
             {'id':'dimmer_noisier','noise_multiplier':1.5,'amplitude_multiplier':.8},
             {'id':'brighter_quieter','noise_multiplier':.75,'amplitude_multiplier':1.2}]
POLICY={'version':'conservative-v1','minimum_relative_gain':.20,'requires_stable_winner':True,
        'prefer_baseline_without_declared_independent_noise':True,
        'note':'保守选择规则，不是严格不劣保证；没有误差模型支持时默认简单方案，局部方案仍可明确选用。'}


def candidate_baseline(groups,settings,constraints,specified=None):
    import numpy as np
    n=constraints['points'];slit=settings['model']==m.SLIT
    if specified is not None:
        if not isinstance(specified,dict) or set(specified)!={'source','positions_mm','label'} or specified['source']!='USER_SPECIFIED' or not isinstance(specified['label'],str) or not 1<=len(specified['label'])<=160:raise ValueError('已有基础方案需明确来源、位置与名称')
        xx=specified['positions_mm'];source='USER_SPECIFIED';label=specified['label']
    elif slit and settings['fixed'].get('wavelength_nm')==633 and settings['fixed'].get('focal_length_mm')==200 and all(g['dataset']['source_kind']=='SYNTHETIC_TEACHING' for g in groups):
        xx=np.linspace(-2,2,n).tolist();source='RC5_RC6_DECLARED_TEACHING_REFERENCE';label='教学参考：±2 mm，同样点数'
    else:
        old=groups[0]['dataset']['x_mm'];xx=np.linspace(old[0],old[-1],n).tolist();source='ORIGINAL_RANGE_REFERENCE';label='基础方案：在原范围重复'
    reasons=[]
    if not isinstance(xx,list) or len(xx)!=n or any(not m.finite(v) for v in xx):reasons.append('点数或坐标不符合当前预算')
    else:
        if any(b<=a for a,b in zip(xx,xx[1:])):reasons.append('位置必须严格递增')
        if any(b-a<constraints['min_step_mm']-1e-12 for a,b in zip(xx,xx[1:])):reasons.append('最小步距不满足')
        if max(map(abs,xx))>constraints['max_abs_x_mm']:reasons.append('超出允许范围')
        old=groups[0]['dataset']['x_mm']
        if not constraints['allow_extension'] and (xx[0]<old[0] or xx[-1]>old[-1]):reasons.append('用户未允许扩大原范围')
        if slit:
            center=settings['bounds'].get('center_shift_mm',[settings['fixed'].get('center_shift_mm',0)])
            if max(map(abs,xx))+max(map(abs,center))>.1*settings['fixed']['focal_length_mm']:reasons.append('超出声明的近轴范围')
    return {'id':'baseline','label':label,'source':source,'positions_mm':xx,'executable':not reasons,'reasons':reasons,
            'note':'来源明确的比较基线，不是任意实验的最优方案；教学参考不自动更改用户范围或点数。'}


def objective(info,target,normal):
    key={'width':'slit_width_um','separation':'slit_separation_um','waist_radius':'waist_radius_um','waist_position':'waist_z_mm'}.get(target['target'])
    if key:return info['scales'].get(key)
    if target['target']=='prediction':return info['prediction_scale']
    if not info['scales'] or any(v is None for v in info['scales'].values()):return None
    return max(v/normal[k] for k,v in info['scales'].items())


def add_baseline(result,groups,settings,catalog):
    import numpy as np
    if not catalog['executable']:return
    xx=catalog['positions_mm'];names,_,_=m.layout(groups,settings);target=result['research_goal'];pool=result['candidate_parameters']
    region=target['prediction_region_mm'] or [groups[0]['dataset']['x_mm'][0],groups[0]['dataset']['x_mm'][-1]]
    info=[gd.information(groups,settings,c,xx,region) for c in pool]
    worst={k:max(r['scales'][k] for r in info) if all(r['scales'][k] is not None for r in info) else None for k in info[0]['scales']}
    pred=max(r['prediction_scale'] for r in info) if all(r['prediction_scale'] is not None for r in info) else None
    score,envelope=gd.disagreement(xx,settings,pool,names,result['constraints']['registration_uncertainty_mm'],group=groups[-1])
    gaps=np.diff(xx);segments=1+int(np.sum(abs(np.diff(gaps))>1e-8))
    p={'id':'baseline','label':catalog['label'],'source':catalog['source'],'identity':'BASELINE','range_mm':[xx[0],xx[-1]],'points':len(xx),'step_mm':float(min(gaps)),
       'max_step_mm':float(max(gaps)),'prediction_x_mm':xx,'prediction_envelope':envelope,'score':score,'local_scales':worst,'prediction_scale':pred,'local_by_candidate':info,
       'goal_scale':objective({'scales':worst,'prediction_scale':pred},target,result['normalization']),'dominated':False,'conditions':m.physical(settings),'source_kind':'PREDICTION_NOT_OBSERVATION',
       'cost':{'points':len(xx),'position_changes':len(xx)-1,'travel_mm':xx[-1]-xx[0],'uniform_segments':segments,'exposures':len(xx),'data_groups':1},
       'cost_note':'基础方案与其他方案同点数；位置移动及分段成本另列，实际耗时未知。','risks':[]}
    result['plans'].append(p);result['resources']['analytical_prediction_calls']+=sum(v['prediction_calls'] for v in info)+len(pool)


def structured_risk(plan,settings,pool):
    if settings['model']!=m.SLIT:return {'hard_constraints_passed':True,'sampling_gap_warning':False,'note':'高斯纵向采样；不是条纹混叠检查'}
    periods=[settings['fixed']['wavelength_nm']*.001*settings['fixed']['focal_length_mm']/c.get('slit_separation_um',settings['fixed'].get('slit_separation_um')) for c in pool]
    ratio=min(periods)/plan['max_step_mm']
    return {'hard_constraints_passed':True,'sampling_gap_warning':ratio<4,'minimum_samples_per_fringe':ratio,
            'note':'最大局部间隔提示是启发式；非均匀采样不由这一项证明发生或排除混叠。'}


def propose(groups,settings,fit,profiles,constraints,research_goal=None,baseline=None,policy='conservative'):
    if policy not in ('conservative','local_exploration'):raise ValueError('请选择保守基础方案或明确的局部探索')
    result=gd.propose(groups,settings,fit,profiles,constraints,research_goal)
    catalog=candidate_baseline(groups,settings,constraints,baseline);add_baseline(result,groups,settings,catalog)
    plans=result['plans'];pool=result['candidate_parameters'];target=result['research_goal'];normal=result['normalization']
    for p in plans:p.update(identity='BASELINE' if p['id']=='baseline' else 'LOCAL_CANDIDATE',sampling_risk=structured_risk(p,settings,pool))
    baseline_id='baseline' if catalog['executable'] else None
    local=[p for p in plans if p['goal_scale'] is not None]
    best=min(local,key=lambda p:(p['goal_scale'],p['cost']['travel_mm'],p['cost']['uniform_segments'])) if local else None
    region=target['prediction_region_mm'] or [groups[0]['dataset']['x_mm'][0],groups[0]['dataset']['x_mm'][-1]]
    stability=[]
    for assumption in ASSUMPTIONS:
        scores={}
        for p in plans:
            if assumption['id']=='nominal':scores[p['id']]=p['goal_scale'];continue
            infos=[gd.information(groups,settings,c,p['prediction_x_mm'],region,future_assumption={k:v for k,v in assumption.items() if k!='id'}) for c in pool]
            values=[objective(v,target,normal) for v in infos];scores[p['id']]=max(values) if all(v is not None for v in values) else None
            result['resources']['analytical_prediction_calls']+=sum(v['prediction_calls'] for v in infos)
        finite={k:v for k,v in scores.items() if v is not None}
        winner=min(finite,key=finite.get) if finite else None
        base=scores.get(baseline_id);gain=(base-scores[best['id']])/base if best and base is not None and base>0 and scores[best['id']] is not None else None
        stability.append({'assumption':assumption,'goal_scales':scores,'local_best_id':winner,'relative_gain_over_baseline':gain,'source':'DECLARED_SENSITIVITY_SCENARIO_NOT_MEASURED_FACT'})
    eligible=best is not None and all(r['local_best_id']==best['id'] and r['relative_gain_over_baseline'] is not None and r['relative_gain_over_baseline']>=POLICY['minimum_relative_gain'] for r in stability)
    calibrated=settings.get('weighting')=='declared_independent_noise'
    chosen=best['id'] if best else result['recommended_id'];reasons=[]
    if baseline_id and policy=='conservative':
        if not calibrated:chosen=baseline_id;reasons.append('当前为组平均误差目标或数值尺度，未声明独立噪声模型；局部指标不足以承诺实际误差收益，默认基础方案。')
        elif not eligible:chosen=baseline_id;reasons.append('三种公开规划假设下未保持同一优胜者且均超过20%预测收益门槛；默认基础方案或并列查看。')
        elif best['sampling_risk']['sampling_gap_warning']:chosen=baseline_id;reasons.append('局部候选存在较大采样间隔风险，保守策略选择基础方案；不是证明混叠。')
        else:reasons.append('在声明噪声、有限候选与三个公开敏感性假设下，局部候选保持超过20%的预测尺度改善；仍不是实际效果保证。')
    elif not baseline_id:reasons.append('基础方案不满足当前硬约束，未放宽条件；显示可执行的局部方案及风险。')
    else:reasons.append('用户明确采用局部探索；保留基础方案对照及未证实实际收益的提示。')
    for p in plans:
        p['selection_reason']='；'.join(reasons) if p['id']==chosen else '保留作为明确可选对照；局部评分、成本和风险见本方案。'
    result.update(schema='photonguard.measurement-plan.v3',baseline_catalog=[catalog],baseline_id=baseline_id,local_recommended_id=best['id'] if best else None,recommended_id=chosen,
       recommendation_kind='BASELINE_CONSERVATIVE' if chosen==baseline_id else result['recommendation_kind'],selection_reason='；'.join(reasons),stability=stability,
       decision_policy={**POLICY,'selected':policy},local_ranking_includes_baseline=True,
       score_definition='基础方案与有限局部方案使用同一坐标、训练划分与物理条件评分；展示三种公开假设下的稳定性，再按预先声明的保守策略或明确局部探索选择。')
    result['resources'].update(templates=len(plans),sensitivity_scenarios=len(ASSUMPTIONS))
    result['sha256']=digest({k:v for k,v in result.items() if k!='sha256'});return result
