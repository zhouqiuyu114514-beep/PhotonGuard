"""A bounded follow-up plan composed from existing approved inverse operations."""
import copy
import uuid
from ..core import digest
from ..workflow import WorkflowError
from . import inverse_models as m,research_actions as ra


def binding(s):return digest(ra.state(s))


def current(s):
    p=s.get('task_plan')
    return bool(p and p.get('sha256')==digest({k:v for k,v in p.items() if k!='sha256'}) and p['state_sha256']==binding(s)
                and not s.get('task_execution',{}).get('started'))


def capacity(store,s):
    from .observation_group import root_record
    ledger=root_record(store,s)['inverse_ledger']
    if ledger['fit_runs_reserved']>=ledger['max_fit_runs'] or ledger['acquisitions_reserved']>=ledger['max_acquisitions'] or ledger['residual_calls_reserved']+30000>ledger['max_residual_calls']:
        raise WorkflowError('同一任务没有足够的补采和拟合额度，连续步骤已暂停',409)


def prepare(store,s,proposal_id):
    from .observation_group import defaults
    if not s.get('teaching_object'):raise WorkflowError('等待你上传新观测；真实任务不能自动生成教学数据',409)
    if len(s['groups'])>=3:raise WorkflowError('同一任务最多三份采集',409)
    cfg=s['inverse_settings'];m.validate(s['groups'],cfg)
    if m.physical(cfg)!=m.physical(defaults(cfg['model'])):raise WorkflowError('当前条件与冻结教学对象的公开条件不同，请分步核对实际新数据',409)
    if cfg['weighting']=='declared_independent_noise' or any(g.get('observation',{}).get('kind') not in ('POINT_SAMPLE','UNKNOWN') for g in s['groups']):
        raise WorkflowError('当前观测核或噪声协议需要逐份核对新数据，请使用分步加入入口',409)
    proposal=s.get('measurement_plan') or {};item=next((p for p in proposal.get('plans',[]) if p['id']==proposal_id),None)
    if not item or item.get('execution_allowed') is False:raise WorkflowError('请选择当前可执行的补采方案',409)
    capacity(store,s)
    origin=s.get('research_origin') or {}
    if origin.get('proposal_id')!=proposal_id or origin.get('plan_sha256')!=proposal['sha256'] or origin.get('status')!='ACQUISITION_SELECTED':origin=None
    p={'schema':'photonguard.user-task-plan.v1','id':uuid.uuid4().hex,'operation':'TEACHING_FOLLOWUP_AND_FIT','state_sha256':binding(s),
       'proposal_id':proposal_id,'proposal_sha256':proposal['sha256'],'selected_proposal':copy.deepcopy(item),
       'settings':copy.deepcopy(cfg),'teaching_object':copy.deepcopy(s['teaching_object']),
       'new_entry':{'conditions':m.physical(cfg),'scale':cfg['scale'],'scale_source':cfg['scale_source'],'observation':{'kind':'POINT_SAMPLE'},'approved':True},
       'steps':[{'id':'acquire','label':'按选定位置从已明确选择的独立教学对象补采'},
                {'id':'review','label':'按本计划列明的相同条件和数值尺度纳入新资料'},
                {'id':'fit','label':'执行一次有限联合拟合'},
                {'id':'receipt','label':'显示已保存结果和变化；停止，等待下一次选择'}],
       'resources':{'teaching_acquisitions':1,'fit_runs':1,'residual_calls_reserved':30000,'model_calls':0,'worker':m.plan(s['groups'],cfg)['budget']},
       'stop_conditions':['方案或资料变化','资源不足','采集失败或数据不符合计划','拟合失败','完成后停止，不自动请求AI'],
       'source':'EXPLICIT_NEW_PLAN_NOT_INHERITED_APPROVAL','approval':False,'research_origin':copy.deepcopy(origin)}
    p['sha256']=digest(p)
    if s.get('task_plan'):s.setdefault('task_plan_history',[]).append(s['task_plan'])
    s['task_plan']=p;s.pop('task_execution',None);s.pop('task_pause_reason',None);store.save(s);return s


def run(store,s,data):
    from . import observation_group as ow
    if data.get('approve') is not True or not current(s) or data.get('plan_sha256')!=s['task_plan']['sha256']:raise WorkflowError('请明确批准当前连续计划；旧批准不能沿用',409)
    if store.running or not store.owner.allow_workers or getattr(store.owner,'simulation_context',None):raise WorkflowError('当前不能启动连续计算',409)
    import importlib.util
    if importlib.util.find_spec('scipy') is None or s['inverse_settings']['model']==m.FILM and importlib.util.find_spec('tmm') is None:raise WorkflowError('分析依赖未就绪，尚未采集或预留计算',409)
    capacity(store,s);p=copy.deepcopy(s['task_plan'])
    receipt={'started':True,'plan_sha256':p['sha256'],'source_record_id':s['id'],'status':'STARTED','steps':[],
             'actor':'EXPLICIT_API_APPROVAL_NOT_PROOF_OF_HUMAN','selected_action_source':(p.get('research_origin') or {}).get('source_kind'),
             'model_action_id':(p.get('research_origin') or {}).get('action_id') if (p.get('research_origin') or {}).get('source_kind')=='LIVE_AI' else None}
    s['task_execution']=copy.deepcopy(receipt);store.save(s);store.event(s,'TASK_PLAN_APPROVED',{'sha256':p['sha256'],'resources':p['resources'],'actor':receipt['actor']})
    active=s
    try:
        active=ow.action(store,s,{'type':'inverse_append','teaching':True,'approve':True,'proposal_id':p['proposal_id'],'proposal_sha256':p['proposal_sha256']})
        receipt['steps'].append({'id':'acquire','status':'COMPLETED','dataset_sha256':active['groups'][-1]['dataset']['sha256']})
        if not (active.get('acquisition_expectation') or {}).get('sampling_positions_match'):raise WorkflowError('新采样位置与批准计划不同，已保留数据并暂停',409)
        entries=[{k:copy.deepcopy(g[k]) for k in ('conditions','scale','scale_source','approved','observation') if k in g} for g in active['groups'][:-1]]+[p['new_entry']]
        active=ow.action(store,active,{'type':'inverse_plan','settings':p['settings'],'entries':entries})
        receipt['steps'].append({'id':'review','status':'COMPLETED','inverse_plan_sha256':active['inverse_plan']['sha256']})
        receipt['status']='RUNNING';active['task_execution']=copy.deepcopy(receipt);active['approved_task_plan']=p;store.save(active)
        active=ow.action(store,active,{'type':'inverse_run','approve':True,'plan_sha256':active['inverse_plan']['sha256']})
        parent=store.get(s['id']);parent['task_execution'].update(status='CONTINUED_IN_CHILD',child_id=active['id']);store.save(parent)
        return active
    except Exception as exc:
        active=store.get(active['id']);receipt.update(status='PAUSED',reason=str(exc),error_type=type(exc).__name__)
        active['task_execution']=receipt;active['approved_task_plan']=p;store.save(active);store.event(active,'TASK_PAUSED',receipt)
        if active['id']!=s['id']:
            parent=store.get(s['id']);parent['task_execution'].update(status='PAUSED_IN_CHILD',child_id=active['id']);store.save(parent)
        return active


def action(store,s,data):
    from . import observation_group as ow
    if data['type']=='inverse_task_run':return run(store,s,data)
    if data['type']=='inverse_task_prepare':return prepare(store,s,data.get('proposal_id'))
    if data['type']=='inverse_task_initial_plan':
        if data.get('confirm_conditions') is not True:raise WorkflowError('请核对已有条件后准备分析计划')
        entries=[{k:copy.deepcopy(g[k]) for k in ('conditions','scale','scale_source','observation','noise') if k in g}|{'approved':True} for g in s['groups']]
        return ow.action(store,s,{'type':'inverse_plan','settings':s['inverse_settings'],'entries':entries})
    raise WorkflowError('未知任务步骤')
