"""Deterministic authoring helper. Never run this over a frozen study directory.

Oracle uses separate textbook expressions, not product results or Pro's probes.
These are implementation checks under the same ideal models, not certificates.
"""
from pathlib import Path
import cmath
import copy
import itertools
import json
import math

HERE = Path(__file__).resolve().parent
UNITS = {'layers': 'n: dimensionless; thickness_um: um', 'wavelengths_um': 'um',
         'material_n_high': 'dimensionless', 'material_n_low': 'dimensionless',
         'layer_count': 'count', 'design_wavelength_um': 'um', 'aperture': 'enum',
         'wavelength_nm': 'nm', 'focal_length_mm': 'mm', 'slit_width_um': 'um',
         'slit_height_um': 'um', 'slit_separation_um': 'um', 'relative_phase_rad': 'rad',
         'grid_size': 'samples', 'window_mm': 'mm', 'waist_radius_um': 'um',
         'waist_z_mm': 'mm', 'screen_distance_mm': 'mm', 'z_max_mm': 'mm'}


def budget(domain, count):
    return {'max_candidates': count, 'max_fast_evaluations': count*(2 if domain == 'diffraction' else 1),
            'max_meep_validations': 1 if domain == 'film' else 0,
            'max_fdtd': 8 if domain == 'film' else 0}


def film(n=2.1, thickness=.115, wavelengths=(.5,.62,.74)):
    return {'layers': [{'n': n, 'thickness_um': thickness}], 'wavelengths_um': list(wavelengths)}


def stack(high=2.2, low=1.6, count=2, design=.72):
    return {'material_n_high': high, 'material_n_low': low, 'layer_count': count,
            'design_wavelength_um': design, 'wavelengths_um': [.64,.68,.72,.76,.8]}


def diffraction(wavelength=532., focal=150., width=32., separation=160., phase=0., aperture='double_slit'):
    value = {'aperture': aperture, 'wavelength_nm': wavelength, 'focal_length_mm': focal,
             'slit_width_um': width, 'slit_height_um': 128.,
             'grid_size': 256, 'window_mm': .320}
    if aperture == 'double_slit':
        value['slit_separation_um'] = separation
        value['relative_phase_rad'] = phase
    return value


def gaussian(wavelength=780., radius=600., waist=-30., focal=125., screen=125.):
    return {'wavelength_nm': wavelength, 'waist_radius_um': radius, 'waist_z_mm': waist,
            'focal_length_mm': focal, 'screen_distance_mm': screen, 'z_max_mm': 250.}


def metric(parameters, domain, goal):
    """Independent oracle expressions, not imported from photonguard."""
    if domain == 'gaussian':
        w = parameters['waist_radius_um']/1000
        wavelength = parameters['wavelength_nm']/1e6
        z = parameters['screen_distance_mm']; a = 1-z/parameters['focal_length_mm']
        b = z-parameters['waist_z_mm']*a
        return 1000*math.sqrt((a*w)**2 + (b*wavelength/(math.pi*w))**2)
    if domain == 'diffraction':
        if goal['metric'] == 'central_intensity_ratio':
            return math.cos(parameters['relative_phase_rad']/2)**2
        divisor = 'slit_separation_um' if goal['metric'] == 'fringe_period_mm' else 'slit_width_um'
        return parameters['wavelength_nm']*parameters['focal_length_mm']/parameters[divisor]/1000
    layers = parameters.get('layers')
    if layers is None:
        layers = [{'n': parameters['material_n_high'] if i % 2 == 0 else parameters['material_n_low'],
                   'thickness_um': parameters['design_wavelength_um']/(4*(parameters['material_n_high'] if i % 2 == 0 else parameters['material_n_low']))}
                  for i in range(parameters['layer_count'])]
    m00,m01,m10,m11 = 1+0j,0j,0j,1+0j
    for layer in layers:
        n = layer['n']; phase = 2*math.pi*n*layer['thickness_um']/goal['wavelength_um']
        a,b,c,d = cmath.cos(phase),1j*cmath.sin(phase)/n,1j*n*cmath.sin(phase),cmath.cos(phase)
        m00,m01,m10,m11 = m00*a+m01*c,m00*b+m01*d,m10*a+m11*c,m10*b+m11*d
    return abs((m00+m01-m10-m11)/(m00+m01+m10+m11))**2


def source_text(domain, p):
    if domain == 'film':
        if 'layers' in p:
            lead = '空气两侧、正入射、无损无色散单膜。' + ''.join(f"折射率 {x['n']}，厚度 {x['thickness_um']} μm。" for x in p['layers'])
        else:
            lead = (f"空气两侧、正入射、无损无色散交替 H/L 四分之一波膜系，从 H 开始。nH={p['material_n_high']}，nL={p['material_n_low']}，"
                    f"设计波长 {p['design_wavelength_um']} μm，当前层数 {p['layer_count']}。")
        return lead + '实际采样波长（μm）：'+', '.join(map(str,p['wavelengths_um']))+'。'
    if domain == 'diffraction':
        lead = '双缝' if p['aperture'] == 'double_slit' else '单缝'
        return (f"均匀相干照明，标量近轴模型，{lead}后的理想薄透镜后焦面；波长 {p['wavelength_nm']} nm，焦距 {p['focal_length_mm']} mm，"
                f"缝宽 {p['slit_width_um']} μm，缝高 {p['slit_height_um']} μm，" +
                (f"中心缝距 {p['slit_separation_um']} μm，相对相位 {p['relative_phase_rad']} rad。" if 'slit_separation_um' in p else '')+
                f"数值网格 {p['grid_size']}，输入平面窗口 {p['window_mm']} mm。")
    return (f"空气中的理想 TEM00 高斯束，M²=1，理想薄透镜在 z=0。波长 {p['wavelength_nm']} nm，"
            f"束腰的 1/e² 强度半径 {p['waist_radius_um']} μm，束腰位置 z={p['waist_z_mm']} mm，"
            f"当前焦距 {p['focal_length_mm']} mm，屏幕位置 z={p['screen_distance_mm']} mm，束宽曲线绘制到 z={p['z_max_mm']} mm。")


def make(identifier, domain, category, parameters, variables, goal, request, *, missing=None, parent_goal=None):
    count = math.prod(len(v) for v in variables.values()) if variables else 1
    text = source_text(domain, parameters)
    cards = None
    if missing:
        key, fragment, reply, aliases = missing
        if fragment not in text: raise ValueError(fragment)
        text = text.replace(fragment, '此参数尚未提供，需向我核实')
        cards = {'id': identifier, 'required_fields': [key], 'aliases': aliases,
                 'reply': reply, 'origin': 'SIMULATED_STATE_MACHINE_AUTHOR_FACT',
                 'must_ask_before_run': True, 'max_replies': 1}
    if variables:
        text += '只允许扫描这些有限候选：'+json.dumps(variables,ensure_ascii=False)+'。其他参数不得改变。'
    else: text += '所有物理参数固定，不进行候选扫描。'
    text += request
    if domain == 'film': text += '最多一个推荐候选进行现有 Meep 完整验证，最多 8 次 FDTD；快速计算不能冒充独立验证。'
    spec = {'schema_version':1,'domain':domain,'context_kind':'specified','known_parameters':parameters,
            'parameter_sources':{k:{'unit':UNITS[k],'quote':(cards['reply'] if cards and k in cards['required_fields'] else text)} for k in parameters},
            'assumptions':[],'locked_parameters':sorted(set(parameters)-set(variables)),
            'allowed_variables':variables,'goal':goal,'resource_budget':budget(domain,count),'parent_task_id':None}
    public = {'id':identifier,'domain':domain,'category':category,'text':text,
              'resource_budget':budget(domain,count),'participant_kind':'SIMULATED_STATE_MACHINE'}
    if parent_goal:
        parent = copy.deepcopy(spec); parent['goal'] = parent_goal
        parent['parent_task_id'] = None
        public['parent'] = {'id':identifier+'-parent','spec':parent,
                            'description':'先前用户确认的规格，作为修订约束上下文；不是声称已经运行过的结果。'}
        spec['parent_task_id'] = identifier+'-parent'
    candidates = []
    keys = sorted(variables)
    for values in itertools.product(*(variables[k] for k in keys)) if keys else [()]:
        params = copy.deepcopy(parameters); params.update(zip(keys,values))
        value = metric(params,domain,goal)
        op = goal['operator']
        met = value <= goal.get('target',0) if op == '<=' else value >= goal.get('target',0) if op == '>=' else abs(value-goal['target']) <= goal['tolerance'] if op == 'near' else None
        candidates.append({'variable_values':dict(zip(keys,values)),'metric_value':value,'goal_met':met})
    op = goal['operator']
    score = lambda c: abs(c['metric_value']-goal['target']) if op == 'near' else -c['metric_value'] if op in ('>=','maximize') else c['metric_value']
    best = min(score(c) for c in candidates)
    oracle = {'id':identifier,'reference_spec':spec,'candidates':candidates,
              'acceptable_winner_variable_values':[c['variable_values'] for c in candidates if math.isclose(score(c),best,rel_tol=1e-9,abs_tol=1e-12)],
              'relative_metric_tolerance':.04 if domain == 'diffraction' else 1e-8,
              'absolute_metric_tolerance':1e-8,'requires_clarification':bool(missing),
              'reference_origin':'Separate textbook expressions in build_fixtures.py; not product outputs, attached Pro examples, or empirical measurements.',
              'is_independent_scientific_certificate':False}
    return public,oracle,cards


def build():
    tasks=[]
    tasks.append(make('M01','film','complete',film(),{},
                      {'metric':'reflectance','operator':'>=','target':.1,'wavelength_um':.62},'目标是在 0.62 μm 的反射率至少 0.10，请实际判断。'))
    tasks.append(make('M02','diffraction','complete',diffraction(aperture='single_slit'),{},
                      {'metric':'first_zero_mm','operator':'near','target':2.49375,'tolerance':.1},'目标是中心到第一零点约 2.49375 mm，绝对容差 0.1 mm。'))
    tasks.append(make('M03','gaussian','complete',gaussian(),{},
                      {'metric':'screen_radius_um','operator':'<=','target':60.},'目标是该屏上半径不超过 60 μm。'))
    p=film(1.9,.135,(.55,.65,.75))
    tasks.append(make('M04','film','missing',p,{},
                      {'metric':'reflectance','operator':'>=','target':.1,'wavelength_um':.65},'目标是在 0.65 μm 的反射率至少 0.10。',
                      missing=('layers','厚度 0.135 μm','确认这层实际厚度为 0.135 μm，折射率仍为 1.9。',['厚度','thickness','layers'])))
    tasks.append(make('M05','diffraction','missing',diffraction(594,180,32,192),{},
                      {'metric':'fringe_period_mm','operator':'near','target':.556875,'tolerance':.025},'目标是条纹周期 0.556875 mm，绝对容差 0.025 mm。',
                      missing=('focal_length_mm','焦距 180 mm','确认理想透镜焦距为 180 mm；这里是后焦面，不是自由传播屏距。',['焦距','focal_length','透镜'])) )
    tasks.append(make('M06','gaussian','missing',gaussian(850,550,-40,120,120),{},
                      {'metric':'screen_radius_um','operator':'<=','target':65.},'目标是该屏上半径不超过 65 μm。',
                      missing=('waist_z_mm','束腰位置 z=-40 mm','确认束腰在透镜前 40 mm，即束腰位置 z=-40 mm。',['束腰位置','waist_z','位置','波前'])) )
    tasks.append(make('M07','film','comparison',stack(),{'layer_count':[2,4,6]},
                      {'metric':'reflectance','operator':'>=','target':.5,'wavelength_um':.72},'比较全部候选，选择 0.72 μm 反射率最高的可行方案，目标至少 0.50。'))
    tasks.append(make('M08','diffraction','comparison',diffraction(488,160,32,160),{'slit_separation_um':[128.,160.,192.]},
                      {'metric':'fringe_period_mm','operator':'near','target':.488,'tolerance':.02},'比较全部缝距，选择条纹周期最接近 0.488 mm 的候选，绝对容差 0.02 mm。'))
    tasks.append(make('M09','gaussian','comparison',gaussian(650,450,-25,90,90),{'focal_length_mm':[80.,90.,110.]},
                      {'metric':'screen_radius_um','operator':'minimize'},'从所给目录比较全部焦距，选择屏幕半径最小的那一个，只讨论该目录。'))
    p=stack(2.3,1.4,2,.70);p['wavelengths_um']=[.60,.65,.70,.75,.80]
    tasks.append(make('M10','film','revision',p,{'layer_count':[2,4,6]},
                      {'metric':'reflectance','operator':'>=','target':.65,'wavelength_um':.75},'修改目标：现在考察 0.75 μm，反射率至少 0.65。仍只改层数，不许把原设计波长 0.70 μm 偷改成目标波长。',
                      parent_goal={'metric':'reflectance','operator':'maximize','wavelength_um':.70}))
    tasks.append(make('M11','diffraction','revision',diffraction(561,175,32,192),{'relative_phase_rad':[0.,math.pi]},
                      {'metric':'central_intensity_ratio','operator':'<=','target':.01},'修改目标：把中心亮纹变暗，使中心强度相对同几何同相中心不超过 0.01。只许改相对相位，缝宽、缝高、缝距、波长和焦距全部保留。',
                      parent_goal={'metric':'central_intensity_ratio','operator':'maximize'}))
    tasks.append(make('M12','gaussian','revision',gaussian(532,400,-20,100,100),{'focal_length_mm':[90.,100.,120.]},
                      {'metric':'screen_radius_um','operator':'<=','target':50.},'修改目标：现在要求固定 z=100 mm 的屏上半径不超过 50 μm。只许选原焦距目录，不能缩小束腰、移动束腰、换波长或移动屏幕。',
                      parent_goal={'metric':'screen_radius_um','operator':'minimize'}))
    dev = [
        make('DEV01','film','complete',film(1.8,.105,(.50,.58,.68)),{}, {'metric':'reflectance','operator':'>=','target':.10,'wavelength_um':.58},'目标是在 0.58 μm 反射率至少 0.10。'),
        make('DEV02','diffraction','comparison',diffraction(520,140,32,160),{'slit_separation_um':[128.,160.]},{'metric':'fringe_period_mm','operator':'near','target':.455,'tolerance':.025},'选择条纹周期接近 0.455 mm 的候选，绝对容差 0.025 mm。'),
        make('DEV03','gaussian','comparison',gaussian(660,480,0,110,110),{'focal_length_mm':[100.,110.,130.]},{'metric':'screen_radius_um','operator':'minimize'},'选择目录中屏上半径最小的焦距。'),
        make('DEV04','diffraction','revision',diffraction(520,140,32,160),{'relative_phase_rad':[0.,math.pi]},{'metric':'central_intensity_ratio','operator':'<=','target':.01},'改目标：只改相位，把中心相对强度降到 0.01 以下，全部几何保留。',parent_goal={'metric':'central_intensity_ratio','operator':'maximize'})]
    paper_resources=[]
    for public,oracle,_ in tasks+dev:
        if public['domain']!='diffraction':continue
        p=oracle['reference_spec']['known_parameters'];variables=oracle['reference_spec']['allowed_variables']
        count=len(oracle['candidates']);grid=p['grid_size'];window_um=p['window_mm']*1000
        span=max(variables.get('slit_separation_um',[p.get('slit_separation_um',0)]))+p['slit_width_um']
        image_grid=min(grid,2*math.floor(.1*p['window_mm']*1e6/p['wavelength_nm'])+1)
        estimated=count*40*(grid*grid+4*image_grid*image_grid)+1024*1024
        width_pixels=p['slit_width_um']/(window_um/grid)
        if max(span,p['slit_height_um'])>.8*window_um or width_pixels<8 or estimated>64*1024*1024:
            raise ValueError('Paper resource planning failed: '+public['id'])
        paper_resources.append({'id':public['id'],'grid_size':grid,'window_mm':p['window_mm'],
                                'candidate_count':count,'largest_aperture_span_um':span,
                                'slit_width_pixels':width_pixels,'image_grid_upper':image_grid,
                                'estimated_output_bytes':estimated,'output_cap_bytes':64*1024*1024,
                                'geometry_inside_80_percent_window':True,'at_least_8_width_pixels':True})
    contents={'formal-public.json':[x[0] for x in tasks], 'development-public.json':[x[0] for x in dev],
              'dialogue-cards.json':{x[0]['id']:x[2] for x in tasks+dev if x[2]},
              'private-oracle.json':{x[0]['id']:x[1] for x in tasks+dev},
              'numerical-resource-audit.json':{'status':'PRE_FREEZE_PAPER_RESOURCE_CHECK_ONLY',
                'actual_physical_solver_calls':0,'actual_model_calls':0,
                'window_policy':'Shared 0.320 mm window is the smallest 0.064 mm step above the 0.280 mm aperture-fit bound; 256 grid gives 25.6 pixels across 32 um slits.',
                'estimation_formula':'candidate_count * 40 * (grid_size**2 + 4*image_grid**2) + 1048576',
                'image_grid_formula':'min(grid_size, 2*floor(0.1*window_mm*1e6/wavelength_nm)+1)',
                'note':'Physical inputs, goals, thresholds and complete candidate lists are unchanged. Single-slit fictitious relative-phase field removed to match the fixed public tool.',
                'tasks':paper_resources},
              'protocol.json':{'schema_version':1,'status':'CANDIDATE_PROTOCOL_NOT_EXECUTED','created_date':'2026-10-11',
                'formal_order':[x[0]['id'] for x in tasks], 'budget_fallback_order':[x[0]['id'] for x in tasks[:6]],
                'development_order':[x[0]['id'] for x in dev], 'arms':['A','G'], 'alternate_arm_order':True,
                'model':'deepseek-flash','temperature':0,'max_output_tokens':4096,
                'max_calls_per_formal_task_arm':3,'max_calls_per_development_task_arm':2,
                'max_formal_calls':72,'max_development_calls':16,'automatic_provider_retry':False,
                'replace_failed_tasks':False,'tune_on_frozen_formal_results':False,
                'participant_kind':'SIMULATED_STATE_MACHINE','new_human_participants':0,'historical_guided_owner_participants':1,
                'primary_metric':'end_to_end_goal_completed','secondary_metrics':['task_judgment_completed','routing_correct','facts_preserved','constraints_preserved','clarification_correct','numeric_checks_passed','goal_metric_correct','report_consistent','design_goal_met','model_calls','physical_resources'],
                'baseline_difference':'G receives parent-version constraint enforcement and internal feedback; A receives the same public tools, facts, goal results and common numeric/resource errors. A is audited for constraints after execution.',
                'task_origin':'Synthetic new parameter instances authored locally, not external independent or unseen-domain tasks. Attached numerical demonstration values are not formal tasks.',
                'oracle_origin':'Separate textbook formulas in build_fixtures.py; same ideal physical theory, not independent scientific certification.',
                'financial_rule':'Existing cumulative authorization and append-only ledger including held unknown costs govern; protocol limits are not new authorization.',
                'stop_rule':'Budget decision made before formal batch; choose fixed 12 or fixed first 6. Mid-batch resource/provider stops remain in denominator; no replacement or automatic retry.'}}
    for name,value in contents.items():
        (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return contents


if __name__ == '__main__':
    result=build()
    print(json.dumps({'formal':len(result['formal-public.json']),'development':len(result['development-public.json']),
                      'any_unreachable_threshold':[k for k,v in result['private-oracle.json'].items() if v['reference_spec']['goal']['operator'] not in ('minimize','maximize') and not any(c['goal_met'] for c in v['candidates'])]}))
