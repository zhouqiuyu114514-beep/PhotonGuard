"""One authoritative, version-bound view for API, exports, UI and model tools."""
import copy
from ..core import digest
from .fact_state import equal,effective_facts
from .report import table_records,result_brief

def context(record):
    facts={p:copy.deepcopy(f['value']) for p,f in effective_facts(record.get('fact_state',{})).items() if f['status']=='resolved'}
    if not record.get('fact_state'):
        for group,key in [('parameters','known_parameters'),('goal','goal')]:
            facts.update({group+'.'+k:copy.deepcopy(v) for k,v in (record.get('spec') or {}).get(key,{}).items()})
    return {'record_id':record['id'],'revision':record['revision'],'result_sha256':digest(record['result']) if record.get('result') else None,
            'facts':facts,'goal':copy.deepcopy((record.get('spec') or {}).get('goal')),'status':record['status']}

def record_view(record,parent=None):
    active=context(record);result=record if record.get('result') else parent if parent and parent.get('result') else None
    out={'rendered_by':'deterministic','record_id':record['id'],'revision':record['revision'],'status':record['status'],
         'facts':active['facts'],'goal':active['goal'],'questions':copy.deepcopy(record.get('fact_state',{}).get('questions',[])),
         'draft_context':active if not record.get('result') else None,'result_context':context(result) if result else None}
    if record.get('result'):out['questions']=[]
    scope=record.get('session_issue') if not record.get('result') and record.get('session_issue',{}).get('kind')=='UNSUPPORTED_SCOPE' else None
    if scope:out.update(scope_warning={'kind':'UNSUPPORTED_SCOPE','text':'当前理想模型不支持这项要求，旧结果不能重标为该要求的实算。'})
    out['text']='计算正在运行，尚无本轮完成结果。' if record['status']=='RUNNING' else '本轮计算失败，已保存此前条件与结果。' if record['status']=='FAILED' else '请确认所列条件。' if out['questions'] else record.get('session_notice') or record.get('fact_state',{}).get('notice') or '请核对计划，批准后才计算。'
    if result:
        out['brief']=result_brief(result,parent if result is record else None)
        rows=table_records(result);out['candidates']=rows;met=sum(r['goal_met'] is True for r in rows)
        out.update(result_id=result['id'],result_sha256=digest(result['result']),candidate_count=len(rows),met_count=met,
                   assumptions=copy.deepcopy(result['plan'].get('assumptions',[])),resources=copy.deepcopy(result['result'].get('resources',{})))
        if record.get('result'):out['text']=f'本版 {len(rows)} 个实际候选中，{met} 个达到目标；结论限于本模型与这份目录。'
        domain=result['domain']
        out['interpretation']={'basis':'公开模型说明与实际候选表；不是对任意器件的证明','text':
            '高斯模型用束腰位置和半径、透镜焦距及屏幕位置计算屏幕光斑。目录未达标只排除本次比较的焦距；可先核对测量条件，再明确另建目录或修改目标。' if domain=='gaussian' else
            '理想透镜焦平面中，波长、焦距和缝距共同决定条纹周期；二维场计算另作数值校准。收紧容差只改变达标判定，不会改变已计算的条纹。该数据不是自由空间Fresnel传播。' if domain=='diffraction' else
            '薄膜结果限于给定层结构、材料常数和实际波长采样。更换目标采样需检查已有数组是否覆盖，不用插值冒充新实算。'}
    event=record.get('fact_state',{}).get('events',[])
    changes=next((e['changes'] for e in reversed(event) if e.get('changes')),[])
    out['changes']=[{'field':c['field'],'before':(c.get('before') or {}).get('value'),'after':c['after'].get('value')} for c in changes if not equal((c.get('before') or {}).get('value'),c['after'].get('value'))]
    changed={c['field'] for c in out['changes']};out['retained_facts']={p:v for p,v in active['facts'].items() if p not in changed}
    out['next_actions']=['revise_goal','restore_result','export'] if record.get('result') else ['fact_update','undo_fact']
    return out

def view_errors(view,record,parent=None):
    """Compare independently re-read spec/result/facts, not the renderer input."""
    errors=[];expected=context(record)
    for key in ('record_id','facts','goal'):
        if not equal(view.get(key),expected[key]):errors.append('active.'+key)
    result=record if record.get('result') else parent if parent and parent.get('result') else None
    if result:
        card=view.get('result_context') or {};truth=context(result)
        if not equal(card,truth):errors.append('result_context')
        for k,v in result['spec']['goal'].items():
            if 'goal.'+k in card.get('facts',{}) and not equal(card['facts']['goal.'+k],v):errors.append('result_goal.'+k)
        if view.get('result_sha256')!=digest(result['result']):errors.append('result_hash')
    if record.get('result') and (view.get('questions') or view.get('scope_warning')):errors.append('stale_draft_warning')
    return errors
