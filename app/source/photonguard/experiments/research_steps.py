"""Prepare exactly a validated suggestion; execution remains separately approved."""
import copy
from ..workflow import WorkflowError
from . import research_actions as ra


def prepare(store,s,data):
    from . import observation_group as ow, inverse_models as m
    b=s.get('research_actions')
    if not ra.current(s) or not b or data.get('suggestion_sha256')!=b['sha256']:raise WorkflowError('建议已经过期，请重新整理',409)
    a=next((v for v in b['actions'] if v['id']==data.get('action_id')),None)
    if not a or a['status']!='SUGGESTED_ONLY' or a['required_before_execution']:raise WorkflowError('请先补齐该建议列出的条件；尚未准备执行计划',409)
    origin={'request_id':b.get('request_id'),'suggestion_sha256':b['sha256'],'action_id':a['id'],
            'source_kind':b['source_kind'],'kind':a['type'],'proposal_id':a['proposal_id'],
            'reason':a['reason'],'actor':'EXPLICIT_PREPARATION_NOT_EXECUTION_APPROVAL'}
    if a['type']=='compare_acquisition':
        if s['inverse_settings']['model']!=m.FILM and not s.get('decision_preferences'):
            from .decision_preferences import preferences
            s['decision_preferences']=preferences(s['inverse_settings'])
        s=ow.action(store,s,{'type':'inverse_measurement_plan','constraints':s.get('acquisition_constraints')})
        origin.update(status='PROPOSALS_READY',plan_sha256=s['measurement_plan']['sha256'])
    elif a['type']=='refit':
        if not all(g['approved'] for g in s['groups']):raise WorkflowError('每次采集条件尚未核对，请先保存下方条件表单',409)
        if s.get('inverse_result') or s.get('inverse_approved_sha256'):s=ow.revise(store,s)
        s.update(inverse_plan=m.plan(s['groups'],s['inverse_settings']),status='PLANNED',questions=[])
        origin.update(status='FIT_PLAN_READY',plan_sha256=s['inverse_plan']['sha256'])
    elif a['type'] in ('choose_baseline','propose_followup'):
        p=s.get('measurement_plan') or {};item=next((v for v in p.get('plans',[]) if v['id']==a['proposal_id']),None)
        if not item or item.get('execution_allowed') is False:raise WorkflowError('方案不存在或超出硬约束',409)
        origin.update(status='ACQUISITION_SELECTED',plan_sha256=p['sha256'])
    else:
        origin.update(status='READ_ONLY_REVIEWED')
        if a['type']=='stop' and s.get('task_plan'):
            s.setdefault('task_plan_history',[]).append(s.pop('task_plan'))
    s['research_origin']=copy.deepcopy(origin);store.save(s);store.event(s,'AI_RESEARCH_STEP_PREPARED',origin)
    if a['type'] in ('choose_baseline','propose_followup') and s.get('teaching_object'):
        from .task_flow import prepare as prepare_task
        try:return prepare_task(store,s,a['proposal_id'])
        except (WorkflowError,ValueError) as exc:
            s['task_pause_reason']=str(exc);store.save(s)
    return s
