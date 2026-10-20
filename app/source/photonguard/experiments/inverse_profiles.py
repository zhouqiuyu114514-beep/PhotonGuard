"""Bounded multistart fits and sampled local profiles, with failed points retained."""
import time
from ..core import digest
from . import inverse_models as models


def components(rows):
    """Do not bridge rejected or uncomputed grid points."""
    groups=[];current=[]
    for row in rows:
        if row.get('accepted'):
            current.append(row['value'])
        elif current:groups.append(current);current=[]
    if current:groups.append(current)
    return groups


def run(p, progress=None, reference=None):
    if p.get('model')==models.FILM:
        from .film_inverse import run as film_run
        return film_run(p,progress)
    import numpy as np
    import scipy
    from scipy.optimize import least_squares
    from .observation_contract import INDEPENDENT, LEGACY, residual_divisor, protocol_description, assessment
    models.verify_plan(p)
    if p['operation']=='profile' and digest(reference)!=p['reference_sha256']:raise ValueError('剖面参考结果发生变化')
    if p['operation']=='profile' and (reference.get('model')!=p['model'] or reference.get('plan_sha256')!=models.plan(p['groups'],p['settings'])['sha256']):raise ValueError('剖面参考拟合与本组数据或设置不一致')
    settings=p['settings'];groups=p['groups'];budget=p['budget'];names,lower,upper=models.layout(groups,settings)
    lo=np.asarray(lower);hi=np.asarray(upper);began=time.monotonic();calls=0;starts=[];rows=[];best_raw=None
    masks=[]
    for g,split in zip(groups,p['splits']):
        mask=np.ones(g['dataset']['rows'],dtype=bool);mask[split['holdout_indices']]=False;masks.append(mask)
    class Stop(Exception):pass
    def residual(theta):
        nonlocal calls
        if calls>=budget['max_residual_calls'] or time.monotonic()-began>=budget['seconds']-1:raise Stop()
        calls+=1;parts=[]
        for j,(g,mask) in enumerate(zip(groups,masks)):
            ds=g['dataset'];x=np.asarray(ds['x_mm']);y=np.asarray(ds['intensity'] if p['model']==models.SLIT else ds['radius_um'])
            scale=np.asarray(ds['sd_um'])[mask] if p['model']==models.GAUSSIAN and ds.get('sd_um') else g['scale']
            delta=models.predict_observation(x[mask],models.values(theta,names,settings,j),p['model'],g)-y[mask]
            parts.append(delta/residual_divisor(g,mask,settings) if settings['weighting']==INDEPENDENT else delta/scale/np.sqrt(mask.sum()))
        return np.concatenate(parts)
    def solve(fixed_index=None, fixed_value=None, start_count=9):
        nonlocal best_raw
        free=np.ones(len(names),dtype=bool)
        if fixed_index is not None:free[fixed_index]=False
        best=None;raw=None
        for index in range(start_count):
            seed=(lo+hi)/2
            # Cover both physical unknowns (not only a single nuisance direction).
            for axis,k in enumerate(('slit_width_um','slit_separation_um') if p['model']==models.SLIT else models.GAUSSIAN_PARAMETERS):
                if k in names:
                    fraction=(.2,.5,.8)[(index//3 if axis==0 else index%3)] if start_count==9 else (.35,.65)[index]
                    seed[names.index(k)]=lo[names.index(k)]+fraction*(hi[names.index(k)]-lo[names.index(k)])
            if reference and start_count==2 and index==0:
                for i,k in enumerate(names):seed[i]=reference['estimated_parameters'].get(k,seed[i])
            if fixed_index is not None:seed[fixed_index]=fixed_value
            seed=np.clip(seed,lo,hi);before=calls
            row={'start':index+1,'profile_value':fixed_value,'initial':dict(zip(names,map(float,seed)))}
            def fun(v):
                theta=seed.copy();theta[free]=v;return residual(theta)
            try:
                if free.any():
                    opt=least_squares(fun,seed[free],bounds=(lo[free],hi[free]),loss=settings['loss'],f_scale=settings['f_scale'],
                       x_scale=(hi-lo)[free],max_nfev=budget['max_nfev'],ftol=1e-9,xtol=1e-9,gtol=1e-9)
                    theta=seed.copy();theta[free]=opt.x
                    row.update(success=bool(opt.success),cost=float(opt.cost),parameters=dict(zip(names,map(float,theta))),reported_nfev=int(opt.nfev),optimizer_status=int(opt.status))
                else:
                    r=fun([]);cost=.5*np.sum(r*r) if settings['loss']=='linear' else settings['f_scale']**2*np.sum(np.sqrt(1+(r/settings['f_scale'])**2)-1)
                    opt=None;theta=seed;row.update(success=True,cost=float(cost),parameters=dict(zip(names,map(float,theta))),reported_nfev=1,optimizer_status=1)
                row['boundary_parameters']=[k for i,k in enumerate(names) if free[i] and min(theta[i]-lo[i],hi[i]-theta[i])/(hi[i]-lo[i])<.001]
                if row['success'] and (best is None or row['cost']<best['cost']):best=row;raw=opt
            except Stop:row.update(success=False,status='RESOURCE_STOP')
            except (ValueError,FloatingPointError,OverflowError):row.update(success=False,status='NUMERICAL_FAILURE')
            row['actual_residual_calls']=calls-before;starts.append(row)
            if progress:progress({'starts':starts,'profile_rows':rows,'actual_residual_calls':calls,'plan_sha256':p['sha256']})
            if row.get('status')=='RESOURCE_STOP':break
        best_raw=raw;return best
    result={'schema':'photonguard.inverse-result.v1','operation':p['operation'],'model':p['model'],'plan_sha256':p['sha256'],
            'source_kind':'MODEL_ESTIMATE','engine':{'scipy':scipy.__version__,'numpy':np.__version__,'method':'bounded local least_squares'},
            'status':'NO_CONVERGENCE','usable_for_forward':False,'warnings':[],'confidence_interval':None,
            'data_use':p['splits'],'weighting':{'rule':settings['weighting'],'scales':[{'value':g['scale'],'source':g['scale_source'],
                 'per_point_sd_from_csv':bool(g['dataset'].get('sd_um')),'effective_source':'CSV_DECLARED_MEASUREMENT_SD' if g['dataset'].get('sd_um') else g['scale_source']} for g in groups]},
            'limitations':['仅声明的物理模型、范围、起点及有限网格；不证明全局唯一','同扫描留出不是独立实测验证','数值尺度与候选显示阈值不是仪器精度或置信水平']}
    if settings['weighting']!=LEGACY or any('observation' in g or 'noise' in g for g in groups):
        result['statistical_protocol']=protocol_description(settings)
        result['observation_assessment']=[assessment(g) for g in groups]
        if settings['weighting']==INDEPENDENT:
            result['weighting']['scales']=[{'sigma':g['noise']['sigma'],'source':g['noise']['source'],'reference':g['noise']['reference'],'acquisition_id':g['noise']['acquisition_id'],'independent':True} for g in groups]
    if p['operation']=='profile':
        key=p['profile']['parameter'];axis=names.index(key);n=p['profile']['grid_points']
        for value in p['profile']['grid']:
            best=solve(axis,float(value),2)
            rows.append({'value':float(value),'success':bool(best),'cost':best['cost'] if best else None,
                         'parameters':best['parameters'] if best else None,'boundary_parameters':best.get('boundary_parameters',[]) if best else [],
                         'status':'CONVERGED' if best else 'UNRESOLVED'})
        successes=[r for r in rows if r['success']]
        minimum=min([r['cost'] for r in successes]+[reference['best_cost']]);rule=p['profile']['display_rule']
        allowance=max(abs(minimum)*rule['relative_cost_allowance'],rule['absolute_cost_floor'])
        for r in rows:
            r.update(relative_cost=r['cost']-minimum if r['success'] else None,
                     accepted=bool(r['success'] and r['cost']-minimum<=allowance))
        blocks=components(rows);flags=[];accepted=[r for r in rows if r['accepted']]
        if len(successes)<len(rows):flags.append('UNRESOLVED_PROFILE_POINTS')
        if reference['best_cost']-minimum>allowance:flags.append('REFERENCE_OUTSIDE_PROFILE_SET')
        if not accepted:flags.append('GRID_MISSES_BEST_REGION')
        if len(blocks)>1 or accepted and (accepted[-1]['value']-accepted[0]['value'])/(hi[axis]-lo[axis])>.1:flags.append('MULTIPLE_PROFILE_CANDIDATES')
        if rows[0]['accepted'] or rows[-1]['accepted'] or accepted and all(r['boundary_parameters'] for r in accepted):flags.append('PROFILE_BOUNDARY')
        result.update(status='PROFILE_REVIEW' if flags else 'PROFILE_SAMPLED',warnings=flags,parameter=key,rows=rows,components=blocks,
                      best_cost=minimum,cost_allowance=allowance,display_rule=rule,
                      grid_spacing=float(max(np.diff(p['profile']['grid']))),grid=p['profile']['grid'],grid_rule=p['profile']['grid_rule'],
                      note='单个保留格点不代表零不确定性；分离片段及失败点原样保留。候选不是置信区间。')
    else:
        best=solve(start_count=9)
        if best:
            theta=np.array([best['parameters'][k] for k in names]);flags=[];data=[];diagnostics={}
            if best['boundary_parameters']:flags.append('BOUNDARY_HIT')
            if best_raw is not None:
                jac=best_raw.jac;sv=np.linalg.svd(jac/np.maximum(np.linalg.norm(jac,axis=0),1e-300),compute_uv=False)
                condition=float(min(1e300,sv[0]/max(sv[-1],1e-300))) if len(sv) else 1e300
                diagnostics['scaled_jacobian_condition']=condition
                if condition>1e6:flags.append('INSUFFICIENT_INFORMATION')
            comparable=[r for r in starts if r.get('success') and r['cost']<=best['cost']*1.1+1e-8 and max(abs(r['parameters'][k]-best['parameters'][k])/(hi[i]-lo[i]) for i,k in enumerate(names))>.05]
            if comparable:flags.append('MULTIPLE_COMPARABLE_SOLUTIONS')
            diagnostics['comparable_starts']=[r['start'] for r in comparable];diagnostics['boundary_parameters']=best['boundary_parameters']
            spans=[]
            for j,(g,mask) in enumerate(zip(groups,masks)):
                ds=g['dataset'];x=np.asarray(ds['x_mm']);y=np.asarray(ds['intensity'] if p['model']==models.SLIT else ds['radius_um'])
                pars=models.values(theta,names,settings,j);pred=models.predict_observation(x,pars,p['model'],g);err=y-pred
                scale=max(float(np.quantile(y,.95)-np.quantile(y,.05)),1e-12)
                normalized=float(np.sqrt(np.mean(err[~mask]**2))/scale)
                corr=float(np.corrcoef(err[:-1],err[1:])[0,1]) if np.std(err)>1e-12 else 0.
                if not np.isfinite(corr):corr=0.
                if normalized>.12 or abs(corr)>.7 and normalized>.02:flags.append('POSSIBLE_MODEL_MISMATCH')
                if p['model']==models.SLIT:
                    period=pars['wavelength_nm']*.001*pars['focal_length_mm']/pars['slit_separation_um']
                    envelope=pars['wavelength_nm']*.001*pars['focal_length_mm']/pars['slit_width_um']
                    spans.append({'fringe_periods':float(np.ptp(x)/period),'envelope_fraction':float(np.ptp(x)/envelope)})
                    if np.max(np.diff(x))>period/4 or np.ptp(y)<1e-8:flags.append('INSUFFICIENT_SAMPLING')
                else:
                    zr=np.pi*(pars['waist_radius_um']*.001)**2/(pars['wavelength_nm']*1e-6)
                    spans.append({'rayleigh_span':float(np.ptp(x)/zr),'waist_bracketed':bool(x[0]<pars['waist_z_mm']<x[-1])})
                data.append({'dataset_sha256':ds['sha256'],'x':x.tolist(),'observed':y.tolist(),'predicted':pred.tolist(),'residual':err.tolist(),'holdout':(~mask).tolist(),
                             'training_rmse':float(np.sqrt(np.mean(err[mask]**2))),'holdout_rmse':float(np.sqrt(np.mean(err[~mask]**2))),
                             'holdout_normalized_rmse':normalized,'residual_lag1_correlation':corr,'local_parameters':pars})
            if p['model']==models.SLIT:
                if max(v['fringe_periods'] for v in spans)<3:flags.append('INSUFFICIENT_FRINGE_COVERAGE')
                if 'slit_width_um' in settings['bounds'] and max(v['envelope_fraction'] for v in spans)<.5:flags.append('INSUFFICIENT_WIDTH_COVERAGE')
            else:
                all_x=[v for g in groups for v in g['dataset']['x_mm']]
                if (max(all_x)-min(all_x))/zr<1 or not min(all_x)<pars['waist_z_mm']<max(all_x):flags.append('INSUFFICIENT_CAUSTIC_COVERAGE')
            if any(r.get('status')=='RESOURCE_STOP' for r in starts):flags.append('RESOURCE_STOP')
            diagnostics['coverage']=spans
            result.update(status='ESTIMATE_READY' if not flags else 'NEEDS_REVIEW',usable_for_forward=not flags,warnings=sorted(set(flags)),
                          best_cost=best['cost'],estimated_parameters=best['parameters'],diagnostics=diagnostics,data=data)
    result['starts']=starts;result['resources']={'actual_residual_calls':calls,'local_optimizations':len(starts),'elapsed_seconds':time.monotonic()-began,
            'model_calls':0,'fft_calls':0,'fdtd_calls':0,'prediction_calls_outside_optimizer':len(groups) if p['operation']=='fit' and result.get('data') else 0}
    result['id']=digest(result);return result
