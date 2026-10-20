"""Single-factor R/S evaluation. Task oracle never enters provider payloads."""
import copy,json,time
from pathlib import Path
from . import fact_state as fs
from .dialogue_update import update,compile_case_plan
from .action_protocol import decode,audit_commentary,validate_command,authorize_command
from .case_catalog import get_case
from .case_workflow import apply_plan
from ..core import digest
from ..product_phase import json_payload
from ..workflow import write_once

SYSTEM='''你在操作有界光学实验工作台。根据同一用户时间线和工具回执，选择本轮一个动作。输出JSON {action:"ask|compute|rescore|restore|explain|stop",fields:[真实缺项或冲突的字段路径],facts:{公开字段路径:当前有效值},target_id:"恢复时的精确记录ID",target_result_sha256:"恢复时的哈希"}。fields和facts可以为空，facts只陈述已经明确的当前事实，不重抄全部表单；可以选parameters.参数名、goal.指标字段、recipe.min/max/values。未知不能用教学值填；没有更正意图的新值与旧值冲突；父结果物理条件锁定。只有事实齐备且用户要新计算时compute；同指标同采样且仅改阈值时rescore，不能把新波长插值冒充实算；解释/等价单位不重复计算；恢复必须引用精确旧结果。每会话最多5次模型调用、2个实际计算阶段，保护层两侧完全相同。普通语言不能任意扩展物理模型。'''

def payload(timeline,case_id,state,arm):
    data={'timeline':copy.deepcopy(timeline),'case':get_case(case_id),'max_compute_stages':2}
    # The only assigned treatment: a program-built effective snapshot.
    if arm=='S':data['effective_facts']={k:v for k,v in state.items() if k in ('facts','questions','issues','revision','parent')}
    return json_payload(SYSTEM,data)

def act(store,s,kind,**kw):
    s=store.get(s['id']);return store.action(s['id'],{'type':kind,'expected_revision':s['revision'],**kw})

def execute(store,s):
    s=act(store,s,'run',approve=True,plan_sha256=s['plan']['sha256'])
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        s=store.get(s['id'])
        if s['status']!='RUNNING' and s['id'] not in store.running:return store.verified_case(s['id'])
        time.sleep(.1)
    raise ValueError('有界计算等待超时')

def score(rows):
    measured=lambda key:sum(r[key] for r in rows) if all(r.get(key) is not None for r in rows) else None
    strict=bool(rows) and all(r.get('expected_action') and r.get('tool_ok') for r in rows)
    return {'score_version':3,'end_to_end':strict,'strict_script_success':strict,
      'final_success':rows[-1].get('final_postconditions_met') if rows else None,'first_try_failure':any(not r.get('expected_action') or not r.get('tool_ok') for r in rows),
      'structure_correct':sum(r['structure_correct'] for r in rows),'facts_correct':sum(r.get('facts_correct',False) for r in rows),
      'repeated_questions':measured('invalid_questions'),'violation_attempts':measured('violation_attempt'),
      'violations_blocked':measured('violation_blocked'),'violations_executed':measured('violation_executed'),
      'new_compute_stages':sum(r.get('computed',False) for r in rows),'reuse_stages':sum(r.get('reused',False) for r in rows),
      'duplicate_compute_attempts':sum(r.get('duplicate_compute_attempt',False) for r in rows),
      'extra_user_field_edits':measured('extra_user_field_edits'),'raw_commentary_errors':sum(r.get('raw_commentary_error',False) for r in rows),
      'delivered_errors':measured('delivered_error'),'model_requests':len(rows),'correct_stops':sum(bool(r.get('expected_action')) and r.get('action')=='stop' for r in rows)}

def run_trial(task,arm,store,call,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);state=fs.seed(task['case_id']);timeline=[];rows=[];current=None;records={};states={};stages=0
    for turn,event in enumerate(task['turns'],1):
        if event.get('undo'):state=fs.undo(state,'undo-'+str(turn))
        elif not event.get('unsupported') and (event.get('form') is not None or event.get('update')):
            state=update(state,event.get('update','用户明确提供资料表'),'input-'+str(turn),request=event.get('form'))
        user={'text':event['text']}
        if event.get('form') is not None:user['provided_form']=event['form']
        timeline.append({'role':'user','content':user})
        request=payload(timeline,task['case_id'],state,arm)
        write_once(out/f'{turn:02d}-request.json',request)
        response=call(turn,request);write_once(out/f'{turn:02d}-response.json',response)
        row={'turn':turn,'structure_correct':False,'computed':False,'reused':False,'tool_ok':False,'expected_action':False}
        feedback={}
        try:
            obj,normalizations=decode(response['assistant']['content'],{'action'})
            action=obj['action'];row.update(action=action,structure_correct=action in ('ask','compute','rescore','restore','explain','stop'),normalizations=normalizations)
            if not row['structure_correct']:raise ValueError('未识别应用动作')
            report=audit_commentary(obj,state,get_case(task['case_id']));command=validate_command(obj,get_case(task['case_id']));fields=command.get('fields',[])
            row.update(report);row['expected_action']=action in event['expected']
            missing={p for q in state['questions'] for p in q['fields']}
            row['repeated_questions']=sum(p not in missing for p in fields) if action=='ask' else 0
            auth=authorize_command(command,state,scope_issue=event.get('unsupported'),current=current,records=records,stages=stages)
            row.update(auth)
            if action=='ask':
                if not missing or any(p not in missing for p in fields):raise ValueError('追问不是当前真实缺项或冲突')
                feedback={'status':'NEEDS_INFORMATION','questions':state['questions']};row['tool_ok']=True
            elif action=='stop':
                justified=bool(event.get('unsupported')) or any(q['kind']=='FACT_CONFLICT' for q in state['questions'])
                if not justified:raise ValueError('当前没有需要停止的范围或锁定冲突')
                feedback={'status':'STOPPED','solver_calls':0};row['tool_ok']=True
            elif action=='compute':
                if event.get('unsupported') or missing:
                    row.update(violation_attempt=True,violation_blocked=True);raise ValueError('范围、缺项或冲突保护阻止计算')
                response_plan=compile_case_plan(state)
                if current and response_plan['plan']['candidates']==current['plan']['candidates'] and response_plan['plan']['goal_sampling_points']==current['plan']['goal_sampling_points']:
                    row['duplicate_compute_attempt']=True;raise ValueError('已有相同实际计算，请解释或重评分')
                if stages>=2:raise ValueError('会话最多两次计算阶段')
                if current:
                    next_record=act(store,current,'revise_goal',goal=response_plan['spec']['goal'])
                else:
                    next_record=store.create({'kind':'specified','text':json.dumps(user,ensure_ascii=False)})
                    next_record['fact_state']=copy.deepcopy(state);next_record['session_version']=2
                    next_record=apply_plan(store,next_record,response_plan)
                current=execute(store,next_record);stages+=1;row['computed']=True
                if current['status']!='COMPLETED':raise ValueError('求解没有完成')
                records[current['id']]=copy.deepcopy(current);row['tool_ok']=True
                # Lock only actual physical values, preserving complete source events.
                for path,f in state['facts'].items():
                    if path.startswith('parameters.') and f['status']=='resolved':f['locked']=True
                state['parent']={'record_id':current['id'],'result_sha256':digest(current['result'])}
                states[current['id']]=copy.deepcopy(state)
            elif action=='rescore':
                if not current or missing or event.get('unsupported'):raise ValueError('尚无可复用结果或存在未解决事实')
                goal=compile_case_plan(state)['spec']['goal'];r=act(store,current,'revise_goal',goal=goal)
                if not r.get('reuse'):raise ValueError('该修改需要新计算，未冒充复用')
                current=r;records[r['id']]=copy.deepcopy(r);states[r['id']]=copy.deepcopy(state);row.update(reused=True,tool_ok=True)
            elif action=='restore':
                target=obj.get('target_id');h=obj.get('target_result_sha256')
                if target not in records or digest(records[target]['result'])!=h:raise ValueError('恢复目标必须匹配精确ID和哈希')
                wanted=next(iter(records))
                if event.get('restore_first') and target!=wanted:raise ValueError('用户要求恢复最初版本')
                current=act(store,current,'restore_result',target_id=target);state=copy.deepcopy(states[target]);row['tool_ok']=True
            elif action=='explain':
                if not current:raise ValueError('尚无实际结果可解释')
                row['tool_ok']=True
            if current:
                feedback.update(current_result={'id':current['id'],'sha256':digest(current['result']),'goal':current['spec']['goal'],
                    'candidates':[{'id':c['id'],'goal':c['goal'],'checks':c['all_checks_passed']} for c in current['result']['candidates']]},
                    available_versions=[{'id':r['id'],'sha256':digest(r['result']),'goal':r['spec']['goal']} for r in records.values()])
        except (ValueError,KeyError,TypeError) as exc:feedback={'status':'REJECTED','reason':str(exc),'solver_dispatched':row['computed']}
        row['feedback']=feedback;rows.append(row)
        timeline.append({'role':'assistant','content':response.get('assistant',{}).get('content')});timeline.append({'role':'tool','content':feedback})
        write_once(out/f'{turn:02d}-judgement.json',row)
    result={'task':task['id'],'arm':arm,'rows':rows,'score':score(rows),'state':state}
    write_once(out/'result.json',result);return result
