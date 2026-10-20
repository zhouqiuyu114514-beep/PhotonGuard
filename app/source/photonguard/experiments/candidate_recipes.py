"""Deterministic finite suggestions; never a global inverse-design claim."""
import math
from ..core import finite

def candidates(recipe,parameters,goal,values=None,bounds=None):
    method=recipe['method'];variable=recipe.get('variable');note={ 'method':method,'variable':variable,'computed_results':False,'scope':'仅有限候选；解析提议不是实际场计算'}
    if method=='single':return {},note
    if method=='fringe_target':
        if goal.get('metric')!='fringe_period_mm' or not finite(goal.get('target')) or goal['target']<=0:raise ValueError('生成缝距需要正的目标条纹周期')
        if not isinstance(bounds,dict) or set(bounds)!={'min','max'} or not all(finite(bounds[k]) for k in bounds) or not 0<bounds['min']<=bounds['max']:raise ValueError('请明确允许的缝距范围 min/max（μm）')
        center=parameters['wavelength_nm']*parameters['focal_length_mm']/(1000*goal['target'])
        pivot=max(bounds['min'],min(bounds['max'],center))
        values=sorted({max(bounds['min'],min(bounds['max'],round(pivot*f,10))) for f in (.95,1,1.05)})
        note.update(formula='d_um = wavelength_nm * focal_length_mm / (1000 * fringe_period_mm)',analytic_suggestion_um=center,bounds=bounds,analytic_suggestion_in_range=bounds['min']<=center<=bounds['max'])
    elif method=='phase':
        values=[0,math.pi/2,math.pi] if values is None else values
    if not isinstance(values,list) or not 1<=len(values)<=8 or any(not finite(v) for v in values):raise ValueError('请提供1–8项明确的有限候选目录')
    if len(set(values))!=len(values):raise ValueError('候选目录有重复值')
    if bounds and any(not bounds['min']<=v<=bounds['max'] for v in values):raise ValueError('候选超出允许范围')
    note['values']=values
    if method=='thickness_catalog':
        return {'layers':[[{'n':parameters['film_n'],'thickness_um':v}] for v in values]},note
    return {variable:values},note
