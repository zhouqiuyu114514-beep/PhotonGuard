"""Observation actions on the existing store, revisions, approvals and exports."""
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
from . import inference, observations

SAMPLES = Path(__file__).resolve().parents[1]/'observation_library'


def samples():
    return json.loads((SAMPLES/'catalog.json').read_text())


def create(store, data):
    if set(data)-{'csv_text','position_unit','source_kind','source_name','license','sample_id'}:raise WorkflowError('数据导入字段无效')
    settings=None
    if 'sample_id' in data:
        if set(data)!={'sample_id'}:raise WorkflowError('教学样例和自己的上传数据请分别选择')
        item=next((r for r in samples() if r['id']==data['sample_id']),None)
        if item is None:raise WorkflowError('数据样例不存在')
        text=(SAMPLES/(item['id']+'.csv')).read_text(encoding='utf-8');settings=item['settings']
        dataset=observations.parse_csv(text,source_kind='SYNTHETIC_TEACHING',source_name=item['title'],license_name='CC0-1.0')
    else:
        text=data.get('csv_text')
        dataset=observations.parse_csv(text,position_unit=data.get('position_unit'),source_kind=data.get('source_kind','USER_PROVIDED'),source_name=data.get('source_name',''),license_name=data.get('license',''))
    s=store.create({'kind':'specified','text':'一维双缝观测数据；来源：'+dataset['source_name']})
    (store.folder(s['id'])/'original.csv').write_bytes(text.encode('utf-8'))
    s.update(kind='observation',domain='diffraction',title='数据分析 · '+dataset['source_name'],observation=dataset,
             observation_root=s['id'],fit_settings=settings or {},questions=dataset['questions'],
             analysis_ledger={'max_fit_runs':3,'fit_runs_reserved':0,'max_residual_calls_per_run':12000},sample_id=data.get('sample_id'))
    store.save(s);store.event(s,'OBSERVATIONS_IMPORTED',observations.preview(dataset))
    return s


def verify(store, s):
    observations.verify(s['observation'],(store.folder(s['id'])/'original.csv').read_bytes())
    if s.get('fit_plan') and inference.plan(s['observation'],s['fit_settings'])!=s['fit_plan']:
        raise WorkflowError('拟合计划发生变化',409)
    if s.get('fit_result'):
        folder=store.folder(s['id'])/'fit-execution';manifest=json.loads((folder/'manifest.json').read_text())
        for name,expected in manifest.items():
            p=folder/name
            if p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:raise WorkflowError('拟合证据发生变化',409)
        if json.loads((folder/'result.json').read_text())!=s['fit_result']:raise WorkflowError('拟合视图和原始结果不一致',409)


def run_fit(store, ident):
    folder=store.folder(ident)/'fit-execution'
    try:
        with store.lock:
            s=store.get(ident);verify(store,s);p=s['fit_plan'];dataset=s['observation']
        folder.mkdir(exist_ok=False);atomic_json(folder/'request.json',{'dataset':dataset,'plan':p})
        from ..runner import clean_environment
        from .executor import solver_mutex
        env=clean_environment();source=Path(__file__).resolve().parents[2]
        env.update(PYTHONPATH=str(source)+os.pathsep+str(source/'local-validation/optics-optional-deps'),PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        with solver_mutex(), (folder/'worker.log').open('wb') as log:
            proc=subprocess.run([sys.executable,'-B','-m','photonguard.experiments.inference_worker',str(folder)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=p['settings']['budget']['seconds'])
        if proc.returncode:raise ValueError('受限拟合进程未完成；保留已完成起点和日志，没有自动重试')
        if sum(f.stat().st_size for f in folder.iterdir() if f.is_file())>p['settings']['budget']['output_mib']*1024**2:raise ValueError('拟合输出超限')
        r=json.loads((folder/'result.json').read_text())
        if r['plan_sha256']!=p['sha256'] or r['dataset_sha256']!=dataset['sha256']:raise ValueError('拟合结果绑定不一致')
        atomic_json(folder/'manifest.json',{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir() if f.is_file()})
        with store.lock:
            s=store.get(ident);s.update(status='COMPLETED',fit_result=r);store.save(s);store.event(s,'FIT_COMPLETED',{'result_id':r['id'],'status':r['status'],'resources':r['resources']})
    except Exception as exc:
        with store.lock:
            s=store.get(ident);s.update(status='FAILED',error='拟合未完整完成；已保留原始数据、计划及可用进度，没有自动重试。',fit_failure_type=type(exc).__name__)
            if (folder/'progress.json').is_file():s['fit_progress']=json.loads((folder/'progress.json').read_text())
            store.save(s);store.event(s,'FIT_FAILED',{'error_type':type(exc).__name__,'automatic_retry':False})
    finally:
        with store.lock:store.running.discard(ident)


def forward(store,s,data):
    if data.get('approve_estimate') is not True:raise WorkflowError('请明确确认采用模型估计作为新任务输入')
    verify(store,s);r=s.get('fit_result')
    if not r or not r['usable_for_forward']:raise WorkflowError('当前估计仍需核对；不生成唯一参数的正向任务')
    if s.get('forward_children'):return store.get(s['forward_children'][0])
    geometry=data.get('geometry')
    if not isinstance(geometry,dict) or set(geometry)!={'slit_height_um','grid_size','window_mm'}:raise WorkflowError('请明确缝高和正向计算网格；不能从一维数据推断缝高')
    fixed=s['fit_plan']['settings']['fixed'];d=r['estimated_parameters']['slit_separation_um']
    p={k:v for k,v in fixed.items() if k!='measurement_plane'}|geometry|{'aperture':'double_slit','slit_separation_um':d}
    from .case_adaptation import adapt
    from .planner import build_plan
    goal={'metric':'fringe_period_mm','operator':'near','target':p['wavelength_nm']*p['focal_length_mm']/(1000*d),'tolerance':1e-9,'unit':'mm'}
    adapted=adapt({'case_id':'D02','parameters':p,'goal':goal,'bounds':{'min':d,'max':d}},mode='specified')
    spec=adapted['spec'];spec['resource_budget'].update(max_candidates=3,max_fast_evaluations=8,max_meep_validations=0,max_fdtd=0)
    for k in p:
        spec['parameter_sources'][k].update(source_kind='MODEL_ESTIMATE' if k=='slit_separation_um' else 'USER_CONFIRMED',
           dataset_hash=s['observation']['sha256'],fit_result_id=r['id'],quote='用户确认的模型输入：'+k+'='+str(p[k])+'；拟合记录 '+s['id'])
    plan=build_plan(spec)
    child=store.create({'kind':'specified','text':'用户确认采用模型估计作正向核对；MODEL_ESTIMATE；来源数据 '+s['observation']['sha256']})
    child.update(title='拟合后正向核对',parent_id=s['id'],family_id=s['family_id'],domain='diffraction',spec=plan['spec'],plan=plan,status='PLANNED',
                 estimate_origin={'source_kind':'MODEL_ESTIMATE','dataset_hash':s['observation']['sha256'],'fit_result_id':r['id'],'record_id':s['id'],
                   'note':'x0、幅度和背景仅为观测干扰参数，不改为器件参数；FFT与解析只在实际 FFT 坐标核对。周期容差 1e-9 mm 仅检查同模型数值自洽，不是用户的器件性能目标。'},
                 library_origin=adapted['provenance'],exploration_root=child['id'],
                 exploration_ledger={'max_fast_evaluations':8,'max_fdtd':0,'stages':0,'reserved_fast':0,'reserved_fdtd':0,
                    'output_limit_bytes':64*1024**2,'used_output_bytes':0,'reservation_policy':'1 forward candidate (2 FFT) plus at most 3 new-goal candidates (6 FFT); explicit approvals'})
    store.save(child);s['forward_children']=[child['id']];store.save(s)
    store.event(child,'MODEL_ESTIMATE_ACCEPTED',child['estimate_origin']);return child


GUIDANCE = {'review_conditions':'先核对单位、测量平面及固定条件；未知项不能由拟合补成已知。',
            'fit':'可以核对当前拟合计划，明确批准后运行；AI 没有自动启动拟合。',
            'review_residuals':'请查看训练/留出残差、全部起点及诊断；收敛不代表唯一真实参数。',
            'forward':'可确认采用模型估计，补齐缝高和网格，另建正向核对计划。',
            'new_goal':'正向核对后，可另建 D02 目标探索；只改变明确允许的缝距范围。'}


def guidance(store,s,data):
    text=data.get('text','')
    if not isinstance(text,str) or not 1<=len(text)<=6000:raise WorkflowError('请简要填写当前问题')
    from ..workflow_model import wire
    if wire.credential_risk(text):raise WorkflowError('请勿发送密钥')
    problems,missing=inference.issues(s['observation'],s.get('fit_settings') or {})
    allowed=['review_conditions'] if problems else ['fit'] if not s.get('fit_result') else ['review_residuals','forward','new_goal'] if s['fit_result'].get('usable_for_forward') else ['review_residuals']
    from .inference_report import view
    from ..product_phase import json_payload
    prompt='你帮助光电初学者理解数据任务。只返回 JSON {next_action:允许动作之一,missing_fields:缺失字段列表}。根据用户意图、当前状态选择下一步。不能填补未知参数、报告置信百分比、改写数值、批准计算或把MODEL_ESTIMATE当USER_MEASURED。返回缺失字段必须来自给定列表。'
    client=store._model(s,data)
    try:
        answer=client.complete('observation-ai-'+s['id']+'-'+str(s['model_calls']),json_payload(prompt,{'question':text,'observation_record':view(s),'missing_fields':missing,'problems':problems,'allowed_actions':allowed}))
        store.event(s,'OBSERVATION_AI_RESPONSE',{'response':answer,'public_input':text})
        obj=json.loads(answer['assistant']['content'])
        if set(obj)!={'next_action','missing_fields'} or obj['next_action'] not in allowed or not isinstance(obj['missing_fields'],list) or set(obj['missing_fields'])!=set(missing):raise ValueError('Ungrounded guidance')
        s['fit_ai_guidance']={'status':'ACCEPTED','action':obj['next_action'],'missing_fields':missing,'text':GUIDANCE[obj['next_action']],'basis':'AI 选择动作；文字与数值由当前记录确定性呈现。'}
    except Exception as exc:
        s['fit_ai_guidance']={'status':'NEEDS_REVIEW','text':'本次 AI 建议未通过或未完整返回；资料保留，未自动拟合或重试。'}
        store.event(s,'OBSERVATION_AI_FAILED',{'error_type':type(exc).__name__})
    store.save(s);return s


def action(store,s,data):
    kind=data['type'];verify(store,s)
    if kind=='fit_wizard':
        from .observation_dialogue import request
        return request(store,s,data)
    if kind=='fit_ai':return guidance(store,s,data)
    if kind=='fit_forward':return forward(store,s,data)
    if kind=='fit_revise':
        child=store.create({'kind':'specified','text':s['text']})
        (store.folder(child['id'])/'original.csv').write_bytes((store.folder(s['id'])/'original.csv').read_bytes())
        child.update(kind='observation',domain='diffraction',title=s['title']+' · 新设置',parent_id=s['id'],family_id=s['family_id'],
                     observation=copy.deepcopy(s['observation']),observation_root=s['observation_root'],fit_settings=copy.deepcopy(s.get('fit_settings') or {}),
                     observation_facts=copy.deepcopy(s.get('observation_facts',{})),numerical_recipe=copy.deepcopy(s.get('numerical_recipe')),questions=[])
        store.save(child);return child
    if kind=='fit_plan':
        if s.get('fit_result') or s.get('fit_approved_sha256'):raise WorkflowError('已批准的拟合版本不可重写；请另建设置版本')
        settings=data.get('settings');problems,missing=inference.issues(s['observation'],settings)
        from .observation_dialogue import facts,flattened
        state=facts(s)
        if isinstance(settings,dict):
            for path,value in flattened(settings).items():
                if path not in state or state[path]['status']!='resolved' or state[path]['value']!=value:
                    state[path]={'value':copy.deepcopy(value),'status':'resolved' if value is not None else 'unknown','source_kind':'USER_FORM','evidence':[]}
        s['observation_facts']=state
        s.update(fit_settings=copy.deepcopy(settings),questions=problems,missing_fields=missing,fit_plan=None,status='NEEDS_INFORMATION')
        s.pop('fit_ai_guidance',None)
        if not problems:s.update(fit_plan=inference.plan(s['observation'],settings),status='PLANNED')
        store.save(s);store.event(s,'FIT_PLAN_REVIEWED',{'dataset_sha256':s['observation']['sha256'],'plan':s.get('fit_plan'),'questions':problems});return s
    if kind=='fit_run':
        if data.get('approve') is not True or not s.get('fit_plan') or data.get('plan_sha256')!=s['fit_plan']['sha256'] or s['status']!='PLANNED':raise WorkflowError('请批准当前数据与拟合计划，旧确认不能复用',409)
        if not store.owner.allow_workers or getattr(store.owner,'simulation_context',None):raise WorkflowError('当前环境禁止新计算',403)
        if importlib.util.find_spec('scipy') is None:raise WorkflowError('可选数据分析依赖 SciPy 未安装；原有 RC2 功能仍可使用',409)
        if store.running:raise WorkflowError('已有计算任务，请稍候',409)
        root=store.get(s['observation_root']) if s['observation_root']!=s['id'] else s
        ledger=root['analysis_ledger']
        if ledger['fit_runs_reserved']>=ledger['max_fit_runs']:raise WorkflowError('同一数据任务已用完 3 次拟合额度；保留失败与旧结果',409)
        ledger['fit_runs_reserved']+=1
        if root is not s:store.save(root)
        s.update(status='RUNNING',fit_approved_sha256=s['fit_plan']['sha256']);store.running.add(s['id']);store.save(s)
        store.event(s,'FIT_APPROVED',{'actor':'EXPLICIT_API_APPROVAL','note':'API 请求不证明操作者是真人；自动验收另记操作者来源。','plan_sha256':s['fit_plan']['sha256'],'resource_budget':s['fit_plan']['settings']['budget']})
        threading.Thread(target=run_fit,args=(store,s['id']),daemon=True).start();return s
    raise WorkflowError('数据任务不支持此操作；原正向实验入口仍可使用')
