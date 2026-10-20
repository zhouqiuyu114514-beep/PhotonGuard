"""Adapt public recipes through the existing plan and physical validators."""
import copy,json,re,math
from ..core import digest
from .case_catalog import get_case,library_digest,public_cases,unsupported_request
from .candidate_recipes import candidates
from .contracts import ASSUMPTIONS,DEFAULT_BUDGET
from .planner import build_plan,unit_for,_ground_from_quotes

def normalize_request(request,parent=None):
    """Remove redundant representations only when equal to explicit authority."""
    r=copy.deepcopy(request);changes=[];case=get_case(r.get('case_id'));variable=case['recipe'].get('variable')
    bounds=r.get('bounds')
    if isinstance(bounds,dict) and set(bounds)=={variable} and isinstance(bounds[variable],dict) and set(bounds[variable])=={'min','max'}:
        r['bounds']=bounds[variable]
        changes.append({'field':'bounds','basis':'UNWRAP_EXPLICIT_RECIPE_VARIABLE','values_invented':False})
    values=r.get('values')
    if isinstance(values,dict) and set(values)=={variable} and isinstance(values[variable],list):
        r['values']=values[variable]
        changes.append({'field':'values','basis':'UNWRAP_EXPLICIT_RECIPE_VARIABLE','values_invented':False})
    p=r.get('parameters',{})
    if not isinstance(p,dict):raise ValueError('parameters必须是参数到数值的对象')
    value=p.get(variable)
    duplicate=(isinstance(value,dict) and value==r.get('bounds') and case['recipe']['method']=='fringe_target') or (isinstance(value,list) and value==r.get('values'))
    if duplicate:
        p.pop(variable);r.get('parameter_sources',{}).pop(variable,None)
        changes.append({'field':variable,'basis':'DUPLICATE_OF_EXPLICIT_RECIPE_RANGE_OR_CATALOG','values_invented':False})
    if parent:
        old,_=selected_parameters(parent)
        for key in list(p):
            if type(p[key]) in (int,float,str) and p[key]==old.get(key):
                p.pop(key);r.get('parameter_sources',{}).pop(key,None)
                changes.append({'field':key,'basis':'EXACT_SELECTED_PARENT_VALUE_REUSED','values_invented':False})
    return r,changes

def ground_goal_operator(goal,quote):
    patterns={'<=':r'不超过|不大于|不高于|至多|小于等于|≤|<=','>=':r'不少于|不小于|不低于|至少|大于等于|≥|>=','near':r'接近|靠近|约为','minimize':r'最小|尽量小|minimi[sz]e','maximize':r'最大|尽量大|maximi[sz]e'}
    found={op for op,pattern in patterns.items() if re.search(pattern,quote,re.I)}
    if found and found!={goal.get('operator')}:raise ValueError('目标比较方式与原文不一致，请核对上限、下限或优化要求；未执行计算')
    if goal.get('operator') in ('minimize','maximize') and ('target' in goal or 'tolerance' in goal):raise ValueError('仅优化目标不能混入达标阈值；请核对目标')

def selected_parameters(parent):
    if not parent or not parent.get('result') or parent['result']['plan_sha256']!=parent['plan']['sha256']:raise ValueError('请选择已完成且有匹配计算记录的来源版本')
    winner=next((c for c in parent['result']['candidates'] if c['id']==parent['result']['winner_id'] and c.get('all_checks_passed') is True),None)
    if winner is None:raise ValueError('来源版本没有通过数值检查的候选')
    return {**copy.deepcopy(parent['spec']['known_parameters']),**copy.deepcopy(winner['changes'])},winner

def adapt(request,*,mode='specified',parent=None,enforce_constraints=True):
    if not isinstance(request,dict) or set(request)-{'case_id','parameters','goal','values','bounds','parameter_sources','goal_quote','recipe_quote','fast_only'}:raise ValueError('案例请求字段无效')
    case=get_case(request.get('case_id'));domain=case['domain']
    if mode not in ('teaching','specified'):raise ValueError('请明确选择教学或我的资料')
    given=request.get('parameters',{})
    if not isinstance(given,dict):raise ValueError('参数必须为对象')
    from .fact_state import parameter_fields
    allowed=parameter_fields(case)
    if 'fast_only' in request and type(request['fast_only']) is not bool:raise ValueError('快速计算约束必须明确为是或否')
    if set(given)-allowed:raise ValueError('参数与所选案例不兼容：'+', '.join(sorted(set(given)-allowed)))
    p=copy.deepcopy(case['teaching']['parameters']) if mode=='teaching' and not parent else {}
    source_winner=None
    if parent:
        if parent['domain']!=domain:raise ValueError('新探索分支仍须保持物理场景')
        p,source_winner=selected_parameters(parent)
        if case['recipe']['method']=='thickness_catalog' and p.get('layers'):
            if len(p['layers'])!=1:raise ValueError('该案例只适用于单层膜')
            p['film_n']=p['layers'][0]['n'];p['thickness_um']=p['layers'][0]['thickness_um'];p.pop('layers')
        for key in list(p):
            if key not in allowed:p.pop(key)
        if enforce_constraints:
            for key,value in given.items():
                if key in p and value!=p[key]:raise ValueError('继续探索须保持已选物理条件；不能改动：'+key)
    p.update(copy.deepcopy(given))
    for key,value in case['fixed_parameters'].items():
        if key in p and p[key]!=value:raise ValueError('所选案例模型类型与资料不匹配：'+key)
        p[key]=value
    for key,value in case['numeric_defaults'].items():p.setdefault(key,value)
    missing=[k for k in case['required_parameters'] if k not in p or p[k] is None]
    if missing:raise ValueError('缺少实际参数（未套用教学值）：'+', '.join(missing))
    goal=copy.deepcopy(request.get('goal',case['teaching']['goal'] if mode=='teaching' else None))
    if not isinstance(goal,dict):raise ValueError('请明确目标指标与条件')
    if goal.get('metric') not in case['metrics']:raise ValueError('该目标与所选案例不兼容')
    values=request.get('values');bounds=request.get('bounds')
    if mode=='teaching' and not parent:
        if values is None:values=copy.deepcopy(case['teaching'].get('values'))
        if bounds is None:bounds=copy.deepcopy(case['teaching'].get('bounds'))
    if parent and values is None and case['recipe']['method'] not in ('fringe_target','phase','single'):
        variable=case['recipe'].get('variable')
        values=copy.deepcopy(parent['spec']['allowed_variables'].get(variable))
        if case['recipe']['method']=='thickness_catalog' and values:values=[v[0]['thickness_um'] for v in values]
    variables,proposal=candidates(case['recipe'],p,goal,values,bounds)
    for key,v in variables.items():
        if key not in p:p[key]=copy.deepcopy(v[0])
    if 'film_n' in p:
        p['layers']=[{'n':p.pop('film_n'),'thickness_um':p.pop('thickness_um',variables.get('layers',[[{'thickness_um':.1}]])[0][0]['thickness_um'])}]
    for key in ('layers',):
        if key in p:
            for unused in ('material_n_high','material_n_low','layer_count','design_wavelength_um'):p.pop(unused,None)
    if parent and enforce_constraints:
        # Explicitly allow only this recipe's new variable. All other selected values stay fixed.
        old,_=selected_parameters(parent)
        for key,value in old.items():
            if key in p and key not in variables and p[key]!=value:raise ValueError('案例切换改变了未授权物理条件：'+key)
    budget={**DEFAULT_BUDGET,'max_candidates':8,'max_fast_evaluations':24 if domain=='diffraction' else 16,'max_meep_validations':1 if case['id'] in ('F01','F02') else 0,'max_fdtd':8 if case['id'] in ('F01','F02') else 0}
    if parent:
        old_budget=parent['spec']['resource_budget']
        for key in budget:budget[key]=min(budget[key],old_budget[key])
    if request.get('fast_only'):
        budget.update(max_meep_validations=0,max_fdtd=0)
    if p.get('wavelengths_um'):
        for key in ('scan_min_um','scan_max_um','scan_points'):p.pop(key,None)
    context='来自用户明确选用的教学案例' if mode=='teaching' and not parent else '来自用户输入/已选实际计算记录；候选由公开配方生成'
    spec={'schema_version':1,'domain':domain,'context_kind':mode,'known_parameters':p,'parameter_sources':{k:{'quote':context+'：'+k+'='+json.dumps(v,ensure_ascii=False)+'；'+json.dumps(proposal,ensure_ascii=False),'unit':unit_for(k)} for k,v in p.items()},'assumptions':ASSUMPTIONS[domain],'locked_parameters':sorted(set(p)-set(variables)),'allowed_variables':variables,'goal':goal,'resource_budget':budget,'parent_task_id':parent['id'] if parent else None}
    plan=build_plan(spec)
    provenance={'case_id':case['id'],'case_version':case['version'],'case_sha256':digest(case),'library_sha256':library_digest(),'mode':mode,'request':copy.deepcopy(request),'proposal':proposal,'selected_parent_id':parent['id'] if parent else None,'selected_candidate_id':source_winner['id'] if source_winner else None,'selected_result_sha256':digest(parent['result']) if parent else None,'new_exploration_branch':bool(parent),'preview_status':'NOT_COMPUTED','numerical_defaults':case['numeric_defaults']}
    return {'spec':plan['spec'],'plan':plan,'provenance':provenance,'questions':[]}

def from_text(text,client,ident,*,mode='specified',parent=None,case_id=None):
    error=unsupported_request(text)
    if error:return {'spec':None,'plan':None,'questions':[error],'actual_model_calls':0}
    from ..product_phase import json_payload
    prompt='''你是光学案例适配助手。两种资料不能混淆：specified缺参数必须追问，teaching只有用户明确选用示例才可沿用其值。输出JSON {request:{case_id,parameters,goal,values可选,bounds可选,parameter_sources,goal_quote,recipe_quote},questions:[]} 或 {request:null,questions:[明确缺失字段]}。parameters只写本轮原文实际给出的值，沿用父版本的值可以省略。每个参数的parameter_sources是{quote:逐字原文,unit:单位}；数组候选也要有recipe_quote逐字原文；goal_quote逐字引用目标。所有长度转换到字段名的单位。不能把教学示例的参数作为指定资料；案例固定模型类型与公开数值网格由程序提供。fringe_target只需波长、焦距、缝宽/缝高、相对相位、目标周期与允许缝距bounds(min/max μm)，不要自己算候选。其他目录型recipe用values给用户明确目录。phase公开配方提供0,pi/2,pi，single无需目录。高斯未知束腰位置不得假设为0。后续探索保留已选物理参数，只通过目标、配方和明确范围生成候选。不要生成内部spec或Python。'''
    payload={'facts':text,'mode':mode,'case_id_constraint':case_id,'cases':[r for r in public_cases(text) if not case_id or r['id']==case_id],'parent':{'id':parent['id'],'domain':parent['domain'],'selected_parameters':selected_parameters(parent)[0],'goal':parent['spec']['goal']} if parent else None}
    segments=text.split('\n\n补充资料：\n')
    if len(segments)>1:
        payload['facts']=segments[0]
        payload['supplements_in_time_order']=segments[1:]
        payload['current_user_update']=segments[-1]
    prompt+='parameters的值必须是JSON数值（例如"wavelength_nm":532），绝不能放{quote,unit}或{value,unit}对象；出处只放在独立parameter_sources中。比如原文明确写波长532 nm，则parameters={"wavelength_nm":532}，parameter_sources={"wavelength_nm":{"quote":"波长532 nm","unit":"nm"}}。例子不是当前任务事实，禁止照抄数字。缺失参数返回questions。'
    prompt+='改目标时parameters通常为空对象，程序自动沿用父版本已选候选。允许缝距范围只能放bounds，格式严格为{"min":数值,"max":数值}，不再套参数名；焦距/厚度等目录只能放values，绝不能把范围对象或目录数组放在parameters中的某个标量参数下。'
    prompt+='资料中的“补充资料”按时间追加：后续明确数值可以补齐原先未知的同一字段，这不是数值冲突；无需反复确认已有明确的候选目录或目标。原资料要求先追问，是针对当时缺项，补齐后应继续规划。只有真正缺项或互相矛盾的已知数值才追问；补充不能覆盖来源版本锁定的物理参数。引用可分别来自原资料与补充资料。'
    prompt+='current_user_update是当前最新补充；supplements_in_time_order是从旧到新的补充列表。先检查最新补充已解决哪些缺项，再决定是否追问，不忽略它们而只读取facts中的旧状态。'
    prompt+='values必须直接为数值数组，如[100,120,160]，不能再套变量名。目标关系严格对应原文：不超过/至多=<=；至少/不小于=>=；接近=near；尽量小/最小化=minimize；尽量大/最大化=maximize。minimize/maximize省略target与tolerance，不把阈值任务改成优化任务。'
    try:response=client.complete(ident,json_payload(prompt,payload))
    except Exception as exc:return {'spec':None,'plan':None,'questions':['AI请求未完成，资料已保留；没有自动重试。'],'error_type':type(exc).__name__}
    result={'actual_model_calls':int(response['audit'].get('live_dispatch',False)),'response':response}
    try:
        if response['audit']['status']!='ASSISTANT_RETURNED':raise ValueError('AI未返回；未自动重试')
        obj=json.loads(response['assistant']['content'])
        if not isinstance(obj,dict) or not isinstance(obj.get('questions',[]),list) or any(not isinstance(q,str) for q in obj.get('questions',[])):raise ValueError('AI返回的追问格式无效')
        if obj.get('questions'):return {**result,'spec':None,'plan':None,'questions':obj['questions']}
        req,normalizations=normalize_request(obj['request'],parent)
        if case_id and req['case_id']!=case_id:raise ValueError('AI选择了用户指定案例以外的案例')
        for key,value in req.get('parameters',{}).items():
            if isinstance(value,dict):raise ValueError('参数'+key+'应为数值，引用应单独放在parameter_sources；未执行计算')
            source=req.get('parameter_sources',{}).get(key,{})
            quote=source.get('quote','')
            if not quote or quote not in text:raise ValueError('参数缺少本轮逐字出处：'+key)
            _ground_from_quotes('n' if key=='film_n' else key,value,[quote])
        for field in ('goal_quote',):
            if not req.get(field) or req[field] not in text:raise ValueError('目标缺少逐字出处')
        goal=req.get('goal',{});quote=req['goal_quote']
        ground_goal_operator(goal,quote)
        for key in ('target','tolerance','wavelength_um'):
            if key not in goal:continue
            metric=goal.get('metric','')
            unit_key='wavelength_um' if key=='wavelength_um' else metric
            percentages=[float(x)/100 for x in re.findall(r'(\d+(?:\.\d+)?)\s*[%％]',quote)]
            if key!='wavelength_um' and not metric.endswith(('_mm','_um')) and any(math.isclose(goal[key],x,rel_tol=1e-9) for x in percentages):continue
            _ground_from_quotes(unit_key,goal[key],[quote])
        if req.get('values') is not None or req.get('bounds') is not None:
            key=get_case(req['case_id'])['recipe'].get('variable','')
            if key=='layers':key='thickness_um'
            quotes=[req.get('recipe_quote','')]
            sources=req.get('parameter_sources',{})
            field='values' if req.get('values') is not None else 'bounds'
            quotes += [sources.get(k,{}).get('quote','') for k in (field,key) if isinstance(sources.get(k,{}),dict)]
            grounded=None
            for quote in quotes:
                if not quote or quote not in text:continue
                try:
                    for value in (req.get('values') or list((req.get('bounds') or {}).values())):_ground_from_quotes(key,value,[quote])
                except (ValueError,TypeError):continue
                grounded=quote;break
            if grounded is None:raise ValueError('候选范围缺少可核对全部数值及单位的逐字出处；未执行计算')
            if grounded!=req.get('recipe_quote'):
                req['recipe_quote']=grounded;normalizations.append({'field':'recipe_quote','basis':'EXPLICIT_RECIPE_SOURCE_WITH_ALL_VALUES_GROUNDED','values_invented':False})
        return {**result,**adapt(req,mode=mode,parent=parent),'normalizations':normalizations}
    except (ValueError,TypeError,KeyError) as exc:return {**result,'spec':None,'plan':None,'questions':[str(exc)]}
