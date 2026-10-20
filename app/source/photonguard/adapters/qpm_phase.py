"""SHG quasi-phase matching factor; never an absolute conversion efficiency."""
import math
import numpy as np
from ..core import digest

POLICY={'version':'qpm-shg-phase-v1','max_length_um':10000,'max_phase_sensitivity_rad':.1,
    'resource_limits':{'max_solver_processes':0,'max_model_requests':0},'immutable_goal':True,'absolute_efficiency_supported':False}

def finite(value):return type(value) in (int,float) and math.isfinite(value)

def beta(wavelength_um,neff):
    if not finite(wavelength_um) or wavelength_um<=0 or not finite(neff) or neff<=0:raise ValueError('波长和有效折射率需要有限正数。')
    return 2*math.pi*neff/wavelength_um

def phase_factor(delta_beta_rad_per_um,length_um):
    if not finite(delta_beta_rad_per_um) or not finite(length_um) or length_um<=0:raise ValueError('失配或长度不合法。')
    return float(np.sinc(delta_beta_rad_per_um*length_um/(2*math.pi))**2)

def qpm_period(pump_um,n_fundamental,n_sh):
    if not all(finite(v) for v in (pump_um,n_fundamental,n_sh)) or pump_um<=0 or n_sh<=n_fundamental:
        raise ValueError('当前一阶正向SHG分支需要n_SH>n_F及正泵浦波长。')
    return pump_um/(2*(n_sh-n_fundamental))

def validate_task(task):
    if set(task)!={'schema_version','adapter','task_id','requirements','modes','provenance'} or task.get('adapter')!='qpm-shg-phase-v1':raise ValueError('QPM任务字段不完整。')
    req=task['requirements']
    if type(req) is not dict or set(req)!={'process','pump_wavelength_um','length_um','poling_period_um','qpm_order','target_phase_factor_min'}:raise ValueError('过程、波长、长度、周期、级次或目标未知。')
    if req['process']!='SHG' or type(req['qpm_order']) is not int or req['qpm_order']!=1:raise ValueError('首版仅一阶正向SHG；不猜实际变频过程。')
    for key in ('pump_wavelength_um','length_um','poling_period_um','target_phase_factor_min'):
        if not finite(req[key]):raise ValueError('物理输入缺失或不是有限数。')
    if not .8<=req['pump_wavelength_um']<=5 or not 0<req['length_um']<=POLICY['max_length_um'] or req['poling_period_um']<=0 or not 0<=req['target_phase_factor_min']<=1:raise ValueError('任务不在明确范围内。')
    modes=task['modes']
    if type(modes) is not list or len(modes)!=2:raise ValueError('需要有来源的基波及倍频模态。')
    for mode,expected in zip(modes,(req['pump_wavelength_um'],req['pump_wavelength_um']/2)):
        if type(mode) is not dict or set(mode)!={'wavelength_um','neff','beta_rad_per_um','mode_id','source_sha256','source','verification_status','neff_sensitivity_estimate'}:raise ValueError('模态身份、来源、验证状态或敏感度未知。')
        if not finite(mode['wavelength_um']) or not math.isclose(mode['wavelength_um'],expected,rel_tol=1e-12):raise ValueError('基波/倍频波长或顺序不一致。')
        if not finite(mode['neff']) or not 1<mode['neff']<5 or not finite(mode['beta_rad_per_um']) or not math.isclose(mode['beta_rad_per_um'],beta(expected,mode['neff']),rel_tol=1e-10):raise ValueError('β与2π*n_eff/λ不一致。')
        if not finite(mode['neff_sensitivity_estimate']) or mode['neff_sensitivity_estimate']<0:raise ValueError('模态误差估计未知；不当作零。')
        if any(type(mode[k]) is not str or not mode[k] for k in ('mode_id','source_sha256','source')) or len(mode['source_sha256'])!=64 or any(c not in '0123456789abcdef' for c in mode['source_sha256']):raise ValueError('模态来源未绑定。')
        if mode['verification_status'] not in ('PASS','IMPORTED_NOT_VERIFIED','INCONCLUSIVE','FAIL'):raise ValueError('模态验证状态不明。')
    if type(task['provenance']) is not dict or not task['provenance'].get('reference'):raise ValueError('需要独立需求出处。')
    if type(task['task_id']) is not str or not task['task_id']:raise ValueError('需要任务ID。')

def evaluate(task,*,verified_mode_sources=None):
    validate_task(task);r=task['requirements'];fund,sh=task['modes']
    bare=sh['beta_rad_per_um']-2*fund['beta_rad_per_um'];grating=2*math.pi/r['poling_period_um'];residual=bare-grating
    factor=phase_factor(residual,r['length_um'])
    estimate=4*math.pi*r['length_um']/r['pump_wavelength_um']*(fund['neff_sensitivity_estimate']+sh['neff_sensitivity_estimate'])
    provenance_verified=True
    for mode in task['modes']:
        receipt=(verified_mode_sources or {}).get(mode['source_sha256']+':'+mode['mode_id'])
        if not receipt or receipt.get('verification_status')!='PASS' or any(receipt.get(key)!=mode[key] for key in ('mode_id','wavelength_um','neff','beta_rad_per_um','neff_sensitivity_estimate')):
            provenance_verified=False
    verified=provenance_verified and all(m['verification_status']=='PASS' for m in task['modes']) and estimate<=POLICY['max_phase_sensitivity_rad']
    status='PASS' if verified else 'INCONCLUSIVE'
    goal=('MET' if factor>=r['target_phase_factor_min'] else 'NOT_MET') if verified else 'NOT_EVALUATED'
    return {'schema_version':1,'adapter':task['adapter'],'task_sha256':digest(task),'policy_sha256':digest(POLICY),
        'verification_status':status,'design_goal_status':goal,'phase_factor_NOT_efficiency':factor,
        'bare_delta_beta_rad_per_um':bare,'grating_K_rad_per_um':grating,'residual_delta_beta_rad_per_um':residual,
        'phase_sensitivity_estimate_rad':estimate,'phase_sensitivity_limit_rad':POLICY['max_phase_sensitivity_rad'],
        'mode_input_statuses':[m['verification_status'] for m in task['modes']],
        'mode_provenance_verified':provenance_verified,'arithmetic_verification_status':'PASS',
        'actual_nonlinear_solver_runs':0,'absolute_efficiency_calculated':False,
        'limitations':['F is a normalized phase-matching factor, not power conversion efficiency',
            'Grid differences are tested sensitivity estimates, not rigorous true-error bounds',
            'No power normalization, nonlinear tensor overlap, depletion, loss or experimental validation',
            'Changing a manufactured poling period is a new design task, not a repair of this immutable task']}
