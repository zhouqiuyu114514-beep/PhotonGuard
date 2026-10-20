"""v2 application-owned facts; the model can propose, never author authority."""
import copy,json,uuid
from ..core import digest
from ..workflow import WorkflowError
from . import fact_state as fs
from .fact_binding import parse,parse_update
from .case_catalog import get_case,public_cases,unsupported_request
from .case_adaptation import adapt
from .action_protocol import decode,canonical_field

PROMPT='''解释用户本轮光学资料更新。只输出一个JSON对象：{case_id:"兼容案例ID",patches:[{field:"字段路径",value:数值或数组或字符串,quote:"本轮逐字片段"}],questions:[]}。已有facts引用用fact_ids数组，无需复述父参数。路径为parameters.参数名、goal.metric/operator/target/tolerance/wavelength_um、recipe.min/max/values、execution.fast_only（布尔值）。薄膜支持 material_n_high、material_n_low、design_wavelength_um、layer_count、wavelengths_um；nH/nL为折射率，总层数目录映射recipe.values，初始层数映射parameters.layer_count；明确列出的计算波长转成微米数组，不能换成默认网格。只做快速计算或不做Meep/FDTD时execution.fast_only=true；勿借此改动设计波长。单点目标的波长和设计波长分别提取。已有薄膜实验中“光源换成/目标波长改为”仅更新goal.wavelength_um；没有明确改变计算/采样波长目录时，勿将parameters.wavelengths_um缩成单点，勿重新设计膜厚。高斯TEM00、M²=1和1/e²强度半径是固定模型声明，不是缺失参数，不生成额外字段。达标后指出光斑最小候选是结果展示要求，不把已有不超过阈值改为minimize。高斯位置以透镜为零点：透镜前25 mm应写waist_z_mm=-25，透镜后取正；显式符号与方位矛盾时询问，不擅自覆盖符号。明确同字段来源才能提议；不得借用别的字段的数值。未知不假设；父结果物理条件不能覆盖；案例教学值未选择时不是用户事实。资料齐全时questions为空。只选择公开案例和字段，不生成spec或工具代码。'''

PROMPT+='goal.target出现时必须同时输出goal.metric及goal.operator。goal.wavelength_um仅适用于薄膜场景，高斯和双缝的光源波长一律为parameters.wavelength_nm；即使原文单位为微米也要换算成纳米。字段名和单位严格遵守allowed_fields，不按原文单位自造字段，cm必须转换为mm。可额外返回assumptions:[{field:mode|beam_quality|radius_definition|medium|lens_count,value:TEM00|1|1/e2_intensity_radius|air|1,quote:逐字固定模型声明}]，只提取用户明确的高斯模型约定，数值1使用JSON数字；这不会改变物理参数。'

def form_operations(request):
    ops=[]
    for group in ('parameters','goal'):
        for k,v in request.get(group,{}).items():
            if group=='goal' and k=='unit':continue
            ops.append({'field':group+'.'+k,'value':v,'correction':True})
    for k,v in request.get('bounds',{}).items():ops.append({'field':'recipe.'+k,'value':v,'correction':True})
    if 'fast_only' in request:ops.append({'field':'execution.fast_only','value':request['fast_only'],'correction':True})
    if 'values' in request:ops.append({'field':'recipe.values','value':request['values'],'correction':True})
    return ops

def compile_case_plan(state,parent=None):
    state=fs.refresh(state)
    if state['questions']:return {'spec':None,'plan':None,'questions':[q['text'] for q in state['questions']]}
    response=adapt(fs.request(state),mode=state['mode'],parent=parent)
    response['provenance']['fact_state_sha256']=digest(state)
    response['provenance']['fact_refs']={p:f['fact_id'] for p,f in state['facts'].items() if f['status']=='resolved'}
    return response

def compile_goal_plan(state,parent):
    """Rescore the same physical candidates; a target is not a new recipe."""
    response=compile_case_plan(state)
    if response.get('plan'):
        from .planner import build_plan
        spec=copy.deepcopy(parent['spec']);spec['goal']=copy.deepcopy(fs.request(state)['goal'])
        plan=build_plan(spec);response.update(spec=plan['spec'],plan=plan)
        response['provenance']['goal_only_source_result_sha256']=digest(parent['result'])
    return response


def update(state,text,event_id,*,request=None,model_obj=None,evidence_review=None):
    """Pure interpreter/reducer. Complete deterministic facts outrank stale questions."""
    mid=event_id;interpretation=parse_update(text,state,mid) if request is None else None
    ops=form_operations(request) if request is not None else interpretation['confirmed_operations']
    issues=[];notes=[]
    if evidence_review is not None and interpretation is not None and model_obj is not None:
        from .evidence_review import checked
        extra,coverage,review_notes=checked(state,text,mid,model_obj,evidence_review)
        for op in extra:
            existing=[o for o in ops if o['field']==op['field']]
            if not existing:ops.append(op)
        # Only clauses actually supported by checked evidence or nonphysical
        # presentation intent can lose their unresolved marker.
        def covered(a):
            lo,hi=a.get('start'),a.get('end')
            if lo is None or a['kind'] not in ('UNRESOLVED_CLAUSE','CONDITIONAL_PROPOSAL'):return False
            if a['kind']=='CONDITIONAL_PROPOSAL' and a['fields']:return False
            fragment=text[lo:hi]
            numeric=list(__import__('re').finditer(r'[-+]?\d+(?:\.\d+)?',fragment))
            if numeric:return all(any(x<=lo+m.start() and y>=lo+m.end() for x,y in coverage) for m in numeric)
            return any(x<=lo and y>=hi for x,y in coverage)
        interpretation['ambiguities']=[a for a in interpretation['ambiguities'] if not covered(a)]
        interpretation['consumed_spans']+=list(coverage)
        notes+=review_notes
    if model_obj is not None:
        if not isinstance(model_obj.get('patches',[]),list) or not isinstance(model_obj.get('questions',[]),list):raise ValueError('模型字段补丁格式无效')
        for patch in model_obj.get('patches',[]):
            if not isinstance(patch,dict):raise ValueError('模型字段补丁必须为对象')
            original_field=patch.get('field');patch=copy.deepcopy(patch);patch['field']=canonical_field(original_field,get_case(state['case_id']))
            if isinstance(patch['field'],str) and patch['field'] not in fs.allowed(get_case(state['case_id'])):
                suffix=patch['field'].rsplit('.',1)[-1]
                targets=[p for p in fs.allowed(get_case(state['case_id'])) if p.rsplit('.',1)[-1]==suffix]
                if len(targets)==1 and any(o['field']==targets[0] and fs.equal(o['value'],patch.get('value')) for o in ops):
                    notes.append({'kind':'SOURCE_BOUND_NAMESPACE_REPAIRED','from':patch['field'],'to':targets[0]});patch['field']=targets[0]
            if patch['field']!=original_field:notes.append({'kind':'PUBLIC_PARAMETER_NAMESPACE_COMPLETED','from':original_field,'to':patch['field']})
            variable=get_case(state['case_id'])['recipe']['variable']
            if patch['field']=='parameters.'+str(variable) and isinstance(patch.get('value'),list) and any(o['field']=='recipe.values' and fs.equal(o['value'],patch['value']) for o in ops):
                notes.append({'kind':'CATALOG_PATH_NORMALIZED','from':patch['field'],'to':'recipe.values','values_invented':False});patch['field']='recipe.values'
            matches=[o for o in ops if o['field']==patch.get('field') and fs.equal(o['value'],patch.get('value'))]
            # Linking is permitted only to an independently parsed same-field fact.
            previous=fs.effective_facts(state).get(patch['field'],{})
            if not matches and previous.get('status')=='resolved' and fs.equal(previous.get('value'),patch.get('value')) and not any(o['field']==patch['field'] for o in ops):
                notes.append({'kind':'EXISTING_FACT_RESTATED_NO_CHANGE','field':patch['field']});continue
            # A target-only edit cannot authorize shrinking the saved sampling grid.
            # Reject this redundant model patch, but keep the independently bound goal.
            target=next((o for o in ops if o['field']=='goal.wavelength_um'),None)
            old_grid=state['facts'].get('parameters.wavelengths_um',{})
            if (not matches and patch['field']=='parameters.wavelengths_um'
                    and target and old_grid.get('status')=='resolved'
                    and not any(o['field']=='parameters.wavelengths_um' for o in ops)
                    and fs.equal(patch.get('value'),[target['value']])
                    and any(fs.equal(v,target['value']) for v in old_grid.get('value',[]))
                    and patch.get('quote') and any(text[e['start']:e['end']] in patch['quote'] or patch['quote'] in text[e['start']:e['end']] for e in target['evidence'])):
                notes.append({'kind':'MODEL_SAMPLING_CHANGE_REJECTED_GOAL_ONLY','field':patch['field'],'activated':False,'rejected_patch':copy.deepcopy(patch),'preserved_value':copy.deepcopy(old_grid['value'])});continue
            directory=next((o for o in ops if o['field']=='recipe.values'),None)
            variable=get_case(state['case_id'])['recipe']['variable']
            if not matches and directory and patch['field'] in ('recipe.min','recipe.max') and get_case(state['case_id'])['recipe']['method']!='fringe_target' and fs.equal(patch.get('value'),(min if patch['field']=='recipe.min' else max)(directory['value'])):
                notes.append({'kind':'CATALOG_ENDPOINT_IS_NOT_A_CONTINUOUS_RANGE','field':patch['field'],'activated':False});continue
            if not matches and directory and patch['field']=='parameters.'+str(variable) and directory['value'] and fs.equal(patch.get('value'),directory['value'][0]) and not any(o['field']==patch['field'] for o in ops):
                notes.append({'kind':'CATALOG_BASELINE_ALREADY_DERIVED','field':patch['field'],'values_invented':False});continue
            # The source reader may already have converted explicit units while
            # the model echoes the original numbers. Keep that authoritative
            # same-field conversion; never infer a scale from the proposed value.
            if not matches and isinstance(patch.get('quote'),str) and patch['quote'] in text:
                import re
                from .fact_binding import numbers, NUMBER
                quote=patch['quote'];raw=[float(x) for x in re.findall(NUMBER,quote)]
                proposed=patch.get('value');raw_value=raw if isinstance(proposed,list) else raw[0] if len(raw)==1 else None
                converted=numbers(quote,fs.unit(patch['field'],get_case(state['case_id'])))
                converted_value=converted if isinstance(proposed,list) else converted[0] if len(converted)==1 else None
                source=next((o for o in ops if o['field']==patch['field'] and fs.equal(o['value'],converted_value) and any(text[e['start']:e['end']] in quote or quote in text[e['start']:e['end']] for e in o['evidence'])),None)
                if source and raw_value is not None and fs.equal(raw_value,proposed):
                    notes.append({'kind':'MODEL_UNCONVERTED_VALUE_REJECTED','field':patch['field'],'preserved_source_value':source['value'],'raw_model_value':proposed});continue
            if not matches:issues.append({'kind':'SOURCE_UNRESOLVED','field':patch.get('field'),'text':'AI提议不能绑定到同字段资料，未采纳。'})
            elif patch.get('quote') and not any(text[e['start']:e['end']] in patch['quote'] or patch['quote'] in text[e['start']:e['end']] for o in matches for e in o['evidence']):
                notes.append({'kind':'SOURCE_LINK_REBUILT','field':patch['field'],'basis':'unique_program_bound_fact','raw_model_preserved':True})
        known_ids={f['fact_id'] for f in state['facts'].values() if f['status']=='resolved'}
        if any(i not in known_ids for i in model_obj.get('fact_ids',[])):issues.append({'kind':'SOURCE_UNRESOLVED','text':'AI引用了不存在或未确认的事实编号，未采纳。'})
    out=fs.apply(state,event_id,text,ops,base_revision=state['revision'],actor='user_form' if request is not None else 'user_text')
    resolved={o['field'] for o in ops if o.get('correction')}
    previous=state.get('ambiguities',[])
    out['events'][-1]['ambiguities_before']=copy.deepcopy(previous)
    out['ambiguities']=[a for a in previous if not a['fields'] or not set(a['fields'])<=resolved]
    if interpretation:out['ambiguities']+=interpretation['ambiguities']
    out=fs.refresh(out)
    if model_obj and model_obj.get('questions'):
        notes.append({'kind':'STALE_QUESTION' if not out['questions'] else 'MODEL_QUESTIONS_ADVISORY','questions':model_obj['questions']})
    out['issues']=issues;out['events'][-1]['interpretation_notes']=notes
    out['proposals']=[{'status':'proposed','proposal':copy.deepcopy(p),'source_kind':'model_proposal','activated':False} for p in (model_obj or {}).get('patches',[]) if any(i.get('field')==p.get('field') for i in issues)]
    if interpretation:
        out['proposals']+=interpretation['proposed_operations']
        out['events'][-1]['interpretation']=interpretation
        out['events'][-1]['ambiguities_before']=copy.deepcopy(previous)
        out['notice']='未修改：已保留原条件。' if interpretation['retained_fields'] and not ops and not out['ambiguities'] else None
    from .evidence_review import fit_numerical_defaults
    return fit_numerical_defaults(out)

def action(store,s,data):
    from . import case_workflow as flow
    kind=data['type'];parent=None
    if kind not in ('plan','library_plan','supplement','save','explore_case','fact_update','undo_fact'):return None
    if s.get('result') or s.get('approved_plan_sha256'):
        if kind!='explore_case':raise WorkflowError('已批准执行的版本保持不变，请另建修订',409)
    event_id=data.get('event_id') or uuid.uuid4().hex
    if not isinstance(event_id,str) or not 1<=len(event_id)<=128:raise WorkflowError('事件编号无效')
    if any(e['event_id']==event_id for e in s.get('fact_state',{}).get('events',[])):
        old=next(e for e in s['fact_state']['events'] if e['event_id']==event_id)
        if old.get('submission_sha256')!=digest({k:v for k,v in data.items() if k!='expected_revision'}):raise WorkflowError('重复事件内容不一致',409)
        return s
    if kind=='explore_case':
        if data.get('new_exploration') is not True:raise WorkflowError('请明确建立新探索分支')
        parent=store.verified_case(s['id'])
    elif s.get('parent_id'):
        context=s.get('library_context',{});parent=store.verified_case(s['parent_id'])
        if context.get('parent_result_sha256')!=digest(parent.get('result')):raise WorkflowError('来源结果校验不一致',409)
    request=data.get('request');case_id=data.get('case_id') or (request or {}).get('case_id') or s.get('fact_state',{}).get('case_id') or s.get('library_context',{}).get('case_id') or s.get('library_origin',{}).get('case_id')
    text=data.get('text',s['text'] if kind in ('plan','library_plan') else '')
    if not isinstance(text,str) or len(text)>24000:raise WorkflowError('本轮资料过长或无效')
    from ..workflow_model import wire
    if wire.credential_risk(text):raise WorkflowError('请移除API密钥')
    error=unsupported_request(text)
    if error:
        if kind=='explore_case':
            s=store.create({'kind':'specified','text':text})
            s.update(parent_id=parent['id'],family_id=parent['family_id'],library_context={'mode':'specified','case_id':case_id,'parent_id':parent['id'],'parent_result_sha256':digest(parent['result'])})
        s.update(session_version=2,status='NEEDS_REVIEW',plan=None,spec=None,questions=[])
        s['session_issue']={'kind':'UNSUPPORTED_SCOPE','text':error}
        store.event(s,'SESSION_SCOPE_REJECTED',{'input_text':text,'new_computation':False});store.save(s);return s
    state=None if kind=='explore_case' else copy.deepcopy(s.get('fact_state'))
    mode='specified' if parent else s['kind'];model_obj=None;model_response=None;normalizations=[];model_error=None;evidence_review=None
    if case_id and state is None:
        state=fs.seed(case_id,mode,parent)
        # Old pending records migrate only independently bound raw facts, never
        # model-written specs. Completed records remain untouched.
        if kind!='explore_case' and s.get('library_context') and s.get('text'):
            for index,part in enumerate(s['text'].split('\n\n补充资料：\n')):
                state=update(state,part,'migration-'+str(index))
            store.event(s,'PENDING_FACTS_MIGRATED',{'source_text_sha256':digest(s['text']),'verified_fact_ids':[f['fact_id'] for f in state['facts'].values() if f['status']=='resolved'],'old_record_id_preserved':True})
    if state and case_id!=state['case_id']:raise WorkflowError('当前会话不能静默切换案例')
    # A model is optional: common anchored facts and a unique question need no call.
    understood=parse_update(text,state,event_id) if state and request is None else None
    need_model=not case_id or (understood is not None and not understood['consumed_spans'] and bool(text.strip()))
    if data.get('mode')=='live' and (need_model or data.get('force_model') is True) and kind!='undo_fact':
        from ..product_phase import json_payload
        client=store._model(s,data)
        snapshot=copy.deepcopy(state)
        if snapshot:snapshot['facts']=fs.effective_facts(snapshot)
        try:
            model_response=client.complete('session-v2-'+s['id']+'-'+str(s['model_calls']),json_payload(PROMPT,{'current_update':text,'cases':[c for c in public_cases(text) if not case_id or c['id']==case_id],'facts':snapshot,'allowed_fields':{p:fs.unit(p,get_case(case_id)) for p in fs.allowed(get_case(case_id))} if case_id else {c['id']:{p:fs.unit(p,c) for p in fs.allowed(c)} for c in public_cases(text)}}))
            model_obj,normalizations=decode(model_response['assistant']['content'],{'case_id'})
            if case_id and model_obj['case_id']!=case_id:raise ValueError('模型建议切换了当前案例')
            get_case(model_obj['case_id']);case_id=model_obj['case_id']
            if state is None:state=fs.seed(case_id,mode,parent)
            from .evidence_review import needs_review, PROMPT as REVIEW_PROMPT
            if needs_review(state,text,model_obj):
                client=store._model(s,data)
                review_response=client.complete('session-evidence-'+s['id']+'-'+str(s['model_calls']),json_payload(REVIEW_PROMPT,{'current_update':text,'case':get_case(case_id),'facts':fs.effective_facts(state),'allowed_fields':{p:fs.unit(p,get_case(case_id)) for p in fs.allowed(get_case(case_id))},'unresolved_clauses':[text[a['start']:a['end']] for a in parse_update(text,state,event_id)['ambiguities']]}))
                store.event(s,'SESSION_EVIDENCE_REPLY',{'response':review_response,'purpose':'independent_source_reading'})
                evidence_review,_=decode(review_response['assistant']['content'],{'bindings','nonfacts'})
                probe=update(state,text,event_id,model_obj=model_obj,evidence_review=evidence_review)
                missing={i['field'] for i in probe['issues'] if i.get('field')}|{p for q in probe['questions'] for p in q.get('fields',[])}
                primary={canonical_field(p.get('field'),get_case(case_id)):p for p in model_obj.get('patches',[]) if isinstance(p,dict)}
                secondary={canonical_field(p.get('field'),get_case(case_id)):p for p in evidence_review.get('bindings',[]) if isinstance(p,dict)}
                missing=missing & fs.allowed(get_case(case_id)) & (set(primary)|set(secondary))
                first_assumptions={a.get('field'):a for a in model_obj.get('assumptions',[]) if isinstance(a,dict)}
                second_assumptions={a.get('field'):a for a in evidence_review.get('assumptions',[]) if isinstance(a,dict)}
                missing_assumptions=(set(first_assumptions)^set(second_assumptions)) if probe['questions'] else set()
                if missing or missing_assumptions:
                    # One bounded completeness repair. Only field names are sent,
                    # never the other reader's proposed values or citations.
                    client=store._model(s,data)
                    recovery_response=client.complete('session-evidence-completeness-'+s['id']+'-'+str(s['model_calls']),json_payload(REVIEW_PROMPT,{'current_update':text,'case':get_case(case_id),'facts':fs.effective_facts(state),'allowed_fields':{p:fs.unit(p,get_case(case_id)) for p in fs.allowed(get_case(case_id))},'required_fields':sorted(missing),'required_assumptions':sorted(missing_assumptions)}))
                    store.event(s,'SESSION_EVIDENCE_COMPLETENESS_REPLY',{'response':recovery_response,'requested_fields':sorted(missing),'maximum_recovery_reads':1})
                    recovery,_=decode(recovery_response['assistant']['content'],{'bindings','nonfacts'})
                    fresh={canonical_field(p.get('field'),get_case(case_id)):p for p in recovery.get('bindings',[]) if isinstance(p,dict)}
                    for field in missing:
                        if field not in primary and field in secondary and field in fresh and fs.equal(secondary[field].get('value'),fresh[field].get('value')):
                            model_obj=copy.deepcopy(model_obj)
                            model_obj.setdefault('patches',[]).append({'field':field,'value':secondary[field]['value'],'quote':secondary[field].get('quote')})
                            normalizations.append({'kind':'TWO_INDEPENDENT_READERS_FILLED_OMITTED_FIELD','field':field})
                    evidence_review['bindings']=[b for b in evidence_review.get('bindings',[]) if canonical_field(b.get('field'),get_case(case_id)) not in missing]+[b for f,b in fresh.items() if f in missing]
                    recovered_assumptions={a.get('field'):a for a in recovery.get('assumptions',[]) if isinstance(a,dict)}
                    for field in missing_assumptions:
                        if field not in first_assumptions and field in second_assumptions and field in recovered_assumptions and fs.equal(second_assumptions[field].get('value'),recovered_assumptions[field].get('value')):
                            model_obj=copy.deepcopy(model_obj);model_obj.setdefault('assumptions',[]).append(second_assumptions[field])
                    evidence_review['assumptions']=[a for a in evidence_review.get('assumptions',[]) if a.get('field') not in missing_assumptions]+[a for f,a in recovered_assumptions.items() if f in missing_assumptions]



        except Exception as exc:model_error={'kind':'MODEL_OUTPUT_INVALID' if model_response else 'SERVICE_UNAVAILABLE','text':'AI本轮未给出可核对的字段更新；原资料仍保留。','error_type':type(exc).__name__}
        store.event(s,'SESSION_MODEL_REPLY',{'response':model_response,'normalizations':normalizations,'error':model_error,'read_fact_revision':snapshot['revision'] if snapshot else None})
    if state is None:
        s['session_issue']=model_error or {'kind':'MISSING_CASE','text':'请从案例库选择本次实验类型。'};store.save(s);return s
    if kind=='explore_case':s=store.create({'kind':'specified','text':text or json.dumps(request,ensure_ascii=False)})
    if kind=='undo_fact':state=fs.undo(state,event_id)
    else:
        try:state=update(state,text,event_id,request=request,model_obj=model_obj,evidence_review=evidence_review)
        except (ValueError,TypeError,KeyError) as exc:
            model_error={'kind':'MODEL_OUTPUT_INVALID','text':str(exc)}
            state=update(state,text,event_id,request=request)
    state['events'][-1]['submission_sha256']=digest({k:v for k,v in data.items() if k!='expected_revision'})
    s['fact_state']=state;s['session_version']=2
    if kind not in ('plan','library_plan','undo_fact') and text and text!=s['text']:s['text']+='\n\n补充资料：\n'+text
    context={'mode':mode,'case_id':case_id,'parent_id':parent['id'] if parent else None,'parent_result_sha256':digest(parent['result']) if parent else None}
    changes=state['events'][-1].get('changes',[])
    effective=[c for c in changes if c['before'] is None or c['before'].get('status')!=c['after'].get('status') or not fs.equal(c['before'].get('value'),c['after'].get('value'))]
    goal_only=bool(parent and effective and all(c['field'].startswith('goal.') for c in effective) and not state['questions'])
    # Same goal-only draft semantics as session_commands.ingest: do not replace
    # the parent's base physical parameters with its selected winner.
    try:response=compile_goal_plan(state,parent) if goal_only else compile_case_plan(state,parent)
    except ValueError as exc:
        response={'plan':None,'spec':None,'questions':[]};model_error={'kind':'UNSUPPORTED_SCOPE','text':str(exc)}
    if kind in ('fact_update','supplement','save') and text.strip() and request is None and not state['events'][-1].get('changes') and not state['events'][-1].get('interpretation',{}).get('consumed_spans'):
        response={'plan':None,'spec':None,'questions':[q['text'] for q in state['questions']]}
        model_error=model_error or {'kind':'SOURCE_UNRESOLVED','text':'这句话尚不能确定改变哪个条件；已知资料已保留。请只写明要改变的字段、数值与单位，或撤销这次输入。'}
    s.pop('session_issue',None)
    if model_error:s['session_issue']=model_error
    elif state['issues']:s['session_issue']=state['issues'][0]
    s=flow.apply_plan(store,s,response,parent,context)
    if not response.get('plan') and not state['questions']:
        s.update(status='NEEDS_REVIEW',questions=[]);store.save(s)
    return s
