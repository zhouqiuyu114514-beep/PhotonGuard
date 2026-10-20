"""Recipe actions on the existing workspace; no alternate solver or authority."""
import copy,json,math
from ..workflow import WorkflowError
from ..core import digest
from .case_catalog import get_case,library_digest
from .case_adaptation import adapt,from_text
from .planner import build_plan

def ledger_for(store,root):
    ledger=root['exploration_ledger']
    if 'output_limit_bytes' not in ledger:
        ledger['output_limit_bytes']=root['spec']['resource_budget']['output_mib']*1024*1024
        size=0
        for path in store.root.glob('*/case.json'):
            record=json.loads(path.read_text(encoding='utf-8'))
            if record.get('exploration_root')==root['id']:
                size+=sum(p.stat().st_size for p in (path.parent/'execution').rglob('*') if p.is_file())
        ledger['used_output_bytes']=size;ledger['output_accounting_reconstructed_from_existing_files']=True
    return ledger

def inherit(store,parent,child):
    if parent.get('estimate_origin'):child['estimate_origin']=copy.deepcopy(parent['estimate_origin'])
    if parent.get('exploration_root'):
        child['exploration_root']=parent['exploration_root']
        child['library_origin']=copy.deepcopy(parent.get('library_origin'))
        child['library_origin']['continued_from']=parent['id']
        root=store.get(child['exploration_root']);remaining=ledger_for(store,root)
        if remaining['stages']>=2:raise WorkflowError('本次探索已用完两阶段，请保留结果；新的任务须明确另建探索')
        if child.get('spec'):
            for key,used in [('max_fast_evaluations','reserved_fast'),('max_fdtd','reserved_fdtd')]:
                child['spec']['resource_budget'][key]=min(child['spec']['resource_budget'][key],remaining[key]-remaining[used])
            child['spec']['resource_budget']['max_meep_validations']=min(child['spec']['resource_budget']['max_meep_validations'],child['spec']['resource_budget']['max_fdtd']//8)
            child['spec']['resource_budget']['output_mib']=min(child['spec']['resource_budget']['output_mib'],(remaining['output_limit_bytes']-remaining['used_output_bytes'])//(1024*1024))
            try:child['plan']=build_plan(child['spec'],child.get('parent_context'))
            except ValueError as exc:
                if str(exc).startswith('二维原始场与展示证据预计超出输出预算'):
                    raise WorkflowError('共享输出预算不足以比较这组二维候选；请缩小候选目录，例如明确一个待核对缝距。旧结果保留，未计算。',409) from None
                raise

def apply_plan(store,s,response,parent=None,context=None):
    prov=response.get('provenance',{})
    s['library_context']=context or {'mode':prov.get('mode',s['kind']),'case_id':prov.get('case_id'),'parent_id':parent['id'] if parent else None,'parent_result_sha256':digest(parent['result']) if parent else None}
    if parent:s.update(parent_id=parent['id'],family_id=parent['family_id'])
    if not response.get('plan'):
        s.update(status='NEEDS_INFORMATION',questions=response.get('questions',['请补充资料']),spec=None,plan=None)
        store.save(s);store.event(s,'LIBRARY_PLAN_REJECTED',response);return s
    prov=response['provenance'];s.update(spec=response['spec'],plan=response['plan'],domain=response['spec']['domain'],title=get_case(prov['case_id'])['title'],questions=[],status='PLANNED',library_origin=prov)
    s.pop('error',None)
    if parent:
        s.update(parent_id=parent['id'],family_id=parent['family_id'])
    same=parent and parent.get('library_origin',{}).get('case_id')==prov['case_id'] and parent.get('exploration_root')
    if same:
        origin=copy.deepcopy(s['library_origin']);inherit(store,parent,s);s['library_origin']=origin
    else:
        s['exploration_root']=s['id'];b=s['spec']['resource_budget']
        s['exploration_ledger']={'max_fast_evaluations':b['max_fast_evaluations'],'max_fdtd':b['max_fdtd'],'stages':0,'reserved_fast':0,'reserved_fdtd':0,'output_limit_bytes':b['output_mib']*1024*1024,'used_output_bytes':0,'reservation_policy':'Reserve entire planned attempt before dispatch; failed attempts not refunded; maximum two stages per exploration.'}
    store.save(s);store.event(s,'CASE_ADAPTED',{'provenance':prov,'plan_sha256':s['plan']['sha256'],'new_computation':False});return s

def create(store,data):
    if set(data)-{'case_id','mode','request','text','session_version'}:raise WorkflowError('案例入口字段无效')
    case=get_case(data.get('case_id'));mode=data.get('mode')
    if mode not in ('teaching','specified'):raise WorkflowError('请选择教学示例或我的参数')
    request=copy.deepcopy(data.get('request') or {'case_id':case['id']})
    if request.get('case_id')!=case['id']:raise WorkflowError('案例选择不一致')
    text=data.get('text') or ('用户明确选用教学示例：' if mode=='teaching' else '用户通过参数表提供：')+json.dumps(request,ensure_ascii=False)
    if data.get('session_version')==2:
        from .dialogue_update import action
        s=store.create({'kind':'specified','text':text});s['kind']=mode
        return action(store,s,{'type':'library_plan','case_id':case['id'],'request':request,'text':text,'session_version':2})
    # Validate before creating directories for invalid direct requests.
    response=adapt(request,mode=mode)
    s=store.create({'kind':'specified','text':text});s['kind']=mode
    store.event(s,'CASE_INPUT_MODE_CONFIRMED',{'mode':mode,'teaching_facts_explicitly_selected':mode=='teaching','case_id':case['id']})
    return apply_plan(store,s,response)

def action(store,s,data):
    kind=data['type']
    if kind=='choose_observation_candidate':
        choice=s.get('candidate_choice')
        if not choice or s.get('plan') or data.get('approve_selection') is not True or data.get('choice_sha256')!=choice['sha256']:raise WorkflowError('请明确选择当前预算提示中的候选',409)
        value=data.get('slit_separation_um')
        if type(value) not in (int,float) or value not in choice['values']:raise WorkflowError('只能选择原计划中的明确候选')
        parent=store.verified_case(s['parent_id'])
        if digest(parent['result'])!=choice['parent_result_sha256']:raise WorkflowError('来源结果已改变',409)
        request={'case_id':'D02','parameters':{},'goal':choice['goal'],'bounds':{'min':value,'max':value}}
        result=apply_plan(store,s,adapt(request,mode='specified',parent=parent),parent)
        result['candidate_selection']={'value_um':value,'original_values':choice['values'],'original_bounds':choice['original_bounds'],'choice_sha256':choice['sha256'],'explicitly_selected':True,'grid_changed':False,'new_solver_calls':0}
        result.pop('candidate_choice',None);result['budget_preview']=budget_preview(store,parent,result['plan'])
        store.save(result);store.event(result,'OUTPUT_BOUNDED_CANDIDATE_SELECTED',result['candidate_selection']);return result
    if kind=='restore_result':
        target=store.verified_case(data.get('target_id'))
        if target['family_id']!=s['family_id'] or not target.get('result'):raise WorkflowError('只能恢复同一实验族中有实际结果的版本')
        store.event(s,'EXPLICIT_RESTORE_EXISTING_RESULT',{'target_id':target['id'],'result_sha256':digest(target['result']),'new_solver_calls':0})
        return target
    if kind not in ('library_plan','explore_case'):return None
    if kind=='library_plan' and (s.get('result') or s.get('approved_plan_sha256')):raise WorkflowError('已执行版本不能改写；请选择继续探索')
    if kind=='library_plan' and s.get('parent_context'):raise WorkflowError('原版修订须保留原候选目录；如需目录外候选，请从来源结果明确建立新探索')
    parent=store.verified_case(s['id']) if kind=='explore_case' else None
    if parent and (data.get('new_exploration') is not True or not parent.get('result')):raise WorkflowError('目录外候选须明确建立新探索分支，并保留已选物理条件')
    context=copy.deepcopy(s.get('library_context',{})) if kind=='library_plan' else {}
    if kind=='library_plan' and s.get('parent_id'):
        origin=s.get('library_origin',{})
        parent_id=context.get('parent_id') or origin.get('selected_parent_id')
        expected=context.get('parent_result_sha256') or origin.get('selected_result_sha256')
        if parent_id!=s['parent_id'] or not expected:raise WorkflowError('缺少已核对的探索来源，请从来源结果重新建立探索')
        parent=store.verified_case(parent_id)
        if digest(parent.get('result'))!=expected:raise WorkflowError('来源结果已改变，停止重新规划')
    text=data.get('text',s['text'])
    mode=s['kind'] if not parent else 'specified'
    case_id=data.get('case_id') or context.get('case_id')
    context={'mode':mode,'case_id':case_id,'parent_id':parent['id'] if parent else None,'parent_result_sha256':digest(parent['result']) if parent else None}
    request=data.get('request')
    if data.get('mode')=='live':
        if not isinstance(text,str) or not text.strip() or len(text)>24000:raise WorkflowError('请填写目标与可变范围')
        from ..workflow_model import wire
        if wire.credential_risk(text):raise WorkflowError('请移除API密钥')
        client=store._model(s,data)
        response=from_text(text,client,'case-library-'+s['id']+'-'+str(s['model_calls']),mode=mode,parent=parent,case_id=case_id)
        store.event(s,'CASE_LIBRARY_AI',{'input_text':text,'result':response})
    else:
        if not isinstance(request,dict):raise WorkflowError('请填写案例参数与目标')
        response=adapt(request,mode=mode,parent=parent)
        store.event(s,'CASE_PARAMETERS_CONFIRMED',{'request':request,'mode':mode,'parent_id':parent['id'] if parent else None,'new_model_calls':0})
    context['case_id']=response.get('provenance',{}).get('case_id') or case_id
    if kind=='explore_case':
        child=store.create({'kind':'specified','text':text if data.get('mode')=='live' else '用户明确新探索：'+json.dumps(request,ensure_ascii=False)})
        preview=budget_preview(store,parent,response.get('plan')) if parent.get('estimate_origin') else None
        if preview:child['budget_preview']=preview
        try:return apply_plan(store,child,response,parent,context)
        except (ValueError,WorkflowError) as exc:
            if not parent.get('estimate_origin'):raise
            child.update(status='NEEDS_INFORMATION',parent_id=parent['id'],family_id=parent['family_id'],domain=parent['domain'],
                         spec=None,plan=None,questions=['候选计划未通过约束或累计资源校验；旧结果保留，请核对范围与剩余额度。'])
            if isinstance(exc,WorkflowError):child['questions']=[str(exc)]
            if preview and preview['allowed_candidates']>=1 and preview['requested_candidates']>preview['allowed_candidates'] and response.get('plan') and context['case_id']=='D02':
                choice={'values':[c['parameters']['slit_separation_um'] for c in response['plan']['candidates']],
                    'goal':copy.deepcopy(response['spec']['goal']),'original_bounds':response['provenance']['request']['bounds'],
                    'parent_result_sha256':digest(parent['result'])}
                choice['sha256']=digest(choice);child['candidate_choice']=choice
                child['questions']=[f"原目标提出 {preview['requested_candidates']} 个候选；当前共享预算最多容纳 {preview['allowed_candidates']} 个。可以明确选择一个原候选，再审核新计划；没有改变网格或启动计算。"]
            store.save(child);store.event(child,'EXPLORATION_PLAN_REJECTED',{'error_type':type(exc).__name__,'new_solver_calls':0})
            return child
    return apply_plan(store,s,response,parent,context)

def budget_preview(store,parent,plan):
    if not plan or plan['domain']!='diffraction' or not parent.get('exploration_root'):return None
    root=store.get(parent['exploration_root']);ledger=ledger_for(store,root);p=plan['spec']['known_parameters']
    remaining=max(0,ledger['output_limit_bytes']-ledger['used_output_bytes']);remaining_mib=remaining//(1024**2)
    grid=p.get('grid_size',512);window=p.get('window_mm',.5);wave=p['wavelength_nm'];image=min(grid,2*math.floor(.1*window*1e6/wave)+1)
    one=40*(grid*grid+4*image*image);count=len(plan['candidates']);fast=max(0,ledger['max_fast_evaluations']-ledger['reserved_fast'])
    capacity=max(0,(remaining_mib*1024**2-1024**2)//one)
    capacity=min(capacity,fast//2,plan['spec']['resource_budget']['max_candidates']) if ledger['stages']<2 else 0
    return {'requested_candidates':count,'allowed_candidates':capacity,'estimated_output_bytes':count*one+1024**2,
      'remaining_output_bytes':remaining,'remaining_fft_calls':fast,'required_fft_calls':count*2,'grid_size':grid,'window_mm':window,
      'note':'计算前的保守输出预算；保留原网格、两次 FFT 校准和所有证据。选择不会重置累计额度。'}

def reserve(store,s):
    if not s.get('exploration_root'):return
    root=s if s['exploration_root']==s['id'] else store.get(s['exploration_root'])
    ledger=ledger_for(store,root);plan=s['plan'];fast=len(plan['candidates'])*(2 if plan['domain']=='diffraction' else 1);fdtd=8*plan['resource_budget']['max_meep_validations']
    if ledger['stages']>=2 or ledger['reserved_fast']+fast>ledger['max_fast_evaluations'] or ledger['reserved_fdtd']+fdtd>ledger['max_fdtd']:raise WorkflowError('本次探索的累计阶段/计算额度已用完；不能在细化时重新领取额度')
    if plan['resource_budget']['output_mib']*1024*1024>ledger['output_limit_bytes']-ledger['used_output_bytes']:raise WorkflowError('请重新规划：此探索剩余输出额度不足')
    ledger['stages']+=1;ledger['reserved_fast']+=fast;ledger['reserved_fdtd']+=fdtd
    store.save(root)
    s['exploration_reservation']={'root_id':root['id'],'stage':ledger['stages'],'fast_attempts':fast,'fdtd_attempts':fdtd}
    store.event(s,'EXPLORATION_RESOURCE_RESERVATION',s['exploration_reservation'])

def settle_output(store,s):
    reservation=s.get('exploration_reservation')
    if not reservation or 'settled_output_bytes' in reservation:return
    size=sum(p.stat().st_size for p in (store.folder(s['id'])/'execution').rglob('*') if p.is_file())
    root=s if reservation['root_id']==s['id'] else store.get(reservation['root_id'])
    root['exploration_ledger']['used_output_bytes']+=size
    reservation['settled_output_bytes']=size
    if root is not s:store.save(root)
    store.save(s)
