"""Finite paired tradeoffs. Predicted local scales are never error guarantees."""
import copy
from ..core import digest
from . import goal_design as gd,inverse_models as m

VERSION='finite-tradeoff-v1'
DEFAULTS={m.SLIT:{'slit_width_um':.5,'slit_separation_um':.1},
          m.GAUSSIAN:{'waist_radius_um':5.,'waist_z_mm':2.}}


def preferences(cfg,value=None):
    if cfg['model'] not in DEFAULTS:raise ValueError('当前目标取舍仅适用于双缝与高斯模型')
    result={'version':VERSION,'mode':'BASELINE_FIRST','target_scales':copy.deepcopy(DEFAULTS[cfg['model']]),
        'protected_scale_increase':{},'max_travel_mm':None,'max_points':201,
        'minimum_proxy_gain':.05,'extra_travel_penalty_per_mm':0.,'extra_segment_penalty':0.,
        'source':'POLICY_DEFAULT','note':'目标尺度和门槛是公开策略设置，不是实测精度或未来真实误差保证。'}
    if value is not None:
        if not isinstance(value,dict) or set(value)-set(result):raise ValueError('取舍设置字段无效')
        result.update(copy.deepcopy(value))
    if result['version']!=VERSION or result['mode'] not in ('BASELINE_FIRST','CONDITIONAL_EXPLORATION') or result['source'] not in ('POLICY_DEFAULT','USER_TEXT','USER_FORM'):raise ValueError('取舍设置版本或来源无效')
    keys=set(DEFAULTS[cfg['model']])|{'prediction'}
    for name in ('target_scales','protected_scale_increase'):
        values=result[name]
        if not isinstance(values,dict) or set(values)-keys or any(not m.finite(v) or v<0 or name=='target_scales' and v==0 for v in values.values()):raise ValueError('目标尺度需为正，保护项允许增加量不得为负')
    if result['max_travel_mm'] is not None and (not m.finite(result['max_travel_mm']) or not 0<result['max_travel_mm']<=1000):raise ValueError('请给出有效移动上限（mm）')
    if type(result['max_points']) is not int or not 3<=result['max_points']<=201:raise ValueError('新增点数上限无效')
    for k in ('minimum_proxy_gain','extra_travel_penalty_per_mm','extra_segment_penalty'):
        if not m.finite(result[k]) or not 0<=result[k]<=1000:raise ValueError('收益门槛与成本系数需非负')
    return result


def decide(plans,baseline_id,prefs,focus):
    """Pure paired rule; every plan must carry the same scenario identifiers."""
    byid={p['id']:p for p in plans};base=byid.get(baseline_id)
    def cost_ok(p):return p.get('feasible',True) and p['cost']['points']<=prefs['max_points'] and (prefs['max_travel_mm'] is None or p['cost']['travel_mm']<=prefs['max_travel_mm'])
    audit=[];available=[p['id'] for p in plans if cost_ok(p)]
    if base is None or not cost_ok(base):return {'status':'NO_COMPARABLE_BASELINE','selected':None,'alternatives':available,'audit':audit,'reason':'没有满足硬约束的可比基础方案，停止自动探索；可以核对条件性备选。'}
    normal=prefs['target_scales'];protected=prefs['protected_scale_increase'];need=set(focus)|set(protected)
    if not focus or any(k not in normal for k in focus):return {'status':'UNDEFINED_NORMALIZATION','selected':base['id'],'audit':audit,'reason':'目标尺度没有定义，保留基础方案。'}
    def rows(p):
        if p['scenario_ids']!=base['scenario_ids']:raise ValueError('方案必须按同一组公开假设配对')
        data=p['scales_by_scenario']
        if len(data)!=len(base['scenario_ids']) or not data or any(any(not m.finite(r.get(k)) or r[k]<0 for k in need) for r in data):return None
        return data
    br=rows(base)
    if br is None:return {'status':'BASELINE_PROXY_UNAVAILABLE','selected':base['id'],'audit':audit,'reason':'基础方案局部尺度缺失或秩不足，不能自动探索。'}
    loss=lambda row:max(row[k]/normal[k] for k in focus)
    eligible=[]
    for p in plans:
        if p['id']==base['id']:continue
        reasons=[];pr=rows(p);entry={'id':p['id'],'reasons':reasons}
        if not cost_ok(p):reasons.append('HARD_COST_OR_POINT_LIMIT')
        if pr is None:reasons.append('PROXY_UNAVAILABLE')
        else:
            harms={k:max(r[k]-b[k] for r,b in zip(pr,br)) for k in protected}
            gain=min(loss(b)-loss(r) for r,b in zip(pr,br))
            cost=prefs['extra_travel_penalty_per_mm']*max(0,p['cost']['travel_mm']-base['cost']['travel_mm'])+prefs['extra_segment_penalty']*max(0,p['cost']['uniform_segments']-base['cost']['uniform_segments'])
            entry.update(worst_scale_increase=harms,worst_paired_proxy_gain=gain,declared_extra_cost=cost,net_proxy_gain=gain-cost)
            if any(harms[k]>protected[k]+1e-12*max(1,abs(protected[k])) for k in protected):reasons.append('PROTECTED_PARAMETER_PROXY')
            if gain-cost<=prefs['minimum_proxy_gain']:reasons.append('INSUFFICIENT_PROXY_GAIN')
        if not reasons:eligible.append((entry['net_proxy_gain'],-p['cost']['travel_mm'],-p['cost']['uniform_segments'],p['id']))
        audit.append(entry)
    selected=max(eligible)[-1] if eligible and prefs['mode']=='CONDITIONAL_EXPLORATION' else base['id']
    return {'status':'CONDITIONAL_FINITE_PROXY_DECISION','selected':selected,'audit':audit,
        'reason':'采用基础方案；当前偏好为基础优先，或没有方案同时通过保护项、成本和收益门槛。' if selected==base['id'] else '按同一组公开假设，选中同时满足保护项、成本与净收益门槛的条件探索方案。',
        'not_guaranteed_actual_error_noninferiority':True}


def apply(result,groups,cfg,raw):
    prefs=preferences(cfg,raw);target=result['research_goal']['target']
    focus={'width':['slit_width_um'],'separation':['slit_separation_um'],'waist_radius':['waist_radius_um'],
        'waist_position':['waist_z_mm'],'prediction':['prediction']}.get(target,list(DEFAULTS[cfg['model']]))
    result['decision_preferences']=prefs
    region=result['research_goal']['prediction_region_mm'] or [groups[0]['dataset']['x_mm'][0],groups[0]['dataset']['x_mm'][-1]]
    pool=result['candidate_parameters'];scenarios=[s['assumption'] for s in result['stability']]
    comparisons=[]
    for p in result['plans']:
        rows=[];by_candidate=[];scenario_ids=[]
        for h in scenarios:
            infos=p['local_by_candidate'] if h['id']=='nominal' else [gd.information(groups,cfg,c,p['prediction_x_mm'],region,future_assumption={k:v for k,v in h.items() if k!='id'}) for c in pool]
            if h['id']!='nominal':result['resources']['analytical_prediction_calls']+=sum(v['prediction_calls'] for v in infos)
            # Keep candidate identity inside h; independently taking maxima for
            # each plan would compare different candidates and lose the pairing.
            for i,info in enumerate(infos):
                rows.append({k:info['scales'].get(k) for k in DEFAULTS[cfg['model']]}|{'prediction':info['prediction_scale']})
                scenario_ids.append(h['id']+':candidate-'+str(i))
            by_candidate.append(infos)
        p['tradeoff_scales']={'scenario_ids':scenario_ids,'scales_by_scenario':rows,'by_candidate':by_candidate}
        p['execution_allowed']=p['points']<=prefs['max_points'] and (prefs['max_travel_mm'] is None or p['cost']['travel_mm']<=prefs['max_travel_mm'])
        comparisons.append({'id':p['id'],'cost':p['cost'],'feasible':p['execution_allowed'],**{k:p['tradeoff_scales'][k] for k in ('scenario_ids','scales_by_scenario')}})
    decision=decide(comparisons,result['baseline_id'],prefs,focus)
    if cfg.get('weighting')!='declared_independent_noise' and decision['status']=='CONDITIONAL_FINITE_PROXY_DECISION':
        decision.update(status='NUMERICAL_SCALE_ONLY',selected=result['baseline_id'],reason='当前只有数值尺度，没有声明独立噪声依据；保留基础方案，其他方案仅作为条件性备选，不自动探索。')
    if any(k!='prediction' and k not in cfg['bounds'] for k in focus):decision.update(status='TARGET_FIXED',selected=result['baseline_id'] if next((p['execution_allowed'] for p in result['plans'] if p['id']==result['baseline_id']),False) else None,reason='关注参数已是固定已知量，停止把它当待估精度目标。')
    result.update(schema='photonguard.measurement-plan.v4',decision_policy={'version':VERSION,'selected':prefs['mode']},
        tradeoff_decision=decision,recommended_id=decision['selected'],selection_reason=decision['reason'],
        recommendation_kind='CONDITIONAL_FINITE_PROXY_DECISION')
    result['score_definition']='同一组候选与公开假设逐项配对：先检查硬约束和受保护参数，再比较归一化最坏净收益。数值尺度不足以支持自动探索时保留基础方案。'
    for p in result['plans']:p['selection_reason']=decision['reason'] if p['id']==decision['selected'] else ('超出声明的点数或移动上限，不能执行。' if not p['execution_allowed'] else '保留为可核对的备选，详见各参数尺度与保护项。')
    result['limitations'].append('保护项约束的是有限假设下的局部预测尺度，不保证未来真实误差不增加；条件探索不会补填独立噪声声明。')
    result['sha256']=digest({k:v for k,v in result.items() if k!='sha256'});return result
