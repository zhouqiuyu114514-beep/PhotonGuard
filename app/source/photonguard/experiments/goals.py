"""Goals are calculated from actual sampled arrays, never model prose."""
from ..core import finite

def assess(result,goal):
    metric=goal['metric'];unit=goal.get('unit') or ('um' if metric.endswith('_um') else 'mm' if metric.endswith('_mm') else 'fraction')
    engine=result.get('engine',{});engine=engine.get('name','') if isinstance(engine,dict) else str(engine)
    source={'engine':engine,'field':'metrics.'+metric,'kind':'COMPUTED_METRIC','label':'实际计算指标'}
    if metric in ('reflectance','transmittance'):
        data=result['data'];axis=data['wavelengths_um'];target=goal['wavelength_um']
        matches=[i for i,x in enumerate(axis) if abs(x-target)<=1e-12]
        if len(matches)!=1:raise ValueError('目标波长未被唯一实际采样；禁止图像插值判定')
        value=data['R' if metric=='reflectance' else 'T'][matches[0]];unit='fraction'
        source.update(kind='MEEP_SAMPLE' if 'meep' in engine.lower() else 'TMM_SAMPLE',label='Meep实际采样' if 'meep' in engine.lower() else 'TMM实际采样',field='data.'+('R' if metric=='reflectance' else 'T')+'['+str(matches[0])+']',wavelength_um=axis[matches[0]],interpolation_used=False)
    else:value=result['metrics'].get(metric)
    if metric in ('fringe_period_mm','first_zero_mm'):source.update(kind='ANALYTIC_GEOMETRY',label='理想几何公式；另有二维场数值校准',field='metrics.'+metric,measured_from_image=False)
    elif metric=='central_intensity_ratio':source.update(kind='FFT_CENTER_FIELD',label='二维场中心光强与同几何零相位基准之比')
    elif metric.startswith(('screen_radius','new_waist')):source.update(kind='GAUSSIAN_Q_ABCD',label='高斯q参数与ABCD计算')
    elif metric.endswith(('_mean','_min')):source.update(kind='MEEP_SAMPLE_AGGREGATE' if 'meep' in engine.lower() else 'TMM_SAMPLE_AGGREGATE',label=('Meep' if 'meep' in engine.lower() else 'TMM')+'实际采样点的统计量',continuous_band_guarantee=False)
    if not finite(value):raise ValueError('求解器未返回所需的有限目标数值')
    op=goal['operator'];target=goal.get('target')
    met= value<=target if op=='<=' else value>=target if op=='>=' else abs(value-target)<=goal['tolerance'] if op=='near' else None
    basis='ANALYTIC_GEOMETRY_FINITE_CANDIDATES' if source['kind']=='ANALYTIC_GEOMETRY' else 'GAUSSIAN_Q_ABCD_FINITE_CANDIDATES' if source['kind']=='GAUSSIAN_Q_ABCD' else 'ACTUAL_SAMPLES_FINITE_CANDIDATES'
    return {'metric':metric,'operator':op,'value':value,'unit':unit,'target':target,'met':met,'basis':basis,'optimization_only':met is None,'source':source}

def rank(candidates,goal):
    valid=[c for c in candidates if c.get('status')=='RUN_COMPLETED' and c.get('all_checks_passed') is True]
    op=goal['operator']
    def key(c):
        v=c['goal']['value']
        return abs(v-goal['target']) if op=='near' else -v if op in ('>=','maximize') else v
    return [c['id'] for c in sorted(valid,key=lambda c:(key(c),c['id']))]
