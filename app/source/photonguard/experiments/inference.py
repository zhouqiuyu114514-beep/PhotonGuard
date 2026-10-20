"""Bounded local four-parameter fit; estimates, not unique physical measurements."""
import copy
import math
import time
from ..core import digest

MODEL = 'double_slit_zero_phase_focal_line_v1'
NAMES = ['slit_separation_um','center_shift_mm','amplitude','background']
FIXED = ['wavelength_nm','focal_length_mm','slit_width_um','relative_phase_rad','measurement_plane']
LIMITS = {'starts':9,'max_nfev':200,'max_residual_calls':12000,'seconds':60,'memory_mib':1024,'output_mib':32}


def finite(v):return type(v) in (int,float) and math.isfinite(v)


def issues(dataset, settings):
    problems = list(dataset['questions'])
    missing = []
    if not isinstance(settings,dict) or set(settings)-{'fixed','bounds','loss','f_scale','budget'}:
        return ['拟合设置字段无效'], FIXED + NAMES
    fixed = settings.get('fixed',{})
    if not isinstance(fixed,dict) or set(fixed)-set(FIXED):return ['固定条件字段无效'], FIXED
    missing.extend(k for k in FIXED if k not in fixed or fixed[k] is None or fixed[k]=='')
    if missing:problems.append('待确认固定条件：'+', '.join(missing))
    if fixed.get('measurement_plane') not in (None,'','FOURIER_FOCAL_PLANE'):
        problems.append('当前仅支持理想透镜傅里叶焦平面；不能替代自由传播近场模型')
    if fixed.get('relative_phase_rad') not in (None,'') and (not finite(fixed['relative_phase_rad']) or fixed['relative_phase_rad']!=0):
        problems.append('首版仅支持相对相位明确为 0；相位不是待估参数')
    for key,lo,hi in [('wavelength_nm',200,2000),('focal_length_mm',1,10000),('slit_width_um',1,5000)]:
        v=fixed.get(key)
        if v not in (None,'') and (not finite(v) or not lo<=v<=hi):problems.append('固定参数范围无效：'+key)
    bounds=settings.get('bounds',{})
    if not isinstance(bounds,dict) or set(bounds)-set(NAMES):return problems+['只允许估计缝距、中心偏移、幅度、背景'],missing+NAMES
    for k in NAMES:
        b=bounds.get(k)
        if not isinstance(b,list) or len(b)!=2 or not all(finite(v) and abs(v)<=1e6 for v in b) or b[0]>=b[1]:
            problems.append('需要有限且递增的参数范围：'+k);missing.append(k)
    if not problems:
        if bounds[NAMES[0]][0] <= fixed['slit_width_um'] or bounds[NAMES[0]][1]>10000:problems.append('缝距范围必须大于缝宽且不超过 10000 μm')
        if bounds['amplitude'][0]<=0:problems.append('幅度下界必须为正')
        if fixed['wavelength_nm']*.001/fixed['slit_width_um']>.1:problems.append('缝宽不满足本模型的近轴范围')
        x=dataset['x_mm'];shift=bounds['center_shift_mm']
        if max(abs(x[0]-shift[1]),abs(x[-1]-shift[0]))/fixed['focal_length_mm']>.1:problems.append('观测位置超出声明的近轴范围')
    if settings.get('loss') not in ('linear','soft_l1'):problems.append('请选择 linear 或 soft_l1 损失')
    if not finite(settings.get('f_scale')) or not 1e-9<=settings['f_scale']<=1e6:problems.append('请明确有效的残差尺度 f_scale')
    budget=settings.get('budget',{})
    if not isinstance(budget,dict) or set(budget)-set(LIMITS):problems.append('资源上限字段无效')
    elif any(type(v) is not int or not 1<=v<=LIMITS[k] for k,v in budget.items()):problems.append('资源设置超出有界拟合上限')
    return problems, sorted(set(missing))


def plan(dataset, settings):
    problems,_=issues(dataset,settings)
    if problems:raise ValueError('；'.join(problems))
    settings=copy.deepcopy(settings);settings['budget']={**LIMITS,**settings.get('budget',{})}
    value={'schema':'photonguard.observation-plan.v1','model':MODEL,'dataset_sha256':dataset['sha256'],
           'raw_sha256':dataset['raw_sha256'],'settings':settings,
           'split':{'kind':'fixed_before_fit_interleaved','holdout_indices':list(range(0,dataset['rows'],5)),
                    'note':'每五个点留出一个，不独立于同一次采集；不用于选择起点'},
           'parameter_order':NAMES,'source_kind':'MODEL_ESTIMATE',
           'assumptions':['uniform coherent illumination; equal-width rectangular double slits; phase zero',
              'ideal thin lens Fourier focal plane; scalar paraxial central line',
              'four unknowns only; amplitude and background are observation nuisance parameters',
              'no confidence interval, global-optimum proof or independent measurement certification']}
    value['sha256']=digest(value)
    return value


def predict(x, theta, fixed):
    import numpy as np
    d,shift,amplitude,background=theta
    q=(np.asarray(x)-shift)/(fixed['wavelength_nm']*1e-6*fixed['focal_length_mm'])
    return background+amplitude*np.sinc(fixed['slit_width_um']*.001*q)**2*np.cos(np.pi*d*.001*q)**2


def fit(dataset, approved_plan, progress=None):
    import numpy as np
    import scipy
    from scipy.optimize import least_squares
    if plan(dataset,approved_plan['settings'])!=approved_plan:raise ValueError('拟合计划与数据不一致')
    started=time.monotonic();settings=approved_plan['settings'];budget=settings['budget'];fixed=settings['fixed']
    x=np.asarray(dataset['x_mm']);y=np.asarray(dataset['intensity']);test=np.zeros(len(x),dtype=bool)
    test[approved_plan['split']['holdout_indices']]=True
    lo,hi=np.array([settings['bounds'][k] for k in NAMES]).T
    calls=0;starts=[];best_raw=None;best=None
    class BudgetStop(Exception):pass
    def residual(theta):
        nonlocal calls
        if calls>=budget['max_residual_calls'] or time.monotonic()-started>=budget['seconds']:
            raise BudgetStop()
        calls+=1
        return predict(x[~test],theta,fixed)-y[~test]
    for index,d0 in enumerate(np.linspace(lo[0]+(hi[0]-lo[0])*.02,hi[0]-(hi[0]-lo[0])*.02,budget['starts'])):
        seed=(lo+hi)/2;seed[0]=d0;before=calls
        row={'start':index+1,'initial':seed.tolist()}
        try:
            r=least_squares(residual,seed,bounds=(lo,hi),loss=settings['loss'],f_scale=settings['f_scale'],
                            max_nfev=budget['max_nfev'],x_scale=hi-lo,ftol=1e-9,xtol=1e-9,gtol=1e-9)
            row.update(success=bool(r.success),parameters=r.x.tolist(),cost=float(r.cost),optimizer_status=int(r.status),reported_nfev=int(r.nfev))
            if r.success and (best is None or r.cost<best['cost']):best=row;best_raw=r
        except BudgetStop:row.update(success=False,status='RESOURCE_STOP')
        except (ValueError,FloatingPointError):row.update(success=False,status='NUMERICAL_FAILURE')
        row['actual_residual_calls']=calls-before;starts.append(row)
        if progress:progress({'starts':starts,'actual_residual_calls':calls,'plan_sha256':approved_plan['sha256']})
        if row.get('status')=='RESOURCE_STOP':break
    resources={'actual_residual_calls':calls,'reported_nfev_total':sum(r.get('reported_nfev',0) for r in starts),
               'elapsed_seconds':time.monotonic()-started,'starts_attempted':len(starts),'starts_planned':budget['starts'],
               'prediction_calls_outside_optimizer':0,'fft_calls':0,'fdtd_calls':0,'model_calls':0}
    result={'schema':'photonguard.fit-result.v1','id':digest({'plan':approved_plan['sha256'],'starts':starts}),
            'plan_sha256':approved_plan['sha256'],'dataset_sha256':dataset['sha256'],'source_kind':'MODEL_ESTIMATE',
            'engine':{'name':'scipy.optimize.least_squares / bounded local multistart','scipy':scipy.__version__,'numpy':np.__version__},
            'starts':starts,'resources':resources,'assumptions':approved_plan['assumptions'],'confidence_interval':None,
            'status':'NO_CONVERGENCE','usable_for_forward':False,'warnings':[]}
    if best is None:return result
    theta=np.asarray(best['parameters']);predicted=predict(x,theta,fixed);resources['prediction_calls_outside_optimizer']=1
    error=y-predicted
    def metric(mask):return {'count':int(mask.sum()),'rmse':float(np.sqrt(np.mean(error[mask]**2))),
                             'median_absolute_residual':float(np.median(abs(error[mask])))}
    flags=[];period=fixed['wavelength_nm']*.001*fixed['focal_length_mm']/theta[0]
    bound_keys=[k for i,k in enumerate(NAMES) if min(theta[i]-lo[i],hi[i]-theta[i])/(hi[i]-lo[i])<.001]
    if bound_keys:flags.append('BOUNDARY_HIT')
    jac=best_raw.jac;norm=np.linalg.norm(jac,axis=0);scaled=jac/np.maximum(norm,1e-300)
    singular=np.linalg.svd(scaled,compute_uv=False);condition=float(singular[0]/max(singular[-1],1e-300))
    if not math.isfinite(condition):condition=1e300
    if condition>1e6 or (x[-1]-x[0])/period<3 or np.max(np.diff(x))>period/4 or np.ptp(y)<1e-8:flags.append('INSUFFICIENT_INFORMATION')
    comparable=[r['start'] for r in starts if r.get('success') and r['cost']<=best['cost']*1.05+1e-10 and np.max(abs(np.asarray(r['parameters'])-theta)/(hi-lo))>.05]
    if comparable:flags.append('MULTIPLE_COMPARABLE_SOLUTIONS')
    train,holdout=metric(~test),metric(test)
    scale=max(float(np.quantile(y,.95)-np.quantile(y,.05)),1e-12)
    normalized=holdout['rmse']/scale
    corr=float(np.corrcoef(error[:-1],error[1:])[0,1]) if np.std(error)>1e-12 else 0.
    if not math.isfinite(corr):corr=0.
    if normalized>.12 or abs(corr)>.7 and normalized>.02:flags.append('POSSIBLE_MODEL_MISMATCH')
    if len(starts)<budget['starts'] or any(r.get('status')=='RESOURCE_STOP' for r in starts):flags.append('RESOURCE_STOP')
    result.update(status='ESTIMATE_READY' if not flags else 'NEEDS_REVIEW',usable_for_forward=not flags,warnings=flags,
        estimated_parameters=dict(zip(NAMES,map(float,theta))),best_start=best['start'],best_cost=best['cost'],
        diagnostics={'boundary_parameters':bound_keys,'comparable_starts':comparable,'scaled_jacobian_condition':condition,
                     'observed_periods':float((x[-1]-x[0])/period),'holdout_normalized_rmse':normalized,'residual_lag1_correlation':corr,
                     'note':'阈值是预先登记的局部诊断，不证明全局可识别；留出点不参与起点选择'},
        metrics={'training':train,'holdout':holdout},
        data={'x':x.tolist(),'observed':y.tolist(),'predicted':predicted.tolist(),'residual':error.tolist(),'holdout':test.tolist(),
              'x_label':'位置（mm）','y_label':'相对强度','series':[{'label':'原始观测（未清洗）','y':y.tolist(),'points':True},{'label':'模型预测（原始坐标）','y':predicted.tolist()}]})
    return result
