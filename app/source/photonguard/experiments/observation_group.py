"""Small inverse journeys on the existing store; immutable versions, shared limits."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from ..core import digest
from ..workflow import WorkflowError, atomic_json
from . import inverse_models as models, observations, gaussian_inference


def defaults(model):
    if model==models.FILM:
        from .film_inverse import defaults as film_defaults
        return film_defaults()
    common={'model':model,'loss':'linear','f_scale':1.,'registration':'SHARED_REGISTERED',
            'weighting':'EQUAL_DATASET_TRAINING_COUNT','scale':.01 if model==models.SLIT else .5,
            'scale_source':'DECLARED_NUMERICAL_SCALE'}
    if model==models.SLIT:
        return common|{'fixed':{'wavelength_nm':633.,'focal_length_mm':200.,'relative_phase_rad':0.,'measurement_plane':'FOURIER_FOCAL_PLANE'},
                       'bounds':{'slit_width_um':[8.,45.],'slit_separation_um':[130.,230.],'center_shift_mm':[-.3,.3],'amplitude':[.15,2.],'background':[-.15,.25]}}
    return common|{'fixed':{'wavelength_nm':633.,'m2':1.,'propagation':'FREE_SPACE'},
                   'bounds':{'waist_radius_um':[20.,180.],'waist_z_mm':[-100.,180.]}}


def parse(text, model, data):
    kw={'source_kind':data.get('source_kind','USER_PROVIDED'),'source_name':data.get('source_name',''),'license_name':data.get('license','')}
    if model==models.SLIT:return observations.parse_csv(text,position_unit=data.get('position_unit'),**kw)
    if model==models.FILM:
        from .film_inverse import parse_csv
        return parse_csv(text,**kw)
    return gaussian_inference.parse_csv(text,diameter_conversion=data.get('diameter_conversion',False),**kw)


def group_entry(ds, settings, filename):
    return {'dataset':ds,'conditions':models.physical(settings),'scale':settings['scale'],'scale_source':settings['scale_source'],
            'approved':False,'raw_file':filename,'observation':{'kind':'UNKNOWN'}}


def create(store, data):
    allowed={'model','teaching','csv_text','source_kind','source_name','license','position_unit','diameter_conversion'}
    if not isinstance(data,dict) or set(data)-allowed or data.get('model') not in models.MODELS:raise WorkflowError('反向分析导入字段无效')
    model=data['model'];teaching=data.get('teaching') is True;settings=defaults(model)
    if teaching:
        if set(data)-{'model','teaching'}:raise WorkflowError('教学对象与上传资料分开选择')
        if importlib.util.find_spec('numpy') is None:raise WorkflowError('教学数据生成需要可选 NumPy；已有结果仍可查看')
        s=store.create({'kind':'specified','text':'明确选择独立教学模拟器；不控制真实仪器'})
        from . import teaching_acquisition as simulator
        if model==models.FILM:
            from . import film_inverse as film
            commitment=film.teaching_create(store.owner.root/'private-teaching',s['id'])
            text=film.teaching_acquire(store.owner.root/'private-teaching',s['id'],commitment['commitment_sha256'],0,[633.])
        else:
            commitment=simulator.create(store.owner.root/'private-teaching',s['id'],model)
            text=simulator.acquire(store.owner.root/'private-teaching',s['id'],commitment['commitment_sha256'],model=model,acquisition_index=0,
                                   lower=-.6 if model==models.SLIT else -60,upper=.6 if model==models.SLIT else 140,points=81 if model==models.SLIT else 21)
        ds=parse(text,model,{'source_kind':'SYNTHETIC_TEACHING','source_name':'独立冻结教学对象 · 初始采集','license':'CC0-1.0'})
    else:
        text=data.get('csv_text');ds=parse(text,model,data)
        # Imported data never inherits teaching physical facts or search ranges.
        settings['fixed']={};settings['bounds']={}
        s=store.create({'kind':'specified','text':'反向分析 CSV；来源：'+ds['source_name']});commitment=None
    (store.folder(s['id'])/'scan-0.csv').write_bytes(text.encode())
    s.update(kind='inverse',domain='diffraction' if model==models.SLIT else 'gaussian',title='宽度与间距反演' if model==models.SLIT else '高斯光束反演',
             inverse_root=s['id'],inverse_settings=settings,groups=[group_entry(ds,settings,'scan-0.csv')],teaching_object=commitment,
             inverse_profiles={},questions=ds['questions'],parameter_sources={'origin':'EXPLICIT_TEACHING_SELECTION' if teaching else 'USER_CSV_METADATA'},
             inverse_ledger={'fit_runs_reserved':0,'profile_runs_reserved':0,'max_fit_runs':4,'max_profile_runs':6,'acquisitions_reserved':0,'max_acquisitions':2,
                             'residual_calls_reserved':0,'max_residual_calls':300000,'actual_residual_calls':0,'measurement_plans':0,'max_measurement_plans':6,
                             'forward_plans':0,'max_forward_plans':2})
    if model==models.FILM:s.update(domain='film',title='单层膜厚度与补测波长')
    if teaching:s['groups'][0]['observation']={'kind':'POINT_SAMPLE'}
    store.save(s);store.event(s,'INVERSE_IMPORTED',{'source_kind':ds['source_kind'],'dataset_sha256':ds['sha256'],'teaching_object_commitment':commitment})
    return s


def verify(store,s):
    from .contrast_calibration import verify as verify_calibration
    verify_calibration(store,s)
    for proposal in s.get('measurement_history',[])+([s['measurement_plan']] if s.get('measurement_plan') else []):
        if proposal.get('sha256')!=digest({k:v for k,v in proposal.items() if k!='sha256'}):raise WorkflowError('补采建议证据发生变化',409)
    for g in s['groups']:
        p=store.folder(s['id'])/g['raw_file']
        if p.is_symlink() or not p.resolve().is_relative_to(store.folder(s['id']).resolve()):raise WorkflowError('数据路径无效')
        observations.verify(g['dataset'],p.read_bytes())
    if s.get('inverse_plan'):
        p=s['inverse_plan'];models.verify_plan(p)
        if p['groups']!=s['groups'] or p['settings']!=s['inverse_settings']:raise WorkflowError('版本与计划不一致',409)
    if s.get('inverse_job_result'):
        folder=store.folder(s['id'])/'inverse-execution';manifest=json.loads((folder/'manifest.json').read_text())
        for name,h in manifest.items():
            file=folder/name
            if file.is_symlink() or not file.resolve().is_relative_to(folder.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest()!=h:raise WorkflowError('反演证据改变',409)
        result=json.loads((folder/'result.json').read_text())
        if result!=s['inverse_job_result']:raise WorkflowError('反演结果与证据不一致',409)
        if result['operation']=='fit' and result!=s.get('inverse_result'):raise WorkflowError('拟合视图发生变化',409)
        if result['operation']=='profile' and result!=s.get('inverse_profiles',{}).get(result['parameter']):raise WorkflowError('剖面视图发生变化',409)
    # Copied fit/profile evidence remains bound to the immediately preceding version.
    if s.get('inverse_reference_parent'):
        parent=store.get(s['inverse_reference_parent']);verify(store,parent)
        if s.get('inverse_result')!=parent.get('inverse_result') or any(v!=parent.get('inverse_profiles',{}).get(k) for k,v in s.get('inverse_profiles',{}).items() if not s.get('inverse_job_result',{}).get('parameter')==k):raise WorkflowError('继承的反演证据发生变化',409)


def revise(store,s,*,keep_results=False):
    child=store.create({'kind':'specified','text':s['text']})
    for g in s['groups']:(store.folder(child['id'])/g['raw_file']).write_bytes((store.folder(s['id'])/g['raw_file']).read_bytes())
    child.update(kind='inverse',domain=s['domain'],title=s['title']+' · 后续版本',parent_id=s['id'],family_id=s['family_id'],inverse_root=s['inverse_root'],
                 inverse_settings=copy.deepcopy(s['inverse_settings']),groups=copy.deepcopy(s['groups']),teaching_object=s.get('teaching_object'),
                 parameter_sources=copy.deepcopy(s.get('parameter_sources',{})),inverse_profiles={})
    if s.get('comparison_origin'):child['comparison_origin']=copy.deepcopy(s['comparison_origin'])
    if s.get('numerical_recipe'):child['numerical_recipe']=copy.deepcopy(s['numerical_recipe'])
    if s.get('research_goal'):child['research_goal']=copy.deepcopy(s['research_goal'])
    if s.get('acquisition_expectation'):child['acquisition_expectation']=copy.deepcopy(s['acquisition_expectation'])
    if s.get('acquisition_constraints'):child['acquisition_constraints']=copy.deepcopy(s['acquisition_constraints'])
    for key in ('decision_preferences','contrast_calibration','research_origin'):
        if s.get(key):child[key]=copy.deepcopy(s[key])
    for key in ('task_goal_text','task_entry'):
        if key in s:child[key]=copy.deepcopy(s[key])
    if keep_results:
        child.update(inverse_result=copy.deepcopy(s.get('inverse_result')),inverse_profiles=copy.deepcopy(s.get('inverse_profiles',{})),inverse_reference_parent=s['id'])
    store.save(child);return child


def root_record(store,s):return s if s['inverse_root']==s['id'] else store.get(s['inverse_root'])


def reserve(store,s,kind):
    root=root_record(store,s);ledger=root['inverse_ledger']
    field,maximum={'fit':('fit_runs_reserved','max_fit_runs'),'profile':('profile_runs_reserved','max_profile_runs'),
                   'acquisition':('acquisitions_reserved','max_acquisitions'),'measurement':('measurement_plans','max_measurement_plans'),
                   'forward':('forward_plans','max_forward_plans')}[kind]
    cost=30000 if kind in ('fit','profile') else 0
    if ledger[field]>=ledger[maximum] or ledger['residual_calls_reserved']+cost>ledger['max_residual_calls']:raise WorkflowError('同一研究任务累计额度已用完；添加 CSV 或新版本不会重置',409)
    ledger[field]+=1;ledger['residual_calls_reserved']+=cost;store.save(root)
    if root['id']==s['id']:s['revision']=root['revision']
    return ledger[field]


def run_job(store,ident):
    from .executor import solver_mutex, SolverBusyError
    folder=store.folder(ident)/'inverse-execution';actual=0
    try:
        with store.lock:s=store.get(ident);verify(store,s);p=s['inverse_plan']
        folder.mkdir(exist_ok=False);atomic_json(folder/'request.json',{'plan':p,'reference':s.get('inverse_result') if p['operation']=='profile' else None})
        from ..runner import clean_environment
        source=Path(__file__).resolve().parents[2];env=clean_environment()
        env.update(PYTHONPATH=str(source),PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        with solver_mutex(),(folder/'worker.log').open('wb') as log:
            proc=subprocess.run([sys.executable,'-B','-m','photonguard.experiments.inverse_worker',str(folder)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=p['budget']['seconds']+5)
        if proc.returncode:raise ValueError('受限反演进程未完成')
        result=json.loads((folder/'result.json').read_text());actual=result['resources']['actual_residual_calls']
        if result['plan_sha256']!=p['sha256'] or sum(f.stat().st_size for f in folder.iterdir() if f.is_file())>32*1024**2:raise ValueError('结果绑定或输出上限错误')
        atomic_json(folder/'manifest.json',{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir() if f.is_file()})
        with store.lock:
            s=store.get(ident);s.update(status='COMPLETED',inverse_job_result=result)
            if p['operation']=='fit':s['inverse_result']=result
            else:s['inverse_profiles'][result['parameter']]=result
            if s.get('task_execution',{}).get('status')=='RUNNING':
                s['task_execution']['status']='COMPLETED';s['task_execution']['steps'].append({'id':'fit','status':'COMPLETED','result_id':result['id'],'resources':result['resources']})
                s['task_execution']['steps'].append({'id':'receipt','status':'COMPLETED','source':'SAVED_PROGRAM_RESULT','model_calls':0})
            store.save(s);store.event(s,'INVERSE_COMPLETED',{'id':result['id'],'resources':result['resources'],'status':result['status']})
    except Exception as exc:
        with store.lock:
            message=('本次未启动计算：本机已有其他求解任务，已有数据与原结果保留。等待其结束后，可沿用保存的数据另存核对并重新批准；不自动重试、补采或调用 AI，原预留额度保留。' if isinstance(exc,SolverBusyError) else '反演未完整完成；保留原数据和进度，不自动重试。')
            s=store.get(ident);s.update(status='FAILED',error=message,inverse_failure_type=type(exc).__name__)
            if isinstance(exc,SolverBusyError):s['inverse_worker_started']=False
            if s.get('task_execution'):s['task_execution'].update(status='PAUSED',reason=message,error_type=type(exc).__name__)
            if (folder/'progress.json').is_file():
                s['inverse_progress']=json.loads((folder/'progress.json').read_text());actual=s['inverse_progress']['actual_residual_calls']
            store.save(s);store.event(s,'INVERSE_FAILED',{'error_type':type(exc).__name__})
    finally:
        with store.lock:
            s=store.get(ident);root=root_record(store,s);root['inverse_ledger']['actual_residual_calls']+=actual;store.save(root);store.running.discard(ident)


def can_adopt(s):
    r=s.get('inverse_result') or {}
    return bool(r.get('usable_for_forward') and all(not p['warnings'] for p in s.get('inverse_profiles',{}).values()))


def forward(store,s,data):
    if data.get('approve_estimate') is not True or not can_adopt(s):raise WorkflowError('当前证据不支持直接采用一个参数组；先核对或补采')
    if s.get('forward_children'):return store.get(s['forward_children'][0])
    from .case_adaptation import adapt
    from .planner import build_plan
    cfg=s['inverse_settings'];names,_,_=models.layout(s['groups'],cfg);estimate=s['inverse_result']['estimated_parameters']
    p=models.values([estimate[n] for n in names],names,cfg);geometry=data.get('geometry',{})
    if cfg['model']==models.SLIT:
        if not isinstance(geometry,dict) or set(geometry)!={'slit_height_um','grid_size','window_mm'}:raise WorkflowError('请明确缝高和 FFT 网格/窗口')
        pars={k:p[k] for k in ('wavelength_nm','focal_length_mm','relative_phase_rad','slit_width_um','slit_separation_um')}|geometry|{'aperture':'double_slit'}
        goal={'metric':'fringe_period_mm','operator':'near','target':p['wavelength_nm']*.001*p['focal_length_mm']/p['slit_separation_um'],'tolerance':1e-9,'unit':'mm'}
        adapted=adapt({'case_id':'D02','parameters':pars,'goal':goal,'bounds':{'min':p['slit_separation_um'],'max':p['slit_separation_um']}},mode='specified')
    else:
        required={'lens_z_mm','screen_distance_mm','z_max_mm','focal_lengths_mm','target_radius_um'}
        if not isinstance(geometry,dict) or set(geometry)!=required:raise WorkflowError('请明确透镜全局位置、屏幕距离、范围、三项焦距和目标半径')
        fs=geometry['focal_lengths_mm']
        if not isinstance(fs,list) or len(fs)!=3 or any(not models.finite(v) or v<1 or v>10000 for v in fs) or len(set(fs))!=3:raise WorkflowError('请提供三种不同正焦距')
        if not models.finite(geometry['lens_z_mm']) or abs(geometry['lens_z_mm'])>10000 or not models.finite(geometry['target_radius_um']) or geometry['target_radius_um']<=0:raise WorkflowError('透镜坐标与目标半径无效')
        pars={'wavelength_nm':p['wavelength_nm'],'waist_radius_um':p['waist_radius_um'],'waist_z_mm':p['waist_z_mm']-geometry['lens_z_mm'],
              'focal_length_mm':fs[0],'screen_distance_mm':geometry['screen_distance_mm'],'z_max_mm':geometry['z_max_mm']}
        adapted=adapt({'case_id':'G02','parameters':pars,'goal':{'metric':'screen_radius_um','operator':'<=','target':geometry['target_radius_um'],'unit':'um'},'values':fs},mode='specified')
    spec=adapted['spec'];spec['resource_budget'].update(max_candidates=3,max_fast_evaluations=8,max_meep_validations=0,max_fdtd=0)
    for k in pars:
        estimated=k in ('slit_width_um','slit_separation_um','waist_radius_um','waist_z_mm') and k not in cfg['fixed']
        spec['parameter_sources'][k].update(source_kind='MODEL_ESTIMATE' if estimated else 'USER_CONFIRMED',fit_result_id=s['inverse_result']['id'],quote='明确采用模型内估计及确认条件；高斯 waist_z = z0 - lens_z')
    plan=build_plan(spec);reserve(store,s,'forward')
    child=store.create({'kind':'specified','text':'采用 MODEL_ESTIMATE 作有限正向比较；不是实测参数或精度保证'})
    child.update(title='反演后正向比较',parent_id=s['id'],family_id=s['family_id'],domain=s['domain'],spec=plan['spec'],plan=plan,status='PLANNED',library_origin=adapted['provenance'],
                 estimate_origin={'record_id':s['id'],'fit_result_id':s['inverse_result']['id'],'source_kind':'MODEL_ESTIMATE','datasets':[g['dataset']['sha256'] for g in s['groups']],
                                  'coordinate_conversion':{'lens_z_mm':geometry.get('lens_z_mm'),'waist_z_relative_mm':pars.get('waist_z_mm')},'note':'有限模型内估计；非唯一性证明；双缝周期严容差仅同模型自洽'},
                 exploration_root=child['id'],exploration_ledger={'max_fast_evaluations':8,'max_fdtd':0,'stages':0,'reserved_fast':0,'reserved_fdtd':0,'output_limit_bytes':64*1024**2,'used_output_bytes':0})
    store.save(child);s['forward_children']=[child['id']];store.save(s);store.event(child,'MODEL_ESTIMATE_ACCEPTED',child['estimate_origin']);return child


def action(store,s,data):
    verify(store,s);kind=data['type']
    if kind=='inverse_revise':return revise(store,s)
    if kind=='inverse_recipe':
        if s['inverse_settings']['model']!=models.SLIT or s.get('inverse_approved_sha256') or s.get('inverse_result'):raise WorkflowError('数值建议仅补充未批准双缝草稿；已有版本需另存')
        from .observation_dialogue import numerical_recipe
        cfg=copy.deepcopy(s['inverse_settings']);locked={k:v for k,v in cfg['fixed'].items() if k in models.SLIT_PARAMETERS}
        suggested,added,recipe=numerical_recipe(s['groups'][0]['dataset'],cfg)
        for k in locked:
            suggested['bounds'].pop(k,None);added.pop('bounds.'+k,None)
        s.update(inverse_settings=suggested,inverse_plan=None,status='DRAFT',numerical_recipe=recipe)
        s.setdefault('parameter_sources',{})['numerical_suggestions']=added
        store.save(s);store.event(s,'INVERSE_NUMERICAL_SUGGESTION',{'added':added,'recipe':recipe});return s
    if kind=='inverse_ai':
        from .inverse_report import guidance
        return guidance(store,s,data)
    if kind in ('inverse_task_prepare','inverse_task_run','inverse_task_initial_plan'):
        from .task_flow import action as task_action
        return task_action(store,s,data)
    if kind in ('inverse_calibration_example','inverse_calibration_run'):
        from .contrast_calibration import action as calibrate
        return calibrate(store,s,data)
    if kind=='inverse_research_suggest':
        from .research_actions import offline
        return offline(store,s,data)
    if kind=='inverse_research_prepare':
        from .research_steps import prepare
        return prepare(store,s,data)
    if kind=='inverse_research_validate':
        from .research_actions import current
        bundle=s.get('research_actions')
        if not current(s) or not bundle or data.get('suggestion_sha256')!=bundle['sha256']:raise WorkflowError('研究建议已过期，请按当前资料重新核对',409)
        selected=next((a for a in bundle['actions'] if a['id']==data.get('action_id')),None)
        if not selected:raise WorkflowError('研究步骤不存在')
        available={p['id'] for p in (s.get('measurement_plan') or {}).get('plans',[])}
        if selected.get('status') in ('STALE_PROPOSAL','REJECTED') or selected.get('proposal_id') is not None and selected['proposal_id'] not in available:raise WorkflowError('这一步引用的补采方案已过期，请重新比较后核对',409)
        s['research_action_review']={'action_id':selected['id'],'suggestion_sha256':bundle['sha256'],'status':'REVIEWED_NOT_EXECUTED','approval':False}
        store.save(s);store.event(s,'RESEARCH_STEP_REVIEWED',s['research_action_review']);return s
    if kind=='inverse_forward':return forward(store,s,data)
    if kind=='inverse_plan':
        if s.get('inverse_approved_sha256') or s.get('inverse_result'):raise WorkflowError('已计算版本不能重写；请另存设置版本')
        cfg=data.get('settings');entries=data.get('entries')
        if not isinstance(cfg,dict) or cfg.get('model')!=s['inverse_settings']['model']:raise WorkflowError('请核对反向模型')
        if not isinstance(entries,list) or len(entries)!=len(s['groups']):raise WorkflowError('需分别批准各次采集条件及权重')
        groups=copy.deepcopy(s['groups'])
        for g,e in zip(groups,entries):
            if not isinstance(e,dict) or not {'conditions','scale','scale_source','approved'}<=set(e) or set(e)-{'conditions','scale','scale_source','approved','observation','noise'}:raise WorkflowError('每次采集资料不完整')
            g.update(e)
        models.validate(groups,cfg)
        # Explicit form edits are recorded, never silently loosen existing fixed facts.
        changes={k:{'old':v,'new':cfg.get('fixed',{}).get(k)} for k,v in s['inverse_settings'].get('fixed',{}).items() if cfg.get('fixed',{}).get(k)!=v}
        if changes and data.get('approve_corrections') is not True:raise WorkflowError('已有固定事实发生变化，请明确确认更正后保存')
        s.update(groups=groups,inverse_settings=copy.deepcopy(cfg),inverse_plan=models.plan(groups,cfg),status='PLANNED',questions=[],
                 parameter_sources={'origin':'EXPLICIT_USER_FORM','fixed':list(cfg['fixed']),'estimated':list(cfg['bounds']),'corrections':changes})
        store.save(s);store.event(s,'INVERSE_PLAN_REVIEWED',{'plan_sha256':s['inverse_plan']['sha256'],'corrections':changes});return s
    if kind=='inverse_profile_plan':
        refinement=data.get('refinement',False)
        if type(refinement) is not bool:raise WorkflowError('加密选择无效')
        if refinement:
            from .goal_design import candidates
            _,evidence=candidates(s['groups'],s['inverse_settings'],s.get('inverse_result') or {},s['inverse_profiles'])
            if not evidence['refinement_eligible'] or root_record(store,s)['inverse_ledger'].get('refinements_reserved',0):raise WorkflowError('本任务仅允许候选不足时一次有限局部加密；失败点不能靠加密判为排除')
        p=models.plan(s['groups'],s['inverse_settings'],'profile',parameter=data.get('parameter'),grid_points=data.get('grid_points',21),reference=s.get('inverse_result'),refinement=refinement)
        child=revise(store,s,keep_results=True);child.update(inverse_plan=p,status='PLANNED');store.save(child);return child
    if kind=='inverse_run':
        p=s.get('inverse_plan')
        if data.get('approve') is not True or not p or data.get('plan_sha256')!=p['sha256'] or s['status']!='PLANNED':raise WorkflowError('需明确批准当前版本与资源计划',409)
        if not store.owner.allow_workers or getattr(store.owner,'simulation_context',None):raise WorkflowError('当前环境禁止新计算',403)
        if importlib.util.find_spec('scipy') is None:raise WorkflowError('可选 SciPy 未安装；原三类正向入口仍保留',409)
        if s['inverse_settings']['model']==models.FILM and importlib.util.find_spec('tmm') is None:raise WorkflowError('薄膜分析需要可选 tmm；未扣除计算额度',409)
        if store.running:raise WorkflowError('已有计算任务，请等待',409)
        if p.get('profile',{} ) and p['profile'].get('refinement'):
            root=root_record(store,s)
            if root['inverse_ledger'].get('refinements_reserved',0):raise WorkflowError('同一任务的一次加密额度已使用',409)
            # Check ordinary profile and aggregate limits before consuming the extra one-time flag.
            ledger=root['inverse_ledger']
            if ledger['profile_runs_reserved']>=ledger['max_profile_runs'] or ledger['residual_calls_reserved']+30000>ledger['max_residual_calls']:raise WorkflowError('累计资源额度已用完',409)
            ledger['refinements_reserved']=1;store.save(root)
        reserve(store,s,p['operation']);s.update(status='RUNNING',inverse_approved_sha256=p['sha256']);store.save(s);store.running.add(s['id'])
        store.event(s,'INVERSE_APPROVED',{'actor':'EXPLICIT_API_APPROVAL_NOT_PROOF_OF_HUMAN','plan_sha256':p['sha256'],'budget':p['budget']})
        threading.Thread(target=run_job,args=(store,s['id']),daemon=True).start();return s
    if kind=='inverse_measurement_plan':
        if s['inverse_settings']['model']==models.FILM:
            from .film_inverse import propose
            constraints=data.get('constraints',s.get('acquisition_constraints'))
            allowed=s.get('acquisition_constraints',{}).get('wavelengths_nm')
            if allowed and constraints and constraints.get('wavelengths_nm')!=allowed:raise WorkflowError('补测波长需遵守已声明目录；改变目录请先明确更正')
            proposal=propose(s['groups'],s['inverse_settings'],s.get('inverse_result') or {},constraints)
        else:
            from .baseline_design import propose
            proposal=propose(s['groups'],s['inverse_settings'],s.get('inverse_result') or {},s['inverse_profiles'],data.get('constraints',s.get('acquisition_constraints')),data.get('research_goal',s.get('research_goal')),baseline=data.get('baseline'),policy=data.get('policy','conservative'))
            raw_preferences=data.get('decision_preferences',s.get('decision_preferences'))
            if raw_preferences is not None:
                from .decision_preferences import apply
                proposal=apply(proposal,s['groups'],s['inverse_settings'],raw_preferences)
        reserve(store,s,'measurement')
        if s.get('measurement_plan'):s.setdefault('measurement_history',[]).append(s['measurement_plan'])
        s['measurement_plan']=proposal
        s['acquisition_constraints']=copy.deepcopy(proposal['constraints'])
        if proposal.get('research_goal'):s['research_goal']=copy.deepcopy(proposal['research_goal'])
        if proposal.get('decision_preferences'):s['decision_preferences']=copy.deepcopy(proposal['decision_preferences'])
        store.save(s);return s
    if kind=='inverse_append':
        if len(s['groups'])>=3:raise WorkflowError('同一研究任务最多三份采集')
        if data.get('approve') is not True:raise WorkflowError('请明确批准加入新数据；它将作为拟合资料')
        cfg=s['inverse_settings'];teaching=data.get('teaching') is True
        if teaching:
            proposal=s.get('measurement_plan');choice=data.get('proposal_id')
            if not s.get('teaching_object') or not proposal or data.get('proposal_sha256')!=proposal['sha256']:raise WorkflowError('教学补采需当前已核对方案及独立教学对象')
            item=next((r for r in proposal['plans'] if r['id']==choice),None)
            if item is None:raise WorkflowError('请选择当前有限补采方案')
            if item.get('execution_allowed') is False:raise WorkflowError('该方案超过声明的点数或移动上限，请先核对偏好',409)
            index=reserve(store,s,'acquisition')
            from .teaching_acquisition import acquire
            if cfg['model']==models.FILM:
                from .film_inverse import teaching_acquire
                text=teaching_acquire(store.owner.root/'private-teaching',s['inverse_root'],s['teaching_object']['commitment_sha256'],index,item['wavelengths_nm'])
            else:
                text=acquire(store.owner.root/'private-teaching',s['inverse_root'],s['teaching_object']['commitment_sha256'],model=cfg['model'],acquisition_index=index,lower=item['range_mm'][0],upper=item['range_mm'][1],points=item['points'],positions=item.get('prediction_x_mm'))
            ds=parse(text,cfg['model'],{'source_kind':'SYNTHETIC_TEACHING','source_name':f'独立教学补采 {index} · {choice}','license':'CC0-1.0'})
        else:
            text=data.get('csv_text');ds=parse(text,cfg['model'],data)
            if any(ds['raw_sha256']==g['dataset']['raw_sha256'] for g in s['groups']):raise WorkflowError('同一份原始 CSV 已在本组；不能重复加入并当作独立补采')
            reserve(store,s,'acquisition')
        child=revise(store,s);name=f'scan-{len(child["groups"])}.csv';(store.folder(child['id'])/name).write_bytes(text.encode())
        entry=group_entry(ds,cfg,name)
        if teaching:entry['observation']={'kind':'POINT_SAMPLE'}
        # Each new dataset starts unapproved, even when generated by the teaching device.
        child['groups'].append(entry);child['comparison_origin']={'record_id':s['id'],'fit_result_id':s.get('inverse_result',{}).get('id'),'profiles':{k:{'components':v['components'],'grid_spacing':v['grid_spacing']} for k,v in s['inverse_profiles'].items()}}
        if child.get('research_origin',{}).get('status')=='ACQUISITION_SELECTED':
            child['research_origin'].update(status='ACQUISITION_RECEIVED',received_dataset_sha256=ds['sha256'])
        if cfg['model']==models.FILM:child['comparison_origin']['previous_mode_count']=len((s.get('inverse_result') or {}).get('modes',[]))
        proposal=s.get('measurement_plan');choice=data.get('proposal_id')
        if proposal and choice and data.get('proposal_sha256')==proposal['sha256']:
            item=next((p for p in proposal['plans'] if p['id']==choice),None)
            if item:
                expected=item.get('prediction_x_mm',item.get('wavelengths_nm',[]));actual=ds.get('x_mm',ds.get('x_nm',[]))
                matched=len(expected)==len(actual) and all(abs(a-b)<=1e-9*max(1,abs(b)) for a,b in zip(expected,actual))
                child['acquisition_expectation']={'proposal_sha256':proposal['sha256'],'research_goal':proposal.get('research_goal'),'proposal':copy.deepcopy(item),'sampling_positions_match':matched,'previous_estimates':s.get('inverse_result',{}).get('estimated_parameters'),'previous_holdout_rmse':[d.get('holdout_rmse') for d in s.get('inverse_result',{}).get('data',[])],'note':'补采前保存的预期；预测尺度不是实际误差，实测无真值时不宣称误差下降。采样位置不匹配时不是对原方案的执行验证。'}
        child.update(status='DRAFT',questions=['请分别核对新采集条件、配准与权重；补采属于新的拟合资料，不再是独立验证。'])
        store.save(child);store.event(child,'ACQUISITION_APPENDED',{'dataset_sha256':ds['sha256'],'source_kind':ds['source_kind'],'actor':'EXPLICIT_API_APPROVAL_NOT_HUMAN_CERTIFICATION'});return child
    raise WorkflowError('当前反向分析不支持此操作')
