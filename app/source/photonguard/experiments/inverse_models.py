"""Explicit small inverse models and immutable group/plan contracts."""
import copy
import math
from ..core import digest
from .gaussian_inference import MODEL as GAUSSIAN

SLIT='double_slit_width_spacing_v1'
FILM='single_film_known_index_v1'
MODELS=(SLIT, GAUSSIAN,FILM)
SLIT_PARAMETERS=('slit_width_um','slit_separation_um','center_shift_mm','amplitude','background')
GAUSSIAN_PARAMETERS=('waist_radius_um','waist_z_mm')
LIMITS={'fit':{'starts':9,'max_nfev':200,'max_residual_calls':30000,'seconds':60,'memory_mib':1024},
        'joint':{'starts':9,'max_nfev':200,'max_residual_calls':30000,'seconds':120,'memory_mib':1024},
        'profile':{'starts':2,'max_nfev':200,'max_residual_calls':30000,'seconds':60,'memory_mib':1024}}


def finite(v):return type(v) in (int,float) and math.isfinite(v)


def parameters(model):return ('thickness_nm',) if model==FILM else SLIT_PARAMETERS if model==SLIT else GAUSSIAN_PARAMETERS


def validate(group, settings):
    if isinstance(settings,dict) and settings.get('model')==FILM:
        from .film_inverse import validate as check
        return check(group,settings)
    if not isinstance(settings,dict) or set(settings)-{'model','fixed','bounds','loss','f_scale','f_scale_units','registration','weighting','scale','scale_source','future_noise'}:raise ValueError('反向分析设置字段无效')
    model=settings.get('model');fixed=settings.get('fixed',{});bounds=settings.get('bounds',{})
    if model not in MODELS or not isinstance(fixed,dict) or not isinstance(bounds,dict):raise ValueError('请选择受支持的反向模型')
    names=parameters(model)
    physical=('wavelength_nm','focal_length_mm','relative_phase_rad','measurement_plane') if model==SLIT else ('wavelength_nm','m2','propagation')
    if set(fixed)-set(physical)-set(names) or set(bounds)-set(names):raise ValueError('不允许估计波长、焦距、相位或未支持的量')
    if any(k not in fixed for k in physical):raise ValueError('请补齐固定物理条件：'+', '.join(k for k in physical if k not in fixed))
    if not finite(fixed['wavelength_nm']) or not 200<=fixed['wavelength_nm']<=2000:raise ValueError('波长范围为 200–2000 nm')
    if model==SLIT:
        if not finite(fixed['focal_length_mm']) or not 1<=fixed['focal_length_mm']<=10000 or type(fixed['relative_phase_rad']) not in (int,float) or fixed['relative_phase_rad']!=0 or fixed['measurement_plane']!='FOURIER_FOCAL_PLANE':raise ValueError('仅支持明确的相位 0、理想焦平面和有效焦距')
    elif fixed['m2']!=1 or type(fixed['m2']) not in (int,float) or fixed['propagation']!='FREE_SPACE':raise ValueError('仅支持 M²=1，自由传播扫描中无透镜/截光/像差')
    if settings.get('loss') not in ('linear','soft_l1') or not finite(settings.get('f_scale')) or not 1e-9<=settings['f_scale']<=1e6:raise ValueError('请声明损失及有效残差尺度')
    if settings.get('registration') not in ('SHARED_REGISTERED','INDEPENDENT'):raise ValueError('请声明共享已配准坐标或每次独立中心')
    from .observation_contract import validate_protocol
    if not finite(settings.get('scale')) or not 1e-9<=settings['scale']<=1e6 or settings.get('scale_source') not in ('DECLARED_NUMERICAL_SCALE','KNOWN_MEASUREMENT_SD'):raise ValueError('残差尺度及来源必须明确；数值尺度不是测量精度')
    if not isinstance(group,list) or not 1<=len(group)<=3:raise ValueError('同一研究任务最多三份采集 CSV')
    validate_protocol(group,settings)
    if model==GAUSSIAN and settings['registration']!='SHARED_REGISTERED':raise ValueError('高斯扫描须使用共享已配准的全局 z 坐标')
    for k in names:
        if k in fixed:
            if k in bounds or not finite(fixed[k]) or abs(fixed[k])>1e6:raise ValueError('固定值与待估范围不能并存：'+k)
        else:
            b=bounds.get(k)
            if not isinstance(b,list) or len(b)!=2 or not all(finite(v) and abs(v)<=1e6 for v in b) or b[0]>=b[1]:raise ValueError('请明确待估范围：'+k)
    if not bounds:raise ValueError('至少声明一个允许估计的参数')
    def span(k):return [fixed[k]]*2 if k in fixed else bounds[k]
    if model==SLIT:
        a,d,A=span('slit_width_um'),span('slit_separation_um'),span('amplitude')
        if a[0]<=0 or a[1]>5000 or d[0]<=a[1] or d[1]>10000 or A[0]<=0:raise ValueError('请提供保证 d > a > 0、A > 0 的不交叠范围；d ≤ 10000 μm')
        if fixed['wavelength_nm']*.001/a[0]>.1:raise ValueError('整个缝宽搜索范围需满足近轴条件 λ/a ≤ 0.1')
    elif span('waist_radius_um')[0]<=0 or span('waist_radius_um')[1]>5000 or fixed['wavelength_nm']*.001/(math.pi*span('waist_radius_um')[0])>.1:raise ValueError('束腰半径须为 (0,5000] μm 且整个范围满足近轴条件')
    for item in group:
        dataset=item['dataset'];conditions=item['conditions']
        if digest({k:v for k,v in dataset.items() if k!='sha256'})!=dataset['sha256']:raise ValueError('数据哈希不一致')
        if dataset.get('questions'):raise ValueError('；'.join(dataset['questions']))
        if not dataset.get('x_mm') or dataset['rows']>5000:raise ValueError('物理坐标或行数无效')
        if model==SLIT and 'intensity' not in dataset or model==GAUSSIAN and 'radius_um' not in dataset:raise ValueError('CSV 类型与反向模型不一致')
        x=dataset['x_mm'];y=dataset['intensity'] if model==SLIT else dataset['radius_um']
        if type(dataset['rows']) is not int or not (20 if model==SLIT else 3)<=dataset['rows']<=5000 or len(x)!=len(y) or len(x)!=dataset['rows'] or any(not finite(v) or abs(v)>1e8 for v in x+y) or any(b<=a for a,b in zip(x,x[1:])):raise ValueError('原始坐标、数值或最少观测数无效')
        if model==GAUSSIAN:
            sd=dataset.get('sd_um')
            if any(v<=0 for v in y) or sd is not None and (len(sd)!=len(y) or any(not finite(v) or v<=0 for v in sd)):raise ValueError('半径及标准差无效')
        if conditions != {k:fixed[k] for k in physical}:raise ValueError('每次采集的固定条件须分别确认且与本次模型一致')
        if item.get('approved') is not True:raise ValueError('每份数据都需要明确纳入本次分析')
        if not finite(item.get('scale')) or not 1e-9<=item['scale']<=1e6 or item.get('scale_source') not in ('DECLARED_NUMERICAL_SCALE','KNOWN_MEASUREMENT_SD'):raise ValueError('每份采集必须分别声明权重尺度及来源')
        if model==SLIT:
            c=span('center_shift_mm');x=dataset['x_mm']
            if max(abs(x[0]-c[1]),abs(x[-1]-c[0]))/fixed['focal_length_mm']>.1:raise ValueError('坐标范围超过声明的近轴模型')
            observation=item.get('observation',{})
            if observation.get('kind')=='CALIBRATED_INTENSITY_AVERAGE':
                offsets=observation['kernel']['offsets_mm']
                if max(abs(x[0]-offsets[-1]-c[1]),abs(x[-1]-offsets[0]-c[0]))/fixed['focal_length_mm']>.1:raise ValueError('观测核完整支持超出近轴模型；不能用边界填充代替真实观测')
    return True


def physical(settings):
    if settings['model']==FILM:
        from .film_inverse import PHYSICS
        return {k:settings['fixed'][k] for k in PHYSICS if k in settings['fixed']}
    keys=('wavelength_nm','focal_length_mm','relative_phase_rad','measurement_plane') if settings['model']==SLIT else ('wavelength_nm','m2','propagation')
    return {k:settings['fixed'][k] for k in keys if k in settings['fixed']}


def layout(group, settings):
    names=[];lo=[];hi=[]
    for k in parameters(settings['model']):
        if k in settings['fixed']:continue
        local=settings['model']==SLIT and (k in ('amplitude','background') or k=='center_shift_mm' and settings['registration']=='INDEPENDENT')
        for j in range(len(group)) if local else [None]:
            names.append(k+(f'@{j}' if j is not None else ''));lo.append(settings['bounds'][k][0]);hi.append(settings['bounds'][k][1])
    return names,lo,hi


def values(theta, names, settings, j=0):
    result=dict(settings['fixed']);result.update({k:v for k,v in zip(names,theta) if '@' not in k})
    result.update({k.split('@')[0]:v for k,v in zip(names,theta) if k.endswith('@'+str(j))})
    return result


def predict(x, p, model):
    import numpy as np
    if model==GAUSSIAN:
        from .gaussian_inference import predict as radius
        return radius(x,p['waist_radius_um'],p['waist_z_mm'],p['wavelength_nm'])
    q=(np.asarray(x)-p['center_shift_mm'])/(p['wavelength_nm']*1e-6*p['focal_length_mm'])
    return p['background']+p['amplitude']*np.sinc(p['slit_width_um']*.001*q)**2*np.cos(np.pi*p['slit_separation_um']*.001*q)**2


def predict_observation(x, p, model, group):
    """Apply an explicitly calibrated physical-coordinate intensity kernel."""
    from .observation_contract import validate_observation
    observation=validate_observation(group,model)
    if observation['kind']!='CALIBRATED_INTENSITY_AVERAGE':return predict(x,p,model)
    import numpy as np
    xx=np.asarray(x);kernel=observation['kernel'];offsets=kernel['offsets_mm']
    if len(xx) and max(abs(float(np.min(xx))-offsets[-1]-p['center_shift_mm']),abs(float(np.max(xx))-offsets[0]-p['center_shift_mm']))/p['focal_length_mm']>.1:raise ValueError('观测核支持超出近轴模型')
    physical=dict(p,amplitude=1.,background=0.)
    shape=sum(weight*predict(xx-offset,physical,model) for offset,weight in zip(offsets,kernel['weights']))
    return p['background']+p['amplitude']*shape


def plan(group, settings, operation='fit', *, parameter=None, grid_points=21, reference=None, refinement=False):
    if settings.get('model')==FILM:
        if operation!='fit' or refinement:raise ValueError('薄膜厚度使用固定的全范围有限网格和局部候选，不另跑参数剖面')
        from .film_inverse import plan as build
        return build(group,settings)
    validate(group,settings)
    if operation not in ('fit','profile'):raise ValueError('不支持的计算')
    if operation=='profile':
        allowed=('slit_width_um','slit_separation_um') if settings['model']==SLIT else GAUSSIAN_PARAMETERS
        if parameter not in allowed or parameter not in settings['bounds'] or type(grid_points) is not int or not 3<=grid_points<=21:raise ValueError('剖面参数必须是待估物理量，粗网格 3–21 点')
        if not isinstance(reference,dict) or not reference.get('estimated_parameters'):raise ValueError('先完成拟合再计算参数证据曲线')
        center=reference['estimated_parameters'].get(parameter)
        lo,hi=settings['bounds'][parameter]
        if not finite(center) or not lo<=center<=hi:raise ValueError('参考参数不在已批准范围内')
        grid=[lo+i*(hi-lo)/(grid_points-1) for i in range(grid_points)]
        if center not in grid:
            # Predeclared in the plan, before any profile work; no outcome-driven refinement.
            nearest=min(range(1,grid_points-1),key=lambda i:abs(grid[i]-center));grid[nearest]=center;grid.sort()
        if refinement:
            radius=(hi-lo)/20;left=max(lo,center-radius);right=min(hi,center+radius)
            grid=sorted(set([left+i*(right-left)/8 for i in range(9)]+[center]));grid_points=len(grid)
    budget=LIMITS['profile' if operation=='profile' else 'joint' if len(group)>1 else 'fit']
    value={'schema':'photonguard.inverse-plan.v1','model':settings['model'],'operation':operation,
           'groups':copy.deepcopy(group),'settings':copy.deepcopy(settings),'budget':dict(budget),
           'splits':[{'holdout_indices':list(range(0,g['dataset']['rows'],5)),
                      'note':'同一次采集的交错留出；不用于起点选择；补采进入联合拟合后不是独立验证'} for g in group],
           'parameter_roles':{k:('USER_CONFIRMED_FIXED' if k in settings['fixed'] else 'MODEL_ESTIMATE') for k in parameters(settings['model'])},
           'profile':{'parameter':parameter,'grid_points':grid_points,'grid':grid,'reference_value':center,
                      'grid_rule':'equally spaced endpoints; nearest interior point replaced by saved fitted value; no adaptive refinement',
                      'display_rule':{'relative_cost_allowance':.1,'absolute_cost_floor':1e-8},
                      'label':'有限网格局部候选；不是置信区间；失败点未被排除'} if operation=='profile' else None,
           'reference_sha256':digest(reference) if reference else None}
    if refinement:
        if operation!='profile':raise ValueError('加密只能用于剖面')
        value['profile'].update(refinement=True,grid_rule='one root refinement; at most 10 points within fitted value +/- original range / 20; unchanged threshold')
    value['sha256']=digest(value);return value


def verify_plan(p):
    if p.get('model')==FILM:
        from .film_inverse import plan as build
        if p!=build(p['groups'],p['settings']):raise ValueError('薄膜计划哈希或固定协议改变')
        return
    if p.get('sha256')!=digest({k:v for k,v in p.items() if k!='sha256'}):raise ValueError('计划哈希发生变化')
    validate(p['groups'],p['settings'])
    expected=LIMITS['profile' if p['operation']=='profile' else 'joint' if len(p['groups'])>1 else 'fit']
    if p['budget']!=expected:raise ValueError('资源计划不能扩大')
    profile=p.get('profile') or {}
    reference={'estimated_parameters':{profile.get('parameter'):profile.get('reference_value')}} if p['operation']=='profile' else None
    rebuilt=plan(p['groups'],p['settings'],p['operation'],parameter=profile.get('parameter'),grid_points=profile.get('grid_points',21),reference=reference,refinement=profile.get('refinement',False))
    rebuilt['reference_sha256']=p['reference_sha256'] if p['operation']=='profile' else None
    rebuilt['sha256']=digest({k:v for k,v in rebuilt.items() if k!='sha256'})
    if rebuilt!=p:raise ValueError('划分、剖面阈值或角色与固定协议不一致')
