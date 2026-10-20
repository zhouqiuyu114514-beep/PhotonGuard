"""Explicit public projection. Raw model replies and diagnostics stay local."""
import copy,json
from .action_protocol import decode,validate_command
from .case_catalog import get_case
from .fact_state import effective_facts
from ..product_phase import json_payload

SYSTEM='''你操作有界光学实验工作台。只输出一个JSON对象：{action:"ask|compute|rescore|restore|explain|stop",fields:[],facts:{},target_id:"恢复时的记录ID",target_result_sha256:"恢复时的结果哈希"}。facts是可选旁注，不是参数或授权；建议省略无关旁注。fields仅列真实缺项或冲突的公开字段，参数为parameters.参数名、goal.metric/operator/target/tolerance/wavelength_um、recipe.min/max/values。
以原用户资料、公开工具回执和已确认状态为依据，不用教学值代替缺失事实。明确更正才改值；条件和待确认不激活；透镜前负、后正，符号冲突先询问。用户要求计算且条件齐备时compute；同采样只改目标阈值/容差，或把目标波长改为已有结果中实际采样过的波长，用rescore；目标波长不在已有实际采样中时才另行请求compute；解释与保持不重算；restore必须匹配精确记录ID和结果哈希。未达标是候选结果，不是工具失败。不支持的模型范围可stop或解释，不能重标旧结果。每会话最多2个实际计算阶段；批准由独立操作者按真实计划提供，模型无权授权。每次只选择当前一步，不伪造完成。'''

def public_command(reply,case_id):
    try:
        obj=decode(reply,{'action'})[0] if isinstance(reply,str) else reply
        return validate_command(obj,get_case(case_id))
    except (ValueError,KeyError,TypeError):return {'status':'MODEL_OUTPUT_INVALID'}

def public_tool_view(record,receipt):
    view=record.get('experiment_record') or receipt.get('rendered') or {}
    result={'status':receipt.get('status','MODEL_OUTPUT_INVALID'),'code':receipt.get('code','COMMAND_ACCEPTED' if receipt.get('status')=='ACCEPTED' else 'COMMAND_REJECTED'),
            'record_id':record['id'],'revision':record['revision'],'calculation_status':record['status'],
            'computed':bool(receipt.get('computed')),'reused':bool(receipt.get('reused'))}
    keys=('record_id','revision','status','facts','goal','questions','draft_context','result_context','result_id','result_sha256','text','scope_warning','candidates','interpretation','assumptions')
    result['rendered']={k:copy.deepcopy(view[k]) for k in keys if k in view}
    result['available_versions']=[{k:r[k] for k in ('id','sha256','goal') if k in r} for r in receipt.get('available_versions',[])]
    return result

def build_context(timeline,state,arm='S'):
    public=[]
    for event in timeline:
        role=event['role'];content=event['content']
        if role=='assistant':content=public_command(content,state['case_id'])
        elif role=='user':content={k:copy.deepcopy(content[k]) for k in ('text','provided_form') if k in content}
        elif role=='tool':
            # Also sanitize legacy caller-supplied receipts. No raw errors/audits.
            rec={'id':content.get('record_id','unknown'),'revision':content.get('revision'), 'status':content.get('calculation_status','UNKNOWN')}
            content=public_tool_view(rec,content)
        else:continue
        public.append({'role':role,'content':content})
    data={'timeline':public,'case':get_case(state['case_id']),'max_compute_stages':2}
    common=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    extra=None
    if arm=='S':
        extra={'revision':state['revision'],'case_id':state['case_id'],'parent':state.get('parent'),'facts':{p:{k:f.get(k) for k in ('value','status','unit','locked','source_kind')} for p,f in effective_facts(state).items()}}
        data['effective_facts']=extra
    request=json_payload(SYSTEM,data)
    from ..workflow_model import wire
    if wire.credential_risk(request):raise ValueError('PUBLIC_CONTEXT_PREFLIGHT_REJECTED')
    serial=json.dumps(extra,ensure_ascii=False,separators=(',',':')) if extra else ''
    sizes={'common_characters':len(common),'common_utf8_bytes':len(common.encode()),'snapshot_characters':len(serial),'snapshot_utf8_bytes':len(serial.encode()),'component_tokens':'NOT_MEASURED'}
    return request,sizes
