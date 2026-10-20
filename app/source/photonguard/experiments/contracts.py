"""Bounded, data-only optical experiments and immutable physical constraints."""
from __future__ import annotations
import copy
import math
from ..core import digest, finite

VERSION = 'optical-experiments-v1'
REQUIRED = {
 'film': [],
 'diffraction': ['aperture','wavelength_nm','focal_length_mm','slit_width_um','slit_height_um'],
 'gaussian': ['wavelength_nm','waist_radius_um','waist_z_mm','focal_length_mm','screen_distance_mm'],
}
PARAMETERS = {
 'film': {'layers','wavelengths_um','scan_min_um','scan_max_um','scan_points','material_n_high','material_n_low','layer_count','design_wavelength_um'},
 'diffraction': set(REQUIRED['diffraction'])|{'slit_separation_um','relative_phase_rad','grid_size','window_mm'},
 'gaussian': set(REQUIRED['gaussian'])|{'z_max_mm'},
}
VARIABLES = {'film':{'layers','layer_count','design_wavelength_um'},'diffraction':{'slit_width_um','slit_separation_um','relative_phase_rad','focal_length_mm','wavelength_nm'},'gaussian':{'focal_length_mm','screen_distance_mm'}}
METRICS = {'film':{'reflectance','transmittance','reflectance_min','reflectance_mean','transmittance_min','transmittance_mean'},'diffraction':{'central_intensity_ratio','fringe_period_mm','first_zero_mm'},'gaussian':{'screen_radius_um','new_waist_radius_um','new_waist_z_mm'}}
DEFAULT_BUDGET = {'max_candidates':12,'max_fast_evaluations':24,'max_meep_validations':1,'max_fdtd':8,'worker_seconds':60,'worker_memory_mib':1024,'output_mib':64}
ASSUMPTIONS = {
 'film':['空气两侧，正入射；线性、无损、无色散、各向同性膜层','最多8层，总厚度≤5微米；结论仅涉及实际采样波长和有限候选'],
 'diffraction':['均匀相干照明，标量近轴近似，理想薄透镜的傅里叶焦平面','相对相位为理想相位参数；不等同于真实相位材料设计','共同入射强度为1；不同候选使用共同物理强度标尺'],
 'gaussian':['空气中理想TEM00，M²=1；一片理想薄透镜位于z=0','光斑为1/e²强度半径；忽略像差、截断及损伤','束腰位置和束腰半径必须同时已知；直径不能确定波前'],
}

def validate_spec(spec, parent=None):
    if not isinstance(spec,dict): raise ValueError('实验规格必须为JSON对象')
    s=copy.deepcopy(spec)
    allowed={'schema_version','domain','context_kind','known_parameters','parameter_sources','assumptions','locked_parameters','allowed_variables','goal','candidate_bounds','resource_budget','parent_task_id'}
    if set(s)-allowed: raise ValueError('不支持的实验字段：'+str(sorted(set(s)-allowed)))
    if s.get('schema_version')!=1 or type(s.get('schema_version')) is not int: raise ValueError('实验规格版本错误')
    d=s.get('domain')
    if d not in REQUIRED or s.get('context_kind') not in ('teaching','specified'): raise ValueError('请选择受支持的场景与资料类型')
    p=s.get('known_parameters',{})
    if not isinstance(p,dict) or set(p)-PARAMETERS[d]: raise ValueError('参数名超出固定工具的公开范围')
    missing=[k for k in REQUIRED[d] if p.get(k) is None]
    if d=='diffraction' and p.get('aperture')=='double_slit': missing += [k for k in ('slit_separation_um','relative_phase_rad') if p.get(k) is None]
    if d=='film':
        if not p.get('layers'): missing += [k for k in ('material_n_high','material_n_low','layer_count','design_wavelength_um') if p.get(k) is None]
        if not p.get('wavelengths_um'): missing += [k for k in ('scan_min_um','scan_max_um','scan_points') if p.get(k) is None]
    if missing: raise ValueError('缺少参数：'+', '.join(missing))
    for k,v in p.items():
        if v is None: raise ValueError('未知参数不能执行：'+k)
        if k!='aperture' and not isinstance(v,list) and not finite(v): raise ValueError('参数必须为有限数值：'+k)
    if d=='diffraction' and p['aperture'] not in ('single_slit','double_slit'):raise ValueError('仅支持单缝/双缝')
    variables=s.get('allowed_variables',{})
    if not isinstance(variables,dict) or set(variables)-VARIABLES[d]: raise ValueError('候选变量不受支持')
    count=1
    for k,v in variables.items():
        if not isinstance(v,list) or not 1<=len(v)<=32:raise ValueError('每个变量需要1–32个明确候选值')
        if k not in p:raise ValueError('候选变量必须有已知基准值：'+k)
        if len({digest(x) for x in v})!=len(v):raise ValueError('候选值不能重复')
        count*=len(v)
    locks=s.get('locked_parameters',[])
    if not isinstance(locks,list) or any(not isinstance(k,str) or k not in p for k in locks) or len(set(locks))!=len(locks):raise ValueError('锁定参数无效')
    if set(locks)&set(variables):raise ValueError('锁定参数不能列为待改变的变量')
    # All physical parameters not explicitly allowed to vary are locked by default.
    s['locked_parameters']=sorted(set(locks)|(set(p)-set(variables)))
    if parent:
        old=parent.get('spec',parent)
        if old['domain']!=d:raise ValueError('改目标不能静默切换物理场景')
        for k in old['locked_parameters']:
            if p.get(k)!=old['known_parameters'][k] or k in variables:raise ValueError('修改违反已锁定参数：'+k)
        if not set(variables)<=set(old.get('allowed_variables',{})):raise ValueError('新版本扩大了原先允许改变的物理参数')
        for k,values in variables.items():
            if not {digest(v) for v in values}<={digest(v) for v in old['allowed_variables'][k]}:raise ValueError('新版本引入原候选目录以外的数值：'+k)
        for k,values in old.get('allowed_variables',{}).items():
            if k not in variables and digest(p.get(k)) not in {digest(v) for v in values}:raise ValueError('固定原候选变量时仍须选择原目录内的值：'+k)
    bounds=s.get('candidate_bounds',{})
    if not isinstance(bounds,dict) or set(bounds)-set(variables):raise ValueError('候选边界只能约束明确变量')
    for k,b in bounds.items():
        if not isinstance(b,dict) or set(b)!={'min','max'} or not finite(b['min']) or not finite(b['max']) or b['min']>b['max']:raise ValueError('候选数值边界无效')
        if any(not finite(v) or not b['min']<=v<=b['max'] for v in variables[k]):raise ValueError('候选超出声明边界：'+k)
    goal=s.get('goal')
    if not isinstance(goal,dict) or set(goal)-{'metric','operator','target','wavelength_um','tolerance','unit'}:raise ValueError('目标格式无效')
    if goal.get('metric') not in METRICS[d] or goal.get('operator') not in ('<=','>=','near','minimize','maximize'):raise ValueError('目标需使用公开指标和比较方式')
    expected_unit='um' if goal['metric'].endswith('_um') else 'mm' if goal['metric'].endswith('_mm') else 'fraction'
    if goal.get('unit',expected_unit)!=expected_unit:raise ValueError('目标单位应为'+expected_unit+'；请先转换阈值与容差')
    if d=='diffraction' and p['aperture']=='single_slit' and goal['metric']=='fringe_period_mm':raise ValueError('双缝干涉条纹周期不适用于单缝，请选择第一暗纹位置')
    if goal['operator'] not in ('minimize','maximize') and not finite(goal.get('target')):raise ValueError('目标阈值未知')
    if goal['operator']=='near' and (not finite(goal.get('tolerance')) or goal['tolerance']<0):raise ValueError('接近目标需要明确误差容限')
    if goal['metric'] in ('reflectance','transmittance') and not finite(goal.get('wavelength_um')):raise ValueError('单点薄膜目标需要指定波长')
    if not isinstance(s.get('resource_budget',{}),dict):raise ValueError('资源上限必须为对象')
    budget={**DEFAULT_BUDGET,**s.get('resource_budget',{})}
    if set(budget)!=set(DEFAULT_BUDGET):raise ValueError('未知资源字段')
    limits={**DEFAULT_BUDGET,'max_candidates':32,'max_fast_evaluations':32,'max_meep_validations':2,'max_fdtd':16}
    for k,v in budget.items():
        if type(v) is not int or not 0<=v<=limits[k]:raise ValueError('资源上限无效：'+k)
    if count>budget['max_candidates'] or count*(2 if d=='diffraction' else 1)>min(budget['max_fast_evaluations'],24 if d=='diffraction' else 32):raise ValueError('候选列表超出本批资源上限，请缩小候选集合')
    if d=='diffraction':
        waves=variables.get('wavelength_nm',[p['wavelength_nm']])
        if not all(finite(w) and w>0 for w in waves):raise ValueError('候选波长必须为正数')
        grid=p.get('grid_size',512);window=p.get('window_mm',.5);wave=min(waves)
        if not finite(grid) or not finite(window) or not finite(wave) or wave<=0:raise ValueError('二维计算网格无效')
        image_grid=min(grid,2*math.floor(.1*window*1e6/wave)+1)
        estimated=count*40*(grid*grid+4*image_grid*image_grid)+1024*1024
        if estimated>budget['output_mib']*1024*1024:raise ValueError('二维原始场与展示证据预计超出输出预算，请减少候选或数值窗口')
    if budget['max_fdtd']<budget['max_meep_validations']*8:raise ValueError('每个完整Meep复核需要预留8次FDTD')
    if not budget['worker_seconds'] or not budget['worker_memory_mib'] or not budget['output_mib']:raise ValueError('工作进程资源必须为正')
    sources=s.get('parameter_sources',{})
    if not isinstance(sources,dict) or any(k not in sources for k in p):raise ValueError('每个已知参数必须保留出处与单位')
    for k in p:
        source=sources[k]
        if not isinstance(source,dict) or not isinstance(source.get('unit'),str):raise ValueError('参数出处必须有原文与unit：'+k)
        quotes=source.get('quotes',[source.get('quote')])
        if 'quotes' in source and 'quote' in source:raise ValueError('出处请选择单段quote或多段quotes，不能混用')
        if not isinstance(quotes,list) or not 1<=len(quotes)<=8 or any(not isinstance(q,str) or not q.strip() or len(q)>24000 for q in quotes):raise ValueError('出处必须为1–8段逐字原文：'+k)
    s.update(allowed_variables=variables,resource_budget=budget,assumptions=ASSUMPTIONS[d],parameter_sources=sources)
    digest(s)
    return s
