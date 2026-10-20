"""V3 raw-input study. Private scoring labels have no path into ingestion/tools."""
import copy,json,time
from pathlib import Path
from ..core import digest
from ..product_phase import json_payload
from ..workflow import write_once
from .case_catalog import get_case
from .session_commands import act
from .action_protocol import decode
from .session_study import score
from .model_context import build_context,public_command,public_tool_view

from .model_context import SYSTEM


def payload(timeline,state,arm):
    return build_context(timeline,state,arm)


def ingest(store,record,case_id,event,index):
    # Explicit projection removes every private/author-only field.
    text=event['text'];request=event.get('form')
    if record is None:
        record=store.create({'kind':'specified','text':text})
        return act(store,record,'library_plan',session_version=2,case_id=case_id,text=text,request=request,event_id='input-'+str(index))
    return act(store,record,'session_input',text=text,request=request,input_id='input-'+str(index))


def await_result(store,record):
    until=time.monotonic()+90
    while record['status']=='RUNNING' and time.monotonic()<until:
        time.sleep(.1);record=store.get(record['id'])
    if record['status']=='RUNNING':raise ValueError('计算超出固定等待窗口')
    if record.get('result'):store.verified_case(record['id'])
    return record


def feedback(record,store):
    record=store.get(record['id']);receipt=copy.deepcopy(record['command_receipt'])
    receipt['available_versions']=store.presentation(record)['available_versions']
    return public_tool_view(record,receipt)


def operator_approval(record,public):
    """Independent synthetic operator: never use a model-provided approval."""
    plan=record.get('plan');state=record.get('fact_state',{})
    ok=bool(public.get('operator_permits_compute') is True and plan and record['status']=='PLANNED' and not state.get('questions') and plan['domain'] in ('gaussian','diffraction') and not plan['resource_budget']['max_meep_validations'] and len(plan['candidates'])<=3)
    return {'approve':ok,'plan_sha256':plan['sha256'] if ok else None}


def run_session(public,oracle,arm,store,call,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);record=None;timeline=[];rows=[];first=None
    assert len(public['events'])<=5
    for index,event in enumerate(public['events'],1):
        write_once(out/f'{index:02d}-slot.json',{'request_slot':index,'state':'ENTERED_PRODUCT_INPUT','provider_dispatch_implied':False})
        record=ingest(store,record,public['case_id'],event,index)
        timeline.append({'role':'user','content':{'text':event['text'],**({'provided_form':event['form']} if 'form' in event else {})}})
        request,sizes=payload(timeline,record['fact_state'],arm)
        write_once(out/f'{index:02d}-input-state.json',record)
        write_once(out/f'{index:02d}-request.json',request)
        response=call(index,request);write_once(out/f'{index:02d}-response.json',response)
        row={'turn':index,'structure_correct':False,'computed':False,'reused':False,'tool_ok':False,'expected_action':False,'input_sizes':sizes}
        try:
            obj,norm=decode(response['assistant']['content'],{'action'});row.update(action=obj['action'],structure_correct=True,normalizations=norm)
            approval=operator_approval(record,public)
            record=act(store,record,'session_command',command=obj,**approval)
            record=await_result(store,record);receipt=feedback(record,store)
            if record['status']=='FAILED':raise RuntimeError('PHYSICAL_TOOL_FAILED')
            if record.get('result') and first is None:first={'id':record['id'],'sha256':digest(record['result'])}
            internal=record['command_receipt'];row.update(internal);row['tool_ok']=receipt['status']=='ACCEPTED';row.update(internal['audit'])
        except (ValueError,KeyError,TypeError) as exc:
            receipt={'status':'MODEL_OUTPUT_INVALID','code':'MODEL_OUTPUT_INVALID','record_id':record['id'],'revision':record['revision'],'calculation_status':record['status']}
        # Labels are read only after tool execution has finished.
        row['expected_action']=row.get('action') in oracle['acceptable_actions'][index-1]
        row['feedback']=receipt;rows.append(row)
        row['application_parse_ok']=row['structure_correct'];row['command_accepted']=row['tool_ok'];row['tool_started']=bool(row.get('computed'));row['tool_terminal']=record['status'] if record['status'] in ('COMPLETED','FAILED') else None
        fields={p for q in record.get('fact_state',{}).get('questions',[]) for p in q['fields']}
        row['invalid_questions']=sum(p not in fields for p in (row.get('command') or {}).get('fields',[])) if row.get('action')=='ask' else 0
        timeline.extend([{'role':'assistant','content':public_command(response['assistant']['content'],record['fact_state']['case_id'])},{'role':'tool','content':receipt}])
        write_once(out/f'{index:02d}-judgement.json',row)
    actual=[]
    for p in store.root.glob('*/case.json'):
        r=json.loads(p.read_text())
        if r.get('result'):actual.append(r)
    stages=sum(bool(r.get('exploration_reservation')) and not r.get('reuse') for r in actual)
    conditions={'actual_compute_exists':bool(first),'stage_cap':stages<=2,'no_pending_questions':not record['fact_state']['questions']}
    if oracle['final']=='restore_first':
        conditions['exact_restore']=bool(first and record['id']==first['id'] and digest(record['result'])==first['sha256'])
        conditions['actual_rescore']=any(r.get('reuse') for r in actual)
    elif oracle['final']=='catalog_explanation':
        conditions['finite_catalog_unmet']=bool(record.get('result') and all(not c['goal']['met'] for c in record['result']['candidates']))
        conditions['delivered_explanation']=rows[-1].get('action')=='explain' and rows[-1]['tool_ok'] and bool(rows[-1]['feedback'].get('rendered',{}).get('text'))
    rows[-1]['final_postconditions_met']=all(conditions.values())
    result={'public_id':public['id'],'arm':arm,'rows':rows,'score':score(rows),'postconditions':conditions,
            'actual_fast_evaluations':sum(r['result']['resources']['fast_evaluations'] for r in actual),'actual_fdtd_runs':sum(r['result']['resources']['actual_fdtd_runs'] for r in actual),
            'record_id':record['id'],'operator':'SYNTHETIC_USER_UNDER_EXISTING_OWNER_AUTHORIZATION','human_participants':0}
    write_once(out/'result.json',result);return result
