"""Shared product command boundary, used by the public API and bounded trials.

Optional model commentary is recorded but never passed to a parameter compiler.
"""
import copy
from ..core import digest
from ..workflow import WorkflowError
from . import fact_state as fs
from .dialogue_update import update
from .case_catalog import get_case,unsupported_request
from .action_protocol import validate_command,authorize_command,audit_commentary,render_supported_response


def act(store,record,kind,**kw):
    current=store.get(record['id'])
    return store.action(current['id'],{'type':kind,'expected_revision':current['revision'],**kw})


def ingest(store,record,text,*,event_id,request=None,live_data=None):
    """Persist the unedited public input. Completed results stay immutable."""
    if not record.get('result'):
        return act(store,record,'fact_update',text=text,event_id=event_id,request=request,**(live_data or {}))
    parent=store.verified_case(record['id']);state=copy.deepcopy(parent['fact_state'])
    for path,fact in state['facts'].items():
        if path.startswith('parameters.') and fact['status']=='resolved':fact['locked']=True
    state['parent']={'record_id':parent['id'],'result_sha256':digest(parent['result'])}
    preview=update(state,text,event_id,request=request)
    if not preview['events'][-1]['changes'] and not preview['questions'] and not unsupported_request(text):
        # Keep and explanation intents create an audit event, no new result.
        store.event(parent,'SESSION_INPUT_RETAINED',{'event_id':event_id,'text':text,'interpretation':preview['events'][-1].get('interpretation'),'new_solver_calls':0})
        parent['session_notice']=preview.get('notice');store.save(parent);return parent
    child=store.create({'kind':'specified','text':text})
    child.update(session_version=2,fact_state=state,parent_id=parent['id'],family_id=parent['family_id'],
                 library_context={'mode':'specified','case_id':state['case_id'],'parent_id':parent['id'],'parent_result_sha256':digest(parent['result'])})
    changes=preview['events'][-1]['changes']
    effective=[c for c in changes if c['before'] is None or c['before'].get('status')!=c['after'].get('status') or not fs.equal(c['before'].get('value'),c['after'].get('value'))]
    if effective and all(c['field'].startswith('goal.') for c in effective) and not preview['questions']:
        # A goal-only draft may be reviewed even after the compute-stage cap.
        # Reuse/compute authorization remains in dispatch and the original ledger.
        from .dialogue_update import compile_goal_plan
        response=compile_goal_plan(preview,parent)
        child.update(fact_state=preview,spec=response['spec'],plan=response['plan'],status='PLANNED',domain=parent['domain'],title=parent['title']+' · 待确认目标',
                     exploration_root=parent.get('exploration_root',parent['id']),library_origin=response['provenance'])
        store.save(child);store.event(child,'SESSION_RAW_GOAL_INPUT',{'text':text,'event_id':event_id,'source_result_sha256':digest(parent['result']),'new_solver_calls':0})
        return child
    store.save(child)
    return act(store,child,'fact_update',text=text,event_id=event_id,request=request,**(live_data or {}))


def dispatch(store,record,obj,*,approve=False,plan_sha256=None):
    """Store version lock is held by the caller. Runs only an approved real plan."""
    state=fs.refresh(record['fact_state']);case=get_case(state['case_id'])
    current=record if record.get('result') else store.verified_case(record['parent_id']) if record.get('parent_id') else None
    records={}
    for path in store.root.glob('*/case.json'):
        import json
        candidate=json.loads(path.read_text())
        if candidate.get('family_id')==record['family_id'] and candidate.get('result'):records[candidate['id']]=candidate
    scope=record.get('session_issue') if record.get('session_issue',{}).get('kind')=='UNSUPPORTED_SCOPE' else None
    audit=audit_commentary(obj,state,case);command=None;stages=0
    try:
        command=validate_command(obj,case)
        root=store.get(record.get('exploration_root',record['id']));stages=root.get('exploration_ledger',{}).get('stages',0)
        auth=authorize_command(command,state,scope_issue=scope,current=current,records=records,stages=stages)
        action=command['action'];result=record;computed=False;reused=False
        if action=='compute':
            if record.get('result'):raise ValueError('已有本版结果，请解释或重评分')
            if not record.get('plan'):raise ValueError('尚无有效计划')
            if current and record['plan']['candidates']==current['plan']['candidates'] and record['plan']['goal_sampling_points']==current['plan']['goal_sampling_points']:raise ValueError('相同实际采样已存在，请重评分或解释')
            result=act(store,record,'run',approve=approve,plan_sha256=plan_sha256);computed=True
        elif action=='rescore':
            from .result_reuse import compatible
            if not record.get('plan') or not compatible(record['plan'],current['plan']):raise ValueError('当前采样不能复用，需要另行批准计算')
            result=act(store,current,'revise_goal',goal=record['spec']['goal'])
            if not result.get('reuse'):raise ValueError('未获得可核验的复用结果')
            result['fact_state']=copy.deepcopy(state);result['session_version']=2;store.save(result);reused=True
        elif action=='restore':result=act(store,record,'restore_result',target_id=command['target_id'])
        receipt={'status':'ACCEPTED','command':command,'audit':audit,**auth,'computed':computed,'reused':reused,'record_id':result['id'],
                 'execution_approval':{'approve':approve,'supplied_plan_sha256':plan_sha256,'actual_plan_sha256':(record.get('plan') or {}).get('sha256')}}
    except (ValueError,KeyError,TypeError,WorkflowError) as exc:
        result=record
        receipt={'status':'REJECTED','code':'COMMAND_REJECTED','reason':str(exc),'command':command,'audit':audit,'computed':False,'reused':False,'record_id':record['id']}
    receipt['violation_executed']=bool(receipt['computed'] and (not approve or plan_sha256!=record['plan']['sha256'] or state['questions'] or scope))
    receipt['violation_attempt']=bool(command and command['action'] in ('compute','rescore') and receipt['status']=='REJECTED' and (state['questions'] or scope or command['action']=='compute' and (not approve or stages>=2)))
    receipt['violation_blocked']=receipt['violation_attempt'] and not receipt['computed']
    receipt['extra_user_field_edits']=sum(not fs.equal(f,result.get('fact_state',{}).get('facts',{}).get(p)) for p,f in state['facts'].items()) if command and command['action'] not in ('restore','rescore') else None
    receipt['measurement_scope']='Executed command authorization and rendered fact-card values; free prose accuracy not measured. Restore/rescore field-edit counts not measured.'
    # This is a command receipt, not a replacement of the immutable physics result.
    result=store.get(result['id']);result['command_receipt']=receipt;store.save(result)
    store.event(record,'SESSION_COMMAND',{'raw_reply':obj,'receipt':result['command_receipt']})
    return result
