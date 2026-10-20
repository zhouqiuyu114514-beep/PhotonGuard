"""Three finite, public-evidence-only acquisition proposals; analytical predictions."""
from ..core import digest
from . import inverse_models as models


def propose(group, settings, fit, profiles, constraints):
    import numpy as np
    if settings['model']!=models.SLIT:raise ValueError('当前补采建议仅支持双缝数据')
    required={'max_abs_x_mm','points','min_step_mm','allow_extension','stable_exposure_background','registration_uncertainty_mm'}
    if not isinstance(constraints,dict) or set(constraints)!=required:raise ValueError('请明确补采范围、点数、步距、曝光与配准条件')
    cap=constraints['max_abs_x_mm'];n=constraints['points'];step=constraints['min_step_mm'];shift=constraints['registration_uncertainty_mm']
    if not models.finite(cap) or not 0<cap<=1000 or type(n) is not int or not 20<=n<=201 or not models.finite(step) or step<=0 or not models.finite(shift) or not 0<=shift<=cap:
        raise ValueError('补采参数无效：20–201 点，有限正范围及步距')
    if any(type(constraints[k]) is not bool for k in ('allow_extension','stable_exposure_background')):raise ValueError('请明确补采及曝光条件')
    if not constraints['stable_exposure_background']:raise ValueError('本轮要求每次扫描内曝光和背景稳定；不同扫描间允许独立变化')
    if settings['registration']=='INDEPENDENT' and shift<=0:raise ValueError('独立坐标需声明可容忍的中心配准误差')
    if settings['registration']=='SHARED_REGISTERED' and shift!=0:raise ValueError('非零配准不确定性请使用独立中心模式')
    if shift and 'center_shift_mm' in settings['fixed']:raise ValueError('中心已声明固定；不能在补采评分中自动放开配准偏移')
    if not fit.get('estimated_parameters'):raise ValueError('先拟合并计算参数证据曲线')
    names,lo,hi=models.layout(group,settings);lo=np.asarray(lo);hi=np.asarray(hi)
    minimum=min([fit['best_cost']]+[p['best_cost'] for p in profiles.values()]);allowance=max(abs(minimum)*.1,1e-8)
    pool=[]
    for p in profiles.values():
        for row in p['rows']:
            if row.get('accepted') and row.get('parameters') and row['cost']-minimum<=allowance:pool.append(row['parameters'])
    if not pool:raise ValueError('需要保留的剖面候选；不能从单个最佳点编造信息增益')
    if fit['best_cost']-minimum<=allowance:pool.append(fit['estimated_parameters'])
    # Greedy farthest-point thinning, <=12, using parameters alone (no future observations).
    chosen=[pool.pop(0)]
    while pool and len(chosen)<12:
        distance=lambda v:min(float(np.linalg.norm([(v[k]-c[k])/(hi[i]-lo[i]) for i,k in enumerate(names)])) for c in chosen)
        idx=max(range(len(pool)),key=lambda i:distance(pool[i]));v=pool.pop(idx)
        if distance(v)>1e-6:chosen.append(v)
    if len(chosen)<2:raise ValueError('当前仅一个数值候选，无法可靠排名；请核对或加密预先规划的参数网格')
    x=group[0]['dataset']['x_mm'];half=max(abs(x[0]),abs(x[-1]));center=(x[0]+x[-1])/2;span=(x[-1]-x[0])/2
    if cap<half:raise ValueError('允许范围小于原采集范围；请另行说明裁剪目标')
    far=min(cap,.1*settings['fixed']['focal_length_mm']-max(abs(settings['bounds'].get('center_shift_mm',[settings['fixed'].get('center_shift_mm',0)] )[0]),abs(settings['bounds'].get('center_shift_mm',[settings['fixed'].get('center_shift_mm',0)])[-1])))
    ranges=[('repeat',x[0],x[-1])]
    if constraints['allow_extension'] and far>half+1e-9:
        ranges += [('medium',-((half+far)/2),(half+far)/2),('wide',-far,far)]
    plans=[];prediction_calls=0
    for label,left,right in ranges:
        if (right-left)/(n-1)<step:continue
        xx=np.linspace(left,right,n);curves=[]
        for candidate in chosen:
            pars=models.values([candidate[k] for k in names],names,settings,0)
            if 'amplitude' not in settings['fixed']:pars['amplitude']=1.
            if 'background' not in settings['fixed']:pars['background']=0.
            curves.append(models.predict(xx,pars,models.SLIT));prediction_calls+=1
        scores=[]
        for i,a in enumerate(curves):
            for b in curves[i+1:]:
                best=None
                for offset in np.linspace(-shift,shift,9) if shift else [0.]:
                    valid=(xx+offset>=xx[0])&(xx+offset<=xx[-1])
                    if valid.sum()<max(3,n//2):continue
                    aa=a[valid];bb=np.interp(xx[valid]+offset,xx,b)
                    free_gain='amplitude' not in settings['fixed'];free_background='background' not in settings['fixed']
                    if free_gain and free_background:
                        mat=np.column_stack([aa,np.ones(len(aa))]);coef=np.linalg.lstsq(mat,bb,rcond=None)[0]
                        gain=max(0.,float(coef[0]));aligned=gain*aa+float(np.mean(bb-gain*aa))
                    elif free_background:aligned=aa+float(np.mean(bb-aa))
                    elif free_gain:
                        offset_known=settings['fixed']['background'];a0=aa-offset_known;b0=bb-offset_known
                        gain=max(0.,float(np.dot(a0,b0)/max(np.dot(a0,a0),1e-300)));aligned=gain*a0+offset_known
                    else:aligned=aa
                    error=float(np.mean((bb-aligned)**2))
                    best=error if best is None else min(best,error)
                if best is not None:scores.append(best)
        plans.append({'id':label,'range_mm':[float(left),float(right)],'points':n,'step_mm':float(xx[1]-xx[0]),
                      'score':float(np.mean(scores)) if scores else 0.,'prediction_x_mm':xx.tolist(),
                      'prediction_envelope':{'min':np.min(curves,axis=0).tolist(),'max':np.max(curves,axis=0).tolist()},
                      'conditions':models.physical(settings),'source_kind':'PREDICTION_NOT_OBSERVATION'})
    if not plans:raise ValueError('当前步距与范围不能容纳指定点数，未改变用户条件')
    maximum=max(r['score'] for r in plans);selected=next(r['id'] for r in plans if r['score']==maximum)
    result={'schema':'photonguard.measurement-plan.v1','constraints':constraints,'plans':plans,'recommended_id':selected,
            'candidate_parameters':chosen,'fit_result_id':fit['id'],'profile_result_ids':[p['id'] for p in profiles.values()],
            'candidate_cost_rule':{'shared_minimum':minimum,'allowance':allowance,'note':'各参数剖面合并后使用同一个代价基准，不带入已不相近的旧最佳点'},
            'alignment_roles':{'amplitude_free':'amplitude' not in settings['fixed'],'background_free':'background' not in settings['fixed'],'center_shift_bound_mm':shift},
            'score_definition':'候选形状在允许的正幅度/背景对齐及有限中心配准后，平均平方预测分歧；未使用未来数据或真值',
            'limitations':['启发式，不保证最优或消除退化；候选可能未覆盖真实参数','固定点数下扩大范围会增大步距：包络覆盖可能改善，但缝距精度可能下降，请比较三个方案','相同 q=(x-x0)/(λf) 范围的等比例变换不会天然增加形状信息','相同点数；预测包络不是测量数据，也不是置信带'],
            'resources':{'analytical_prediction_calls':prediction_calls,'candidate_count':len(chosen),'model_calls':0,'fft_calls':0,'fdtd_calls':0}}
    result['sha256']=digest(result);return result
