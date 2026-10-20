"""Host-owned request context and independently checked research suggestions.

No model output can approve execution. A fact patch is atomic; an invalid
independent suggestion does not discard source-bound facts or read-only advice.
"""
import copy
import json
import re
import uuid
from ..core import digest
from ..workflow import WorkflowError, write_once
from . import advice_contract as contract, research_actions as actions

READ_ONLY={'explain','clarify_fact','inspect_observation','request_calibration','stop'}
PREFERENCE_FIELDS=list(actions.PREFERENCE_FIELDS)


def snapshot(s,ledger):
    return {'state':actions.state(s),'preferences':s.get('decision_preferences'),
            'calibration_id':(s.get('contrast_calibration') or {}).get('id'),'ledger':ledger}


def catalog(s,text):
    entries=[{'id':'E0','kind':'CURRENT_QUESTION','text':text},
             {'id':'E1','kind':'SAVED_FACTS','source':'已保存条件与来源；历史事实不授权修改本轮条件'}]
    if s.get('inverse_result'):entries.append({'id':'E2','kind':'FIT_RESULT','result_id':s['inverse_result']['id']})
    if s.get('measurement_plan'):entries.append({'id':'E3','kind':'SAVED_PROPOSALS','proposal_ids':[p['id'] for p in s['measurement_plan']['plans']],
                                               **actions.proposal_availability(s)})
    if s.get('contrast_calibration'):entries.append({'id':'E4','kind':'CONTRAST_AT_FREQUENCY','result':s['contrast_calibration']})
    for i,(key,p) in enumerate(sorted(s.get('inverse_profiles',{}).items())):
        entries.append({'id':'P'+str(i),'kind':'PROFILE','parameter':key,'result_id':p.get('id')})
    return entries


def capture(store,s,text):
    from .observation_group import root_record
    evidence=catalog(s,text)
    ctx={'request_id':uuid.uuid4().hex,'record_id':s['id'],'revision':s['revision'],
         'facts_sha256':digest(snapshot(s,root_record(store,s)['inverse_ledger'])),
         'evidence_catalog':evidence,'evidence_sha256':digest(evidence),
         'input_binding':actions.binding(s),'contract_sha256':digest(contract.SCHEMA)}
    folder=store.folder(s['id'])/'ai-requests'/ctx['request_id'];folder.mkdir(parents=True,exist_ok=False)
    write_once(folder/'context.json',ctx)
    return ctx


def still_current(store,s,ctx):
    from .observation_group import root_record
    return (s['id']==ctx['record_id'] and s['revision']==ctx['revision'] and
            digest(snapshot(s,root_record(store,s)['inverse_ledger']))==ctx['facts_sha256'])


def preference_patch(cfg,prefs,field,value,quote,text):
    from .decision_preferences import preferences
    if not isinstance(quote,str) or not quote or quote not in text:raise ValueError('偏好需要本轮原话')
    if re.search(r'如果|假设|例如|是否|不确定',quote):raise ValueError('假设不是已声明偏好')
    p=preferences(cfg,prefs);key=field.split('.')[1]
    if key=='mode':
        valid=value=='BASELINE_FIRST' and re.search('基础|简单|基线',quote) or value=='CONDITIONAL_EXPLORATION' and re.search('允许|接受|愿意',quote) and '探索' in quote
        if not valid:raise ValueError('偏好模式与原话不符')
        p['mode']=value
    elif key=='protected_parameter':
        aliases={'slit_width_um':'缝宽','slit_separation_um':'缝距|间距','waist_radius_um':'束腰半径','waist_z_mm':'束腰位置'}
        if value not in aliases or not re.search(aliases[value],quote) or not re.search('不.*(?:牺牲|变差|恶化)|保护|保持',quote):raise ValueError('保护对象与原话不符')
        # Explicit default: zero *predicted-scale* increase, not zero true error.
        p['protected_scale_increase']={value:0.}
    elif key=='max_travel_mm':
        m=re.search(r'(?:行程|移动).{0,12}?([\d.]+)\s*(mm|毫米)',quote)
        if not m or type(value) not in (float,int) or float(m[1])!=value:raise ValueError('最大行程需明确数值与单位')
        p[key]=value
    else:raise ValueError('不支持的偏好字段')
    p['source']='USER_TEXT';return preferences(cfg,p)


def patch_facts(s,updates,text):
    """Validate the complete patch before writing anything."""
    from .inverse_report import grounded
    from .goal_design import goal
    from .inverse_models import SLIT
    cfg=copy.deepcopy(s['inverse_settings']);g=copy.deepcopy(s.get('research_goal'));design=copy.deepcopy(s.get('acquisition_constraints',{}));prefs=copy.deepcopy(s.get('decision_preferences'))
    seen=set();ids=set();evidence=[];allowed=actions.fact_fields(s)
    for op in updates:
        contract.check(contract.UPDATE,op)
        field=op['field'];value=op['value'];quote=op['quote']
        if field not in allowed or field.startswith('observation.') or field in seen or op['id'] in ids:raise ValueError('条件字段未知或重复')
        ids.add(op['id']);seen.add(field)
        if field.startswith('preference.'):
            prefs=preference_patch(cfg,prefs,field,value,quote,text)
        else:
            grounded(field,value,quote,text);role,key=field.split('.')
            if role=='goal':g=goal(cfg['model'],{**(g or {}),'target':value,'source':'USER_TEXT'})
            elif role=='design':
                if key=='points' and cfg['model']==SLIT and value<20:raise ValueError('双缝补采至少20点；不扩大用户机会')
                design[key]=value
            else:
                other='bounds' if role=='fixed' else 'fixed'
                existing=key in cfg.get(role,{}) or key in cfg.get(other,{})
                same=cfg.get(role,{}).get(key)==value and key not in cfg.get(other,{})
                if existing and not same and not(op['correction'] and re.search('更正|改为|改成',text)):raise ValueError('已有事实冲突，请明确更正')
                # A reply may not give both a fixed value and a bound for one parameter.
                if other+'.'+key in seen:raise ValueError('固定量与待估量不能同时设置')
                cfg.setdefault(role,{})[key]=copy.deepcopy(value);cfg.setdefault(other,{}).pop(key,None)
        evidence.append(op|{'source_kind':'USER_TEXT','text_sha256':digest(text)})
    return cfg,g,design,prefs,evidence


def receive(store,s,text,answer,ctx):
    """Receiver used by the product and offline protocol fixtures alike."""
    from .observation_group import root_record,revise
    from .inverse_report import explain
    folder=store.folder(ctx['record_id'])/'ai-requests'/ctx['request_id']
    write_once(folder/'response.json',answer)
    latest=store.get(ctx['record_id'])
    if not still_current(store,latest,ctx):
        receipt={'validation_status':'STALE_CONTEXT','request_id':ctx['request_id'],'applied':False}
        write_once(folder/'receipt.json',receipt);store.event(latest,'INVERSE_AI_STALE',receipt)
        return latest
    s=latest
    if s.get('research_actions'):s.setdefault('research_actions_history',[]).append(s.pop('research_actions'))
    try:
        obj=json.loads(answer['assistant']['content']);contract.check(contract.SCHEMA,obj,envelope=True)
    except (ValueError,TypeError,KeyError):
        s['inverse_ai']={'status':'NEEDS_REVIEW','validation_status':'PROTOCOL_INVALID','request_id':ctx['request_id'],
                         'focus':'limitations','text':'AI 回复格式未通过核对，未提取自由文本或执行任何步骤。'}
        write_once(folder/'receipt.json',s['inverse_ai']);store.save(s);return s
    errors=[];patch_error=None;before=copy.deepcopy(s)
    try:cfg,g,design,prefs,evidence=patch_facts(s,obj['updates'],text)
    except (ValueError,TypeError,KeyError) as exc:patch_error=str(exc);evidence=[]
    valid=[];seen=set();suggestion_ids=set();ids={op.get('id') for op in obj['updates'] if isinstance(op,dict) and isinstance(op.get('id'),str)}
    refs={e['id'] for e in ctx['evidence_catalog']}
    for i,item in enumerate(obj['suggestions']):
        try:
            contract.check(contract.SUGGESTION,item)
            kind=item['kind']
            if kind in seen:raise ValueError('步骤重复')
            if item.get('id') in suggestion_ids:raise ValueError('建议短编号重复')
            if not item['evidence_refs'] or any(r not in refs for r in item['evidence_refs']):raise ValueError('引用不在本轮证据目录')
            if any(d not in ids for d in item['depends_on']):raise ValueError('依赖不存在的条件更新')
            legacy={'type':kind,'reason':item['reason'],'proposal_id':item['proposal_id'],'fact_fields':item['fields'],'quote':''}
            entry=actions.validate(s,{'input_binding':ctx['input_binding'],'actions':[legacy]},text,ctx['input_binding'],ledger=root_record(store,s)['inverse_ledger'])['actions'][0]
            entry.update(evidence_refs=item['evidence_refs'],depends_on=item['depends_on'],reason_verification='AI_REASON_NOT_PROGRAM_FACT',model_suggestion_id=item.get('id'))
            if item.get('id'):suggestion_ids.add(item['id'])
            valid.append(entry);seen.add(kind)
        except (ValueError,TypeError,KeyError) as exc:errors.append({'index':i,'status':'REJECTED','reason':str(exc)})
    facts_changed=False
    if patch_error is None:
        facts_changed=cfg!=s['inverse_settings']
        planning_changed=facts_changed or g!=s.get('research_goal') or design!=s.get('acquisition_constraints',{}) or prefs!=s.get('decision_preferences')
        if planning_changed and s.get('measurement_plan'):s.setdefault('measurement_history',[]).append(s.pop('measurement_plan'))
        history=copy.deepcopy(s.get('measurement_history',[]))
        if facts_changed:
            if s.get('inverse_approved_sha256') or s.get('inverse_result'):s=revise(store,s)
            if history:s['measurement_history']=history
            s.update(inverse_settings=cfg,inverse_plan=None,status='DRAFT',questions=['AI 条件草稿需逐次核对，尚未批准计算。'])
            for group in s['groups']:group['approved']=False
        if g:s['research_goal']=g
        if design:s['acquisition_constraints']=design
        if prefs:s['decision_preferences']=prefs
        if evidence:s.setdefault('parameter_sources',{})['latest_text_evidence']=evidence
    if valid:
        bundle={'schema':'photonguard.research-actions.v2','source_kind':'LIVE_AI','request_id':ctx['request_id'],
                'input_binding':ctx['input_binding'],'state_binding':actions.state(s),'actions':valid,
                'approval':False,'executed':False,'note':'AI 建议与已核验的计算结果分开；实际执行需单独批准。'}
        bundle=actions.rebind(bundle,s)
        for entry in bundle['actions']:
            if patch_error and (entry['type'] not in READ_ONLY or entry['depends_on']):
                entry['required_before_execution'].append('FACT_PATCH_REJECTED');entry['status']='NEEDS_REVIEW'
            if facts_changed and entry['type'] not in READ_ONLY:
                entry['required_before_execution'].append('FACTS_NEED_REVIEW');entry['status']='NEEDS_REVIEW'
            proposal=next((p for p in (s.get('measurement_plan') or {}).get('plans',[]) if p['id']==entry['proposal_id']),None)
            if proposal and proposal.get('execution_allowed') is False and entry['type'] not in READ_ONLY:
                entry['required_before_execution'].append('HARD_CONSTRAINT_VIOLATION');entry['status']='NEEDS_REVIEW'
        primary=obj.get('primary_suggestion_id')
        chosen=next((v for v in bundle['actions'] if v.get('model_suggestion_id')==primary),None) if primary else None
        bundle['primary_action_id']=chosen['id'] if chosen else None
        bundle['primary_selection_source']='MODEL_EXPLICIT_SELECTION' if chosen else 'NO_MODEL_SELECTION'
        if primary and not chosen:errors.append({'index':'primary_suggestion_id','status':'REJECTED','reason':'主建议未引用通过核对的建议短编号'})
        bundle.pop('sha256',None);bundle['sha256']=digest(bundle);s['research_actions']=bundle
    elif obj.get('primary_suggestion_id'):
        errors.append({'index':'primary_suggestion_id','status':'REJECTED','reason':'主建议未引用通过核对的建议短编号'})
    status='FACT_PATCH_REJECTED' if patch_error else 'PARTIAL_VALID' if errors else 'ALL_VALID'
    s['inverse_ai']={'status':'ACCEPTED' if status=='ALL_VALID' else status,'validation_status':status,'request_id':ctx['request_id'],
                     'focus':obj['focus'],'updates':evidence,'patch_error':patch_error,'rejected_suggestions':errors,
                     'valid_suggestion_count':len(valid),'raw_contract_valid':False,'text':explain(s,obj['focus']),
                     'text_source':'PROGRAM_SAVED_FACTS','reason_source':'AI_UNVERIFIED_EXPLANATION','approved':False}
    try:contract.check(contract.SCHEMA,obj);s['inverse_ai']['raw_contract_valid']=True
    except ValueError:pass
    receipt=copy.deepcopy(s['inverse_ai'])|{'output_record_id':s['id'],'facts_changed':facts_changed,'executed':False}
    write_once(folder/'receipt.json',receipt);store.save(s);store.event(s,'INVERSE_AI_CHECKED',receipt)
    return s


def guide(store,s,data):
    from ..workflow_model import wire
    from ..product_phase import json_payload
    from .inverse_report import view
    text=data.get('text','')
    if not isinstance(text,str) or not 1<=len(text)<=6000:raise WorkflowError('请填写问题或本次条件')
    if wire.credential_risk(text):raise WorkflowError('请勿发送密钥')
    client=store._model(s,data);ctx=capture(store,s,text)
    prompt='''你是 PhotonGuard AI 研究助手。只返回契约定义的 JSON 根对象，不包 response、不复制哈希、不批准或执行。
每条建议给唯一短 id（如S1）。primary_suggestion_id 指向你认为当前主要的一条；没有充分选择依据时填null，明确并列。最多两条用途不同的备选即可。主建议选择不是执行批准。已有计划可直接选具体方案，不要要求重填已有条件。用户要求停止时优先提出stop；解释变化从已保存的task_summary/结果回执出发。
E3的currently_feasible_proposal_ids和blocked_proposals来自本次已保存计划。用户要求“在当前约束内选下一步”时，主建议只能从可行ID中选择，或澄清、解释、停止；不得将blocked_proposals中的方案作为当前可准备的主计划。没有可行方案时说明限制，不自动放宽条件。可行方案若只是重复扫描、不能解决覆盖不足，可以说明价值有限并停止，不强迫补采。
用户仅讨论“如果改变条件会怎样”时，用explain等只读步骤引用超限方案，指出保存的阻断原因、数值与单位；讨论不改变约束或批准，也不冒充当前可执行方案。不要用自由reason覆盖程序可行性，亦不宣称理由里的全部数字已核验。
从本轮 question 的逐字原话提取 updates；未给出的量不能补。fixed 是已知，bounds 是待估范围；替换已有物理事实需用户明确更正和 correction=true。每项更新有唯一 id。研究目标 goal.target 为 width/separation/balanced/prediction/waist_radius/waist_position；design.points 是新增位置数，不是拟合次数。design.max_abs_x_mm 是最大绝对坐标；design.wavelengths_nm 是完整明确可用目录。
允许解释、澄清和多条合理路线。建议引用 evidence_catalog 的短 id，理由可使用历史证据，但不能把历史文本当本轮更新授权。fields 只用 action_fact_fields，proposal_id 只用已有方案 id；缺少计划时 null 并建议 compare_acquisition。depends_on 只引用本轮更新 id。explain 或 inspect_observation 是有价值的动作；用户要下一步时根据真实结果选择明确步骤。
preference.mode：基础优先 BASELINE_FIRST、明确允许条件探索 CONDITIONAL_EXPLORATION；preference.protected_parameter 指不愿牺牲的参数（默认限制预测尺度不增大，并非真实精度承诺）；preference.max_travel_mm 为明确最大行程。不得把偏好当独立噪声或物理事实。新目标会使旧计划失效，应先 compare_acquisition。
条件提取要严格区分：用户只说“先比较”并没有选择 BASELINE_FIRST，不能新增 preference.mode；沿用程序默认不需要 updates。最大移动行程/总行程只对应 preference.max_travel_mm，不能同时写成 design.max_abs_x_mm（后者必须是用户明确的最大绝对位置/正负范围）。只改本轮明确给出的值；历史已被拒绝的 updates 不能从 task_summary.original_request 或历史理由复制回来。
反过来也一样：只有最大绝对位置时只提取 design.max_abs_x_mm，不能推导任何 preference.max_travel_mm。没有已保存拟合结果时，先澄清缺失事实或 refit 并提醒核对采集条件；修改目标不代表可以跳过初始分析直接比较补采。
枚举值按程序合同填写：用户明确说理想透镜傅里叶焦平面时 fixed.measurement_plane="FOURIER_FOCAL_PLANE"；明确自由传播时 fixed.propagation="FREE_SPACE"。quote 保留用户中文原话，value 不用中文标签代替枚举；未声明这些条件时询问，不默认填写。
quote 使用能支持该字段的最短完整逐字片段。例如原句“我希望缝宽优先，不要牺牲缝距”分别用“缝宽优先”引用 goal.target=width、“不要牺牲缝距”引用 preference.protected_parameter=slit_separation_um；不能把包含相邻否定的整句作为物理/目标引用。每种 kind 最多一条；解释中的多个要点合并到一条 explain，不把同用途的多个波长拆成重复 propose_followup。
reason 只解释证据、取舍和待核对事项。不宣布确诊、真实精度或唯一性，不索取目录外波长，不假定独立校准已完成。所有动作只是建议，资料批准与计算批准由界面另行处理。'''
    payload={'question':text,'record':view(s),'decision_preferences':s.get('decision_preferences'),
             'allowed_fields':[f for f in actions.fact_fields(s) if not f.startswith('observation.')],
             'action_fact_fields':actions.fact_fields(s),'evidence_catalog':ctx['evidence_catalog'],**contract.public_contract()}
    # Hashes are host-owned; the model only needs short evidence/plan identifiers.
    payload['record'].pop('research_input_binding',None);payload['record'].pop('research_actions',None)
    # UI/export plots retain original samples; model receipts use the same headline,
    # changes and plan summary, without raw observation arrays or full fit inputs.
    payload['record']['task_summary'].pop('chart',None)
    write_once(store.folder(s['id'])/'ai-requests'/ctx['request_id']/'public-input.json',payload)
    try:answer=client.complete('research-advice-'+ctx['request_id'],json_payload(prompt,payload))
    except Exception as exc:
        store.event(s,'INVERSE_AI_TRANSPORT_FAILED',{'request_id':ctx['request_id'],'error_type':type(exc).__name__})
        raise
    return receive(store,s,text,answer,ctx)
