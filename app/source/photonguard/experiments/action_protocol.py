"""Lossless normalization shared by both evaluation arms."""
import json,re

def decode(content,required=None):
    changes=[];text=content.strip()
    match=re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```',text,re.S)
    if match:text=match.group(1);changes.append('SINGLE_JSON_FENCE_REMOVED')
    obj=json.loads(text)
    if isinstance(obj,dict) and set(obj) in ({'response'},{'output'}) and isinstance(next(iter(obj.values())),dict):
        obj=next(iter(obj.values()));changes.append('UNIQUE_OBJECT_WRAPPER_REMOVED')
    if not isinstance(obj,dict):raise ValueError('应用动作必须是JSON对象')
    if obj.get('type')=='json_object' and len(obj)>1:obj.pop('type');changes.append('REDUNDANT_RESPONSE_FORMAT_REMOVED')
    if obj=={'type':'json_object'}:raise ValueError('只有输出格式，没有应用动作')
    if required and not required<=set(obj):raise ValueError('应用动作缺少字段：'+','.join(sorted(required-set(obj))))
    return obj,changes

def canonical_field(field,case):
    """Only a unique public parameter spelling can acquire its namespace."""
    from .fact_state import allowed
    paths=allowed(case)
    if field in paths:return field
    if isinstance(field,str) and '.' not in field and 'parameters.'+field in paths:return 'parameters.'+field
    return field

def check_report(obj,state,case):
    """Separate presentation schema from physical assertions in future studies.

    Frozen first-run scores are never rewritten by this function. Metadata is
    checked against the public case, not silently converted into user authority.
    """
    from .fact_state import equal
    facts=obj.get('facts',{});fields=obj.get('fields',[])
    if not isinstance(facts,dict) or not isinstance(fields,list) or any(not isinstance(f,str) for f in fields):raise ValueError('应用字段格式无效')
    meta={'case_id':case['id'],'variables':case['variables'],'metrics':case['metrics'],'recipe.method':case['recipe']['method'],'recipe.variable':case['recipe']['variable']}
    schema_errors=[];value_errors=[];notes=[];canonical={}
    for key,value in facts.items():
        path=canonical_field(key,case);fact=state['facts'].get(path)
        if path!=key:notes.append({'kind':'PUBLIC_PARAMETER_NAMESPACE_COMPLETED','from':key,'to':path})
        if key in meta:
            if equal(meta[key],value):notes.append({'kind':'VERIFIED_CASE_METADATA','field':key});continue
            value_errors.append(key);continue
        if fact is None:schema_errors.append(key);continue
        if fact['status']=='conflict' and equal(fact['value'],value) and obj['action'] in ('ask','stop','explain','restore'):
            notes.append({'kind':'RETAINED_BASE_VALUE_NOT_ACTIVE_AUTHORITY','field':path});continue
        if fact['status']!='resolved' or not equal(fact['value'],value):value_errors.append(path);continue
        if path in canonical and not equal(canonical[path],value):value_errors.append(path)
        canonical[path]=value
    return {'field_schema_correct':not schema_errors,'facts_correct':not value_errors,'schema_errors':schema_errors,'value_errors':value_errors,
            'fields':[canonical_field(p,case) for p in fields],'normalizations':notes,'facts_reported':len(facts),'gate_pass':not schema_errors and not value_errors}


def audit_commentary(obj,state,case):
    """Optional claims are audited, never read by a command or input compiler."""
    if not isinstance(obj,dict):return {'field_schema_correct':False,'facts_correct':False,'schema_errors':['reply'],'value_errors':[],'raw_commentary_error':True,'unverified_free_text':False}
    try:
        report=check_report({**obj,'fields':[]},state,case)
    except (ValueError,TypeError,KeyError):
        report={'field_schema_correct':False,'facts_correct':False,'schema_errors':['facts'],'value_errors':[],'normalizations':[],'facts_reported':0}
    report.pop('gate_pass',None)
    report['raw_commentary_error']=not (report['field_schema_correct'] and report['facts_correct'])
    report['unverified_free_text']=bool(obj.get('explanation') or obj.get('reason'))
    return report


def validate_command(obj,case):
    if not isinstance(obj,dict):raise ValueError('应用动作必须为对象')
    action=obj.get('action')
    if action not in ('ask','compute','rescore','restore','explain','stop'):raise ValueError('未识别应用动作')
    command={'action':action}
    if action=='ask':
        fields=obj.get('fields',[])
        if not isinstance(fields,list) or any(not isinstance(p,str) for p in fields):raise ValueError('追问字段格式无效')
        from .fact_state import allowed
        fields=[canonical_field(p,case) for p in fields]
        if any(p not in allowed(case) for p in fields):raise ValueError('追问字段不属于当前案例')
        command['fields']=fields
    if action=='restore':
        for key in ('target_id','target_result_sha256'):
            if not isinstance(obj.get(key),str) or not obj[key]:raise ValueError('恢复需要精确记录ID和结果哈希')
            command[key]=obj[key]
    return command


def authorize_command(command,state,*,scope_issue=None,current=None,records=None,stages=0):
    """Necessary semantic checks; store still enforces version/approval/budgets."""
    from .fact_state import refresh
    from ..core import digest
    action=command['action'];state=refresh(state)
    missing={p for q in state['questions'] for p in q['fields']}
    if action in ('compute','rescore'):
        if scope_issue or state['questions']:raise ValueError('范围、缺项或冲突保护阻止计算')
        if action=='compute' and stages>=2:raise ValueError('会话最多两次计算阶段')
        if action=='rescore' and not current:raise ValueError('尚无可复用结果')
    if action=='ask' and (not state['questions'] or any(p not in missing for p in command['fields'])):raise ValueError('追问不是当前真实缺项或冲突')
    if action=='stop' and not (scope_issue or state['questions']):raise ValueError('当前没有需要停止的范围或事实问题')
    if action=='explain' and not (current or scope_issue or state.get('notice')):raise ValueError('尚无实际结果或可解释的状态')
    if action=='restore':
        target=(records or {}).get(command['target_id'])
        if not target or digest(target.get('result'))!=command['target_result_sha256']:raise ValueError('恢复目标ID或哈希不一致')
    return {'authorized':True,'program_assisted_ask':action=='ask' and not command['fields']}


def render_supported_response(state,*,current=None,scope_issue=None,audit=None):
    """No model prose/numbers copied; raw reply remains in the audit record."""
    if current and current.get('result'):
        from .record_view import record_view
        result=record_view(current)
        result['commentary_filtered']=bool(audit and (audit['raw_commentary_error'] or audit['unverified_free_text']))
        # Legacy callers cannot attach an unbound draft's facts to this result.
        # Product callers use record_view(draft, parent) with both record IDs.
        if scope_issue:result['separate_request_warning']='当前要求超出模型范围，不能用此旧结果替代。'
        return result
    result={'rendered_by':'deterministic','commentary_filtered':bool(audit and (audit['raw_commentary_error'] or audit['unverified_free_text'])),
            'facts':{p:f['value'] for p,f in state['facts'].items() if f['status']=='resolved'},'questions':state.get('questions',[])}
    if scope_issue:result['scope_warning']=scope_issue;result['text']='当前模型不支持这项要求，旧结果不能作为该要求的实算结果。'
    elif current and current.get('result'):
        from ..core import digest
        rows=current['result']['candidates'];met=sum(bool(r['goal']['met']) for r in rows)
        result.update(result_id=current['id'],result_sha256=digest(current['result']),goal=current['spec']['goal'],candidate_count=len(rows),met_count=met,
                      text=f'已计算的 {len(rows)} 个候选中，{met} 个达到本版目标。结论仅限这些候选和当前模型。')
    else:result['text']=state.get('notice') or ('请确认列出的条件。' if state.get('questions') else '条件齐备，尚待批准计算。')
    return result
