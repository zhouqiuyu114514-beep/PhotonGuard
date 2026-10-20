"""Interactive AI action suggestion using the same public context as studies."""
import copy
from .session_commands import act
from .model_context import build_context,public_command,public_tool_view
from .action_protocol import decode
from ..workflow import WorkflowError

def action(store,record,data):
    if not record.get('fact_state'):raise WorkflowError('请先选择案例并整理资料')
    text=data.get('text','')
    if not isinstance(text,str) or len(text)>24000:raise WorkflowError('本轮文字无效')
    history=copy.deepcopy(record.get('session_public_history',[]))
    if history and record.get('command_receipt'):
        receipt=copy.deepcopy(record['command_receipt']);receipt['available_versions']=store.presentation(record)['available_versions']
        history.append({'role':'tool','content':public_tool_view(record,receipt)})
    if text:record=act(store,record,'session_input',text=text,mode='live',approve_data=data.get('approve_data'))
    if record.get('questions') or record.get('session_issue'):
        record['ai_step']={'status':'NEEDS_INFORMATION','text':'原文核对仍有未确定条件，资料已保留，尚未开始新计算。'}
        store.save(record);return record
    # Always give the model the current verified result context, even when the
    # first calculation was approved through the normal plan button.
    view=store.presentation(record)
    if view.get('result_context'):
        history.append({'role':'tool','content':public_tool_view(record,{'status':'CURRENT_SAVED_RESULT','computed':False,'reused':False,'rendered':view,'available_versions':view.get('available_versions',[])})})
    user=text or record['text'];history.append({'role':'user','content':{'text':user}})
    request,_=build_context(history,record['fact_state'],'S')
    client=store._model(record,data)
    response=client.complete('continuous-ai-'+record['id']+'-'+str(record['model_calls']),request)
    store.event(record,'CONTINUOUS_AI_REPLY',{'response':response,'public_input':request})
    command=public_command(response['assistant']['content'],record['fact_state']['case_id'])
    if command.get('status')=='MODEL_OUTPUT_INVALID':
        record['ai_step']={'status':'MODEL_OUTPUT_INVALID','text':'AI本轮回复格式无效，资料与结果已保留，没有自动重试。'}
    elif command['action']=='compute' and data.get('approve') is not True:
        record['ai_step']={'status':'AWAITING_PLAN_APPROVAL','text':'AI建议计算。请核对当前计划，再使用下方批准按钮。','command':command}
    else:
        obj=decode(response['assistant']['content'],{'action'})[0]
        record=act(store,record,'session_command',command=obj,approve=data.get('approve') is True,plan_sha256=data.get('plan_sha256'))
        record['ai_step']={'status':record['command_receipt']['status'],'command':command,'text':'本轮动作已处理，请查看当前实验记录。'}
    history.append({'role':'assistant','content':command})
    if record.get('command_receipt'):
        receipt=copy.deepcopy(record['command_receipt']);receipt['available_versions']=store.presentation(record)['available_versions']
        history.append({'role':'tool','content':public_tool_view(record,receipt)})
    record['session_public_history']=history;store.save(record);return record
