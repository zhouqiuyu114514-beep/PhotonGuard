"""Finite goal-directed designs. Public joint candidates only; no future observations."""
import copy
from ..core import digest
from . import inverse_models as m

TARGETS={'width','separation','balanced','prediction','waist_radius','waist_position'}


def goal(model, value=None):
    default={'target':'balanced','source':'DEFAULT_BALANCED','tolerances':{},'prediction_region_mm':None}
    if value is None:return default
    if not isinstance(value,dict) or set(value)-set(default):raise ValueError('研究目标字段无效')
    result=default|copy.deepcopy(value)
    allowed={'balanced','prediction'}|({'width','separation'} if model==m.SLIT else {'waist_radius','waist_position'})
    if result['target'] not in allowed or result['source'] not in ('DEFAULT_BALANCED','USER_FORM','USER_TEXT'):raise ValueError('目标与当前模型不符')
    if result['source']=='DEFAULT_BALANCED' and result['target']!='balanced':raise ValueError('默认目标只能是平衡目标')
    keys=physical(model)
    if not isinstance(result['tolerances'],dict) or set(result['tolerances'])-set(keys) or any(not m.finite(v) or v<=0 for v in result['tolerances'].values()):raise ValueError('目标容差必须为正，且仅针对物理参数')
    region=result['prediction_region_mm']
    if result['target']=='prediction' and (not isinstance(region,list) or len(region)!=2 or not all(m.finite(v) for v in region) or region[0]>=region[1] or max(map(abs,region))>1000):raise ValueError('请明确要预测的坐标区间（mm）')
    return result


def physical(model):return ('slit_width_um','slit_separation_um') if model==m.SLIT else m.GAUSSIAN_PARAMETERS


def candidates(groups,settings,fit,profiles):
    import numpy as np
    if not fit.get('estimated_parameters'):raise ValueError('先完成一次拟合；缺少物理条件时不能给出自适应排名')
    minimum=min([fit['best_cost']]+[p['best_cost'] for p in profiles.values()]);allowance=max(abs(minimum)*.1,1e-8)
    pool=[r['parameters'] for p in profiles.values() for r in p['rows'] if r.get('accepted') and r.get('parameters') and r['cost']-minimum<=allowance]
    pool += [r['parameters'] for r in fit.get('starts',[]) if r.get('success') and r['cost']-minimum<=allowance]
    if fit['best_cost']-minimum<=allowance:pool.append(fit['estimated_parameters'])
    if not pool:raise ValueError('没有可用联合候选；求解未收敛不能解释为排除参数')
    keys=[k for k in physical(settings['model']) if k in settings['bounds']]
    scale={k:settings['bounds'][k][1]-settings['bounds'][k][0] for k in keys}
    chosen=[pool.pop(0)]
    while pool and len(chosen)<12:
        def distance(v):return min(float(np.linalg.norm([(v[k]-c[k])/scale[k] for k in keys])) for c in chosen)
        index=max(range(len(pool)),key=lambda i:distance(pool[i]));v=pool.pop(index)
        if distance(v)>1e-5:chosen.append(v)
    unresolved=any('UNRESOLVED_PROFILE_POINTS' in p['warnings'] for p in profiles.values())
    status='MULTIPLE_PHYSICAL_CANDIDATES' if len(chosen)>1 else 'LOCAL_ONLY_SINGLE_PHYSICAL_CANDIDATE'
    if unresolved:status='SOLVER_UNRESOLVED_LOCAL_ONLY'
    return chosen,{'status':status,'shared_minimum':minimum,'allowance':allowance,'physical_distance_only':True,
        'refinement_eligible':len(chosen)==1 and bool(profiles) and not unresolved,
        'note':'只保留实际联合拟合/剖面点；不拼接区间端点。单一候选只支持局部灵敏度建议，未证明唯一。'}


def templates(groups,settings,constraints,mixed=True):
    import numpy as np
    slit=settings['model']==m.SLIT
    required={'max_abs_x_mm','points','min_step_mm','allow_extension','stable_exposure_background','registration_uncertainty_mm'}
    if not isinstance(constraints,dict) or set(constraints)!=required:raise ValueError('请明确范围、点数、步距、曝光与配准条件')
    cap=constraints['max_abs_x_mm'];n=constraints['points'];step=constraints['min_step_mm'];shift=constraints['registration_uncertainty_mm']
    if not m.finite(cap) or not 0<cap<=500 or type(n) is not int or not (20 if slit else 3)<=n<=201 or not m.finite(step) or step<=0 or not m.finite(shift) or not 0<=shift<=cap:raise ValueError('补采范围、点数或步距无效')
    if any(type(constraints[k]) is not bool for k in ('allow_extension','stable_exposure_background')) or not constraints['stable_exposure_background']:raise ValueError('一次扫描内须保持曝光与背景稳定；否则分开上传')
    if slit and settings['registration']=='INDEPENDENT' and shift<=0:raise ValueError('独立中心需声明正的配准不确定性')
    if settings['registration']=='SHARED_REGISTERED' and shift!=0 or 'center_shift_mm' in settings['fixed'] and shift:raise ValueError('配准不确定性与已知条件冲突')
    if not slit and settings['registration']!='SHARED_REGISTERED':raise ValueError('高斯补采需使用同一个已配准的全局 z 坐标')
    x=groups[0]['dataset']['x_mm'];left,right=x[0],x[-1];half=max(abs(left),abs(right))
    if cap<half:raise ValueError('允许范围小于原采集范围')
    far=cap
    if slit:
        c=settings['bounds'].get('center_shift_mm',[settings['fixed'].get('center_shift_mm',0)])
        far=min(far,.1*settings['fixed']['focal_length_mm']-max(map(abs,c)))
    ranges=[('repeat',left,right)]
    if constraints['allow_extension'] and far>half+1e-9:ranges += [('medium',-(half+far)/2,(half+far)/2),('wide',-far,far)]
    result=[]
    for name,a,b in ranges:result.append((name,np.linspace(a,b,n),1))
    if mixed and len(ranges)>1:
        # Three registered allocations. One stable scan, not three independent A/B groups.
        for frac,label in ((.6,'mixed60'),(.4,'mixed40'),(.8,'mixed80')):
            nc=max(1,min(n-2,round(n*frac)));nl=(n-nc)//2;nr=n-nc-nl
            xx=np.r_[np.linspace(-far,left,nl+1)[:-1],np.linspace(left,right,nc),np.linspace(right,far,nr+1)[1:]]
            result.append((label,xx,3))
    plans=[]
    for name,xx,segments in result:
        if len(xx)!=n or np.min(np.diff(xx))<step:continue
        plans.append({'id':name,'range_mm':[float(xx[0]),float(xx[-1])],'points':n,'step_mm':float(np.min(np.diff(xx))),
            'max_step_mm':float(np.max(np.diff(xx))),'prediction_x_mm':xx.tolist(),'conditions':m.physical(settings),
            'source_kind':'PREDICTION_NOT_OBSERVATION','cost':{'points':n,'position_changes':n-1,'travel_mm':float(xx[-1]-xx[0]),'uniform_segments':segments,'exposures':n,'data_groups':1},
            'cost_note':'分段模板需要仪器支持指定位置或分段扫描；移动耗时及曝光时长未知，相同点数不等于相同总成本。'})
    if not plans:raise ValueError('声明的步距与范围不能容纳这些有限模板')
    return plans


def information(groups,settings,candidate,new_x=None,prediction_region=None,*,future_assumption=None):
    """Weighted finite differences; SVD projects nuisance, then scaled physical SVD."""
    import numpy as np
    from .observation_contract import INDEPENDENT, validate_noise, residual_divisor, protocol_description
    if settings['weighting']==INDEPENDENT:m.validate(groups,settings)
    old_names,_,_=m.layout(groups,settings);allgroups=list(groups)
    assumption=future_assumption or {'noise_multiplier':1.,'amplitude_multiplier':1.}
    if set(assumption)!={'noise_multiplier','amplitude_multiplier'} or any(not m.finite(v) or not .1<=v<=10 for v in assumption.values()):raise ValueError('未来灵敏度假设仅支持公开的有限噪声/亮度倍率')
    if new_x is not None:
        future={'dataset':{'x_mm':list(new_x),'rows':len(new_x)},'scale':groups[-1]['scale']*assumption['noise_multiplier']}
        if 'observation' in groups[-1]:future['observation']=copy.deepcopy(groups[-1]['observation'])
        if settings['weighting']==INDEPENDENT:
            if 'future_noise' not in settings:raise ValueError('独立噪声规划需要明确 future_noise；不能把旧数值尺度当成未来真实噪声')
            future['noise']=copy.deepcopy(validate_noise(settings['future_noise'],len(new_x),future=True))
            sigma=future['noise']['sigma'];factor=assumption['noise_multiplier']
            future['noise']['sigma']=[v*factor for v in sigma] if isinstance(sigma,list) else sigma*factor
        allgroups.append(future)
    names,lo,hi=m.layout(allgroups,settings);theta=[]
    for key in names:
        if key in candidate:theta.append(candidate[key])
        else:theta.append(candidate[key.rsplit('@',1)[0]+'@'+str(len(groups)-1)])
    theta=np.asarray(theta);span=np.asarray(hi)-lo;calls=0
    future_amplitude='amplitude@'+str(len(groups))
    if new_x is not None and future_amplitude in names:
        i=names.index(future_amplitude);theta[i]=np.clip(theta[i]*assumption['amplitude_multiplier'],lo[i],hi[i])
    def signal(v):
        nonlocal calls
        parts=[]
        for j,g in enumerate(allgroups):
            ds=g['dataset'];xx=np.asarray(ds['x_mm']);mask=np.arange(len(xx))%5!=0
            # Future data uses the same preregistered interleaved training split.
            scale=np.asarray(ds['sd_um'])[mask] if ds.get('sd_um') else g['scale']
            prediction=m.predict_observation(xx[mask],m.values(v,names,settings,j),settings['model'],g)
            parts.append(prediction/residual_divisor(g,mask,settings) if settings['weighting']==INDEPENDENT else prediction/scale/np.sqrt(mask.sum()))
            observation=g.get('observation',{});calls+=len(observation['kernel']['weights']) if observation.get('kind')=='CALIBRATED_INTENSITY_AVERAGE' else 1
        return np.concatenate(parts)
    columns=[]
    for i in range(len(names)):
        h=max(span[i]*1e-5,abs(theta[i])*1e-6,1e-8);a=theta.copy();b=theta.copy()
        a[i]=max(lo[i],theta[i]-h);b[i]=min(hi[i],theta[i]+h)
        columns.append((signal(b)-signal(a))/(b[i]-a[i])*span[i])
    jac=np.column_stack(columns);keys=[k for k in physical(settings['model']) if k in names]
    pi=[names.index(k) for k in keys];ni=[i for i in range(len(names)) if i not in pi];J=jac[:,pi]
    if ni:
        U,s,_=np.linalg.svd(jac[:,ni],full_matrices=False);rank=int(np.sum(s>max(s[0]*1e-10,1e-12))) if len(s) else 0
        J=J-U[:,:rank]@(U[:,:rank].T@J)
    if not pi:return {'scales':{},'prediction_scale':0.,'rank':0,'physical_dimensions':0,'prediction_calls':calls}
    U,s,Vh=np.linalg.svd(J,full_matrices=False);rank=int(np.sum(s>max(s[0]*1e-9,1e-12))) if len(s) else 0
    good=rank==len(pi)
    cov=(Vh.T*(1/np.maximum(s,1e-150)**2))@Vh if good else None
    scales={k:float(np.sqrt(max(cov[i,i],0))*span[pi[i]]) if good else None for i,k in enumerate(keys)}
    pred=None
    if prediction_region is not None and good:
        xx=np.linspace(*prediction_region,31);pars=m.values(theta,names,settings,0)
        # Prediction of physical shape/radius; free brightness/background normalized, fixed values retained.
        if settings['model']==m.SLIT:
            if 'amplitude' not in settings['fixed']:pars['amplitude']=1.
            if 'background' not in settings['fixed']:pars['background']=0.
        G=[]
        for i,k in enumerate(keys):
            h=max(span[pi[i]]*1e-5,1e-8);a=pars.copy();b=pars.copy();a[k]-=h;b[k]+=h
            G.append((m.predict(xx,b,settings['model'])-m.predict(xx,a,settings['model']))/(2*h)*span[pi[i]]);calls+=2
        G=np.column_stack(G);pred=float(np.sqrt(max(0,np.mean(np.einsum('ij,jk,ik->i',G,cov,G)))))
    result={'scales':scales,'prediction_scale':pred,'rank':rank,'physical_dimensions':len(pi),'prediction_calls':calls}
    if settings['weighting']!= 'EQUAL_DATASET_TRAINING_COUNT' or future_assumption is not None:
        result['statistical_protocol']=protocol_description(settings)
        result['future_assumption']=dict(assumption,source='PUBLIC_SENSITIVITY_ASSUMPTION_NOT_OBSERVED_FACT') if new_x is not None else None
    return result


def disagreement(xx,settings,pool,names,shift=0.,*,group=None):
    import numpy as np
    curves=[]
    for c in pool:
        p=m.values([c[n] for n in names],names,settings)
        if settings['model']==m.SLIT:
            if 'amplitude' not in settings['fixed']:p['amplitude']=1.
            if 'background' not in settings['fixed']:p['background']=0.
        curves.append(m.predict_observation(xx,p,settings['model'],group) if group is not None else m.predict(xx,p,settings['model']))
    scores=[];xx=np.asarray(xx)
    for i,a in enumerate(curves):
        for b in curves[i+1:]:
            errors=[]
            for offset_mm in np.linspace(-shift,shift,9) if shift else [0.]:
                valid=(xx+offset_mm>=xx[0])&(xx+offset_mm<=xx[-1])
                if valid.sum()<max(3,len(xx)//2):continue
                aa=a[valid];bb=np.interp(xx[valid]+offset_mm,xx,b)
                errors.append(alignment_error(aa,bb,settings))
            if errors:scores.append(min(errors))
    return float(np.mean(scores)) if scores else 0.,{'min':np.min(curves,axis=0).tolist(),'max':np.max(curves,axis=0).tolist()}


def alignment_error(a,b,settings):
    import numpy as np
    if settings['model']==m.SLIT:
        gain='amplitude' not in settings['fixed'];offset='background' not in settings['fixed']
        if gain and offset:
            coef=np.linalg.lstsq(np.c_[a,np.ones(len(a))],b,rcond=None)[0];v=max(0,float(coef[0]))*a;v+=np.mean(b-v)
        elif gain:
            bg=settings['fixed']['background'];q=a-bg;v=bg+max(0,float(np.dot(q,b-bg)/max(np.dot(q,q),1e-300)))*q
        elif offset:v=a+np.mean(b-a)
        else:v=a
    else:v=a
    return float(np.mean((b-v)**2))


def propose(groups,settings,fit,profiles,constraints,research_goal=None,*,mixed=True,scoring='goal'):
    import numpy as np
    m.validate(groups,settings);target=goal(settings['model'],research_goal)
    pool,evidence=candidates(groups,settings,fit,profiles);plans=templates(groups,settings,constraints,mixed)
    names,_,_=m.layout(groups,settings);keys=[k for k in physical(settings['model']) if k in settings['bounds']]
    region=target['prediction_region_mm'] or [groups[0]['dataset']['x_mm'][0],groups[0]['dataset']['x_mm'][-1]]
    if settings['model']==m.SLIT and max(map(abs,region))/settings['fixed']['focal_length_mm']>.1:raise ValueError('预测目标区间超出近轴模型')
    # Explicit public normalization, not an inferred measurement tolerance.
    normal={k:target['tolerances'].get(k,{'slit_width_um':1.,'slit_separation_um':.1,'waist_radius_um':1.,'waist_z_mm':5.}[k]) for k in keys}
    base=[information(groups,settings,c,None,region) for c in pool];calls=sum(r['prediction_calls'] for r in base)
    for plan in plans:
        info=[information(groups,settings,c,plan['prediction_x_mm'],region) for c in pool];calls+=sum(r['prediction_calls'] for r in info)+len(pool)
        worst={k:max(r['scales'][k] for r in info) if all(r['scales'][k] is not None for r in info) else None for k in keys}
        pred=max(r['prediction_scale'] for r in info) if all(r['prediction_scale'] is not None for r in info) else None
        score,envelope=disagreement(plan['prediction_x_mm'],settings,pool,names,constraints['registration_uncertainty_mm'],group=groups[-1])
        plan.update(score=score,prediction_envelope=envelope,local_scales=worst,prediction_scale=pred,local_by_candidate=info)
        selected={'width':'slit_width_um','separation':'slit_separation_um','waist_radius':'waist_radius_um','waist_position':'waist_z_mm'}.get(target['target'])
        if selected and selected not in keys:raise ValueError('目标参数已固定；请明确选择待估参数或预测目标')
        utility=pred if target['target']=='prediction' else worst.get(selected) if selected else max((worst[k]/normal[k] for k in keys),default=None) if all(worst[k] is not None for k in keys) else None
        plan['goal_scale']=utility
        plan['risks']=[]
        if settings['model']==m.SLIT:
            periods=[settings['fixed']['wavelength_nm']*.001*settings['fixed']['focal_length_mm']/(c.get('slit_separation_um',settings['fixed'].get('slit_separation_um'))) for c in pool]
            plan['minimum_samples_per_fringe']=min(periods)/plan['max_step_mm']
            if plan['minimum_samples_per_fringe']<4:plan['risks'].append('部分间隔每条纹少于四点；局部信息评分不能消除混叠风险')
            if max(envelope['max'])-min(envelope['min'])<.05:plan['risks'].append('候选预测信号变化较弱')
        if any(r['rank']<r['physical_dimensions'] for r in info):plan['risks'].append('至少一个候选的局部物理信息秩不足')
    def vector(p):return [p['local_scales'].get(k) if p['local_scales'].get(k) is not None else float('inf') for k in keys]+[p['prediction_scale'] if p['prediction_scale'] is not None else float('inf'),-p['score'],p['cost']['travel_mm'],p['cost']['uniform_segments']]
    for p in plans:
        v=vector(p);p['dominated']=any(all(a<=b for a,b in zip(vector(q),v)) and any(a<b for a,b in zip(vector(q),v)) for q in plans if q is not p)
    feasible=[p for p in plans if not p['dominated'] and p['goal_scale'] is not None]
    if scoring=='legacy':selected=max(plans,key=lambda p:p['score']) if len(pool)>1 else None
    elif scoring=='goal':selected=min(feasible,key=lambda p:(p['goal_scale'],-p['score'],p['cost']['travel_mm'])) if feasible else None
    else:raise ValueError('未知评分方式')
    fallback=not selected
    if fallback:selected=plans[0]
    result={'schema':'photonguard.measurement-plan.v2','research_goal':target,'normalization':normal,'constraints':constraints,'plans':plans,
        'recommended_id':selected['id'],'recommendation_kind':'FIXED_BASELINE_NOT_ADAPTIVE' if fallback else 'LOCAL_ONLY' if len(pool)==1 or 'UNRESOLVED' in evidence['status'] else 'FINITE_CANDIDATE_GOAL_HEURISTIC',
        'candidate_evidence':evidence,'candidate_parameters':pool,'baseline_information':base,'fit_result_id':fit['id'],'profile_result_ids':[p['id'] for p in profiles.values()],
        'input_diagnostic_warnings':fit.get('warnings',[]),'model_assumption_status':'USER_DECLARED_NOT_EXPERIMENTALLY_VERIFIED',
        'score_definition':'分别比较参数的预测尺度、预测差异和采样成本，排除各方面均不占优的方案，再按研究目标选择。允许亮度、背景及声明的配准差异；跨保留候选取保守的局部评分。',
        'limitations':['预测尺度不是置信区间或精度保证；局部线性化可能漏掉远处模式','双缝区间预测针对归一化形状：自由幅度/背景归一，中心固定在各候选的参考位置，仅传播物理参数；不是任意曝光及未知中心下的原始强度预测','未来扫描尺度与亮度使用最近一组的声明尺度/估计作为规划假设；实际曝光改变须重新核对','按每组训练点数归一化；新增数据沿用每五点留一，非独立验证','soft_l1 拟合时规划使用声明尺度的线性灵敏度代理','混合位置合为一个稳定扫描；若曝光或配准改变，应分别上传为独立组','没有全局最优性保证；候选分歧与参数精度可能冲突'],
        'resources':{'analytical_prediction_calls':calls,'candidate_count':len(pool),'templates':len(plans),'model_calls':0,'fft_calls':0,'fdtd_calls':0}}
    result['sha256']=digest(result);return result
