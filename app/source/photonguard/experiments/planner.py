"""Explicit teaching inputs, grounded AI drafts, and a fixed candidate graph."""
from __future__ import annotations
import copy
import itertools
import json
import math
import re
from ..core import digest, finite
from .contracts import validate_spec, DEFAULT_BUDGET, ASSUMPTIONS, PARAMETERS, METRICS

def parameters_for(domain,params,goal):
    p=copy.deepcopy(params)
    if domain=='film':
        if 'layers' not in p:
            n=p['layer_count']
            if type(n) is not int or not 1<=n<=8:raise ValueError('膜层数必须为1–8的整数')
            hi,lo=p['material_n_high'],p['material_n_low'];w=p['design_wavelength_um']
            if not all(finite(x) and 1<=x<=5 for x in (hi,lo)) or not finite(w) or not .5<=w<=5:raise ValueError('四分之一波长膜层的材料或中心波长超出范围')
            p['layers']=[{'n':hi if i%2==0 else lo,'thickness_um':w/(4*(hi if i%2==0 else lo))} for i in range(n)]
        if 'wavelengths_um' not in p:
            a,b,n=p['scan_min_um'],p['scan_max_um'],p['scan_points']
            if not finite(a) or not finite(b) or not .5<=a<b<=5 or type(n) is not int or not 3<=n<=201:raise ValueError('薄膜扫描需要0.5–5微米内的区间和3–201个点')
            p['wavelengths_um']=[a+(b-a)*i/(n-1) for i in range(n)]
        if goal.get('wavelength_um') is not None:
            w=goal['wavelength_um'];axis=p['wavelengths_um']
            if not min(axis)<=w<=max(axis):raise ValueError('目标波长不在已给定扫描范围内')
            axis=[x for x in axis if abs(x-w)>1e-12]
            if len(axis)>=201:raise ValueError('需要实际加入目标波长，但201点上限已满')
            p['wavelengths_um']=sorted(axis+[w])
        p={k:p[k] for k in ('layers','wavelengths_um')}
    elif domain=='diffraction':
        # These are numerical aperture-window choices, explicitly shown in the plan.
        p.setdefault('grid_size',512);p.setdefault('window_mm',.5)
    elif domain=='gaussian':p.setdefault('z_max_mm',max(1,p['screen_distance_mm']*2))
    return p

def build_plan(spec,parent=None):
    s=validate_spec(spec,parent);d=s['domain'];variables=s['allowed_variables'];names=sorted(variables)
    from .optics import validate_parameters
    candidates=[]
    for idx,values in enumerate(itertools.product(*(variables[k] for k in names))):
        changes=dict(zip(names,values));p={**s['known_parameters'],**changes}
        parameters=parameters_for(d,p,s['goal'])
        try:validate_parameters(d,parameters)
        except ValueError as exc:raise ValueError(f'候选{idx+1}超出当前模型支持范围：{exc}') from None
        candidates.append({'id':f'candidate-{idx+1:02d}','changes':changes,'parameters':parameters})
    n=len(candidates);budget=s['resource_budget']
    plan={'schema_version':1,'domain':d,'adapter':{'film':'tmm-meep-film1d-v1','diffraction':'scalar-lens-fourier-v1','gaussian':'gaussian-abcd-v1'}[d],
          'spec':s,'spec_sha256':digest(s),'goal':s['goal'],'locked_parameters':{k:s['known_parameters'][k] for k in s['locked_parameters']},
          'allowed_variables':variables,'assumptions':ASSUMPTIONS[d],'resource_budget':budget,'candidates':candidates,
          'tool_graph':[{'id':'fast','tool':d,'depends_on':[]},{'id':'goals','tool':'deterministic-goal-comparison','depends_on':['fast']}]+([{'id':'meep','tool':'film1d-full-verification','depends_on':['goals']}] if d=='film' and budget['max_meep_validations'] else []),
          'goal_sampling_points':[s['goal']['wavelength_um']] if 'wavelength_um' in s['goal'] else [],
          'stop_conditions':['missing-input','locked-parameter-change','candidate-bound','worker-resource-limit','numerical-check-failure'],
          'summary':f'在明确假设下比较 {n} 个候选；优化仅在该候选集合内有效。'}
    plan['sha256']=digest(plan)
    return plan

def _spec(domain,params,variables,goal,text):
    return {'schema_version':1,'domain':domain,'context_kind':'teaching','known_parameters':params,
            'parameter_sources':{k:{'quote':text,'unit':unit_for(k)} for k in params},'assumptions':ASSUMPTIONS[domain],
            'locked_parameters':sorted(set(params)-set(variables)),'allowed_variables':variables,'goal':goal,
            'resource_budget':dict(DEFAULT_BUDGET),'parent_task_id':None}

def unit_for(key):
    return 'nm' if key.endswith('_nm') else 'um' if key.endswith('_um') else 'mm' if key.endswith('_mm') else 'rad' if key.endswith('_rad') else 'dimensionless'

def templates():
    values=[
      ('film-quarterwave','比较四分之一波长多层膜','film',{'material_n_high':2.4,'material_n_low':1.45,'layer_count':2,'design_wavelength_um':.633,'scan_min_um':.5,'scan_max_um':.8,'scan_points':61},{'layer_count':[2,4,6,8]}, {'metric':'reflectance','operator':'>=','target':.9,'wavelength_um':.633},'教学合成薄膜：空气两侧、正入射、无损无色散。高折射率2.4，低折射率1.45，设计波长0.633 um，扫描0.5–0.8 um，61个点另加目标点。比较2、4、6、8层交替四分之一波长膜，目标633 nm反射率至少0.9。'),
      ('diffraction-phase','双缝相位改变中心亮暗','diffraction',{'aperture':'double_slit','wavelength_nm':633,'focal_length_mm':200,'slit_width_um':20,'slit_separation_um':126.6,'relative_phase_rad':0,'grid_size':512,'window_mm':.5,'slit_height_um':100},{'relative_phase_rad':[0,math.pi/2,math.pi]},{'metric':'central_intensity_ratio','operator':'<=','target':.01},'教学合成双缝：均匀相干照明，波长633 nm，理想透镜焦距200 mm，缝宽20 um，中心距126.6 um，缝高100 um。只比较相对相位0、pi/2、pi rad，其余固定。数值窗口0.5 mm，512网格。目标中心强度与共同入射相位0基准之比≤0.01。'),
      ('gaussian-catalog','选择使屏幕光斑更小的透镜','gaussian',{'wavelength_nm':633,'waist_radius_um':500,'waist_z_mm':0,'focal_length_mm':100,'screen_distance_mm':100,'z_max_mm':250},{'focal_length_mm':[100,150,200]}, {'metric':'screen_radius_um','operator':'minimize','unit':'um'},'教学合成TEM00：空气、M²=1，波长633 nm，束腰半径500 um，束腰位于透镜处z=0 mm；屏幕在透镜后100 mm。比较焦距100、150、200 mm，使屏幕1/e²强度半径最小；绘制到250 mm。'),
    ]
    return [{'id':i,'title':title,'domain':d,'text':text,'spec':_spec(d,p,v,g,text)} for i,title,d,p,v,g,text in values]

PUBLIC_SCHEMA={
 'schema_version':1,'domain':'film | diffraction | gaussian','context_kind':'specified | teaching',
 'known_parameters':'object: only explicit known physical values, SI-submultiple units in parameter name',
 'parameter_sources':'object: EACH parameter -> {quote: exact substring of supplied facts, unit: nm/um/mm/rad/dimensionless}, or {quotes: 1-8 separate exact substrings, unit: same units}; never combine quote and quotes',
 'locked_parameters':'array of parameter names fixed by user, all non-variable parameters are additionally locked',
 'allowed_variables':'object parameter -> finite explicit candidate values; empty for single calculation',
 'goal':{'metric':'one domain metric','operator':'<= | >= | near | minimize | maximize','target':'finite threshold when needed','wavelength_um':'film single-point goal only','tolerance':'near goal only'},
 'resource_budget':DEFAULT_BUDGET,'parent_task_id':'null or provided parent id',
}
PROMPT='''你是光学实验规划助手，只输出 JSON {spec:完整规格或null,questions:字符串数组}。公开工具只接收数据，不可生成或执行Python。参数缺失必须追问，不可从教学示例或常识填实际参数。薄膜只支持空气两侧、无损无色散正入射；衍射只支持均匀相干照明的理想透镜傅里叶焦平面；高斯只支持M2=1理想TEM00空气薄透镜。高斯直径不能替代已知束腰位置与半径。每个参数都给逐字quote原文出处及转换后的单位。无依据参数不要填。场景和模型假设必须清楚，最终须用户核对批准。allowed_variables只能列原文明确提供的有限候选，所有其他已知物理参数锁定。修改目标保留parent规格和锁，不能自选更容易的入射光。film四分之一波长模板支持material_n_high,material_n_low,layer_count,design_wavelength_um与scan_min_um,scan_max_um,scan_points；也支持layers[{n,thickness_um}]和wavelengths_um实际数组。数值窗口/grid可不填，由固定工具公开给出数值选择。不能将自由传播距离当作透镜焦距。max_fast_evaluations衍射为每候选2次，不超过24。仅优化时finite best没有达标阈值，不可虚构达标。'''
PROMPT+='列为allowed_variables的参数也必须在known_parameters有基准值：优先保留原文或parent基准；若只有明确候选目录，则用目录首值作计算占位，不能冒称测量。该变量的parameter_sources.quote须逐字涵盖整个候选目录，必要时引用原文整段，不能只引基准。层数layer_count和网格grid_size等整数参数使用JSON整数。'
PROMPT+='回复顶层只有spec和questions。spec直接包含schema_version:1、domain、context_kind、known_parameters、parameter_sources、assumptions、locked_parameters、allowed_variables、goal、resource_budget、parent_task_id，绝不能包含名为schema的包装字段，也不要复制字段说明。非薄膜把max_meep_validations与max_fdtd均填0。goal仅填适用字段，优化目标省略target/tolerance/wavelength_um。'
PROMPT+='出处在不同位置时，可用parameter_sources中的{quotes:[第一段逐字原文,第二段逐字原文],unit:单位}，不要把非连续片段拼成一个quote，也不要改写标点。quote与quotes二选一。补充资料与原资料一起读取；明确缺失字段名称，不使用“此参数”等含糊指代。'
PROMPT+='questions仅列无法据已有文字确定、且阻止计算的缺失物理事实、冲突或不支持的条件。不要把逐项复述已明确参数当成追问；完整计划下一步会集中交给用户核对。补充资料已明确填入原先未知的字段时，该字段不再缺失。普通目标直接映射公开指标：指定屏幕上光斑尽量小=screen_radius_um+minimize；透镜后新束腰尽量小=new_waist_radius_um+minimize；屏幕光斑不超过给定半径=screen_radius_um+<=。显示曲线到某距离只填写z_max_mm，不改变屏幕距离或优化目标。明确写出“其余参数固定”时保留全部非变量参数；不要求用户学习或选择内部字段名。仅当原文确有不同物理解释时才追问。资料齐全即返回完整spec与空questions。'
PROMPT+='衍射的known_parameters必须包含aperture；单缝写single_slit，双缝写double_slit。这是必填模型类型，不能只在assumptions里写中文双缝后漏掉该字段。'

def normalize_explicit_aperture(spec,text):
    """Map an unambiguous stated aperture name, without guessing physical data."""
    s=copy.deepcopy(spec)
    if s.get('domain')!='diffraction' or 'aperture' in s.get('known_parameters',{}):return s,[]
    names={'single_slit':r'单缝|single[- ]slit','double_slit':r'双缝|double[- ]slit'}
    matches={k:list(re.finditer(pattern,text,re.I)) for k,pattern in names.items()}
    kinds=[k for k,v in matches.items() if v]
    if len(kinds)!=1:return s,[]
    key=kinds[0];match=matches[key][0]
    left=max(text.rfind(mark,0,match.start()) for mark in ('。','！','？','\n'))+1
    endings=[text.find(mark,match.end()) for mark in ('。','！','？','\n')]
    right=min([n for n in endings if n>=0] or [len(text)])
    quote=text[left:right]
    if re.search(r'不|非|未知|是否|可能|也许|假如|如果|\b(?:not|no|unknown|unsure|whether|maybe|if)\b',quote,re.I):return s,[]
    s.setdefault('known_parameters',{})['aperture']=key
    s.setdefault('parameter_sources',{})['aperture']={'quote':quote,'unit':'dimensionless'}
    return s,[{'parameter':'aperture','basis':'EXPLICIT_UNAMBIGUOUS_APERTURE_NAME','value':key,'quote':quote}]

def _validate_quotes(spec,text,parent=None):
    old=(parent or {}).get('spec',parent or {})
    for k,v in spec.get('known_parameters',{}).items():
        src=spec.get('parameter_sources',{}).get(k,{})
        if old.get('known_parameters',{}).get(k)==v and src==old.get('parameter_sources',{}).get(k):continue
        quotes=src.get('quotes',[src.get('quote','')])
        if not isinstance(quotes,list) or not 1<=len(quotes)<=8 or any(not isinstance(q,str) or not q or q not in text for q in quotes):raise ValueError('参数出处不是当前原文的逐字摘录：'+k)
        _ground_from_quotes(k,v,quotes)
        for alternative in spec.get('allowed_variables',{}).get(k,[]):_ground_from_quotes(k,alternative,quotes)
    return spec

def _ground_from_quotes(key,value,quotes):
    # Each span retains its units, including "10、15 cm" next to "200 mm".
    if isinstance(value,list):
        for item in value:
            if isinstance(item,dict):
                for k,v in item.items():_ground_from_quotes(k,v,quotes)
            else:_ground_from_quotes(key,item,quotes)
        return
    for quote in quotes:
        try:_ground_value(key,value,quote);return
        except ValueError:pass
    raise ValueError('参数数值或单位无法从引用核对：'+key)

def normalize_catalog_baselines(spec,parent=None):
    """Expand only explicitly listed candidates; never fill missing beam facts."""
    s=copy.deepcopy(spec);changes=[]
    p=s.get('known_parameters',{});sources=s.get('parameter_sources',{})
    old=(parent or {}).get('spec',parent or {})
    if not isinstance(p,dict) or not isinstance(sources,dict):raise ValueError('参数与来源必须为对象')
    for key,values in s.get('allowed_variables',{}).items():
        if key not in p and isinstance(values,list) and values and key in sources:
            p[key]=copy.deepcopy(old.get('known_parameters',{}).get(key,values[0]))
            changes.append({'parameter':key,'value':p[key],'basis':'EXPLICIT_PARENT_OR_FIRST_CATALOG_CANDIDATE_NOT_NEW_MEASUREMENT'})
    for key,value in p.items():
        if key in old.get('known_parameters',{}) and value==old['known_parameters'][key]:
            sources[key]=copy.deepcopy(old['parameter_sources'][key])
    s['known_parameters']=p;s['parameter_sources']=sources
    return s,changes

def complete_adjacent_catalog_quotes(spec,text):
    """Include a verbatim adjacent length catalog omitted from a baseline quote.

    Only the source span changes. All candidates must occur in the immediately
    following explicit numeric list; unrelated numbers elsewhere never qualify.
    """
    s=copy.deepcopy(spec);changes=[]
    number=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    adjacent=re.compile(r'^[，,：:\s]*(?:仅)?(?:可)?(?:比较|候选(?:目录)?|可选|目录)(?:为|是|仅|包括|[:：])?\s*'
                        r'(?P<catalog>'+number+r'(?:\s*[,，、]\s*'+number+r')+)\s*(?P<unit>nm|um|μm|µm|mm|cm|纳米|微米|毫米|厘米)(?![A-Za-z])')
    for key,values in s.get('allowed_variables',{}).items():
        if unit_for(key) not in ('nm','um','mm') or not isinstance(values,list):continue
        src=s.get('parameter_sources',{}).get(key,{})
        quote=src.get('quote')
        if not isinstance(quote,str) or not quote or text.count(quote)!=1:continue
        try:
            for v in values:_ground_value(key,v,quote)
            continue
        except ValueError:pass
        end=text.index(quote)+len(quote);match=adjacent.match(text[end:end+300])
        if not match:continue
        # Ground each candidate solely in this list, with its explicit unit.
        listed=match.group('catalog')+' '+match.group('unit')
        try:
            for v in values:_ground_value(key,v,listed)
        except ValueError:continue
        extended=text[end-len(quote):end+match.end()]
        src['quote']=extended
        changes.append({'parameter':key,'basis':'ADJACENT_EXPLICIT_CATALOG_SOURCE_SPAN','original_quote':quote,'expanded_quote':extended,'parameter_values_changed':False})
    return s,changes

def _ground_value(key,value,quote):
    """Reject invented numbers/units; human approval still reviews interpretation."""
    if isinstance(value,str):
        names={'double_slit':('双缝','double','two slits'),'single_slit':('单缝','single')}
        if value in names and not any(x in quote.lower() for x in names[value]):raise ValueError('孔径类型没有原文依据')
        return
    if isinstance(value,list):
        for item in value:
            if isinstance(item,dict):
                for k,v in item.items():_ground_value(k,v,quote)
            else:_ground_value(key,item,quote)
        return
    if not finite(value):raise ValueError('不能从出处核对非有限参数')
    normalized=quote.replace('π','pi').replace('μ','u').replace('µ','u')
    normalized=re.sub(r'pi\s*/\s*2',str(math.pi/2),normalized,flags=re.I)
    normalized=re.sub(r'\bpi\b',str(math.pi),normalized,flags=re.I)
    numbers=[]
    factors={'nm':1e-9,'纳米':1e-9,'um':1e-6,'微米':1e-6,'mm':1e-3,'毫米':1e-3,'cm':1e-2,'厘米':1e-2,'m':1,'米':1}
    unit=unit_for(key);scale=factors.get(unit)
    quoted_units=set(re.findall(r'(?<![A-Za-z])(nm|um|mm|cm|m|纳米|微米|毫米|厘米|米)(?![A-Za-z])',normalized))
    inherited=next(iter(quoted_units)) if len(quoted_units)==1 else None
    for match in re.finditer(r'(?<![A-Za-z0-9_.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?',normalized):
        n=float(match.group());tail=normalized[match.end():].lstrip()
        u=re.match(r'(nm|um|mm|cm|m|纳米|微米|毫米|厘米|米)(?![A-Za-z])',tail)
        # Bare numbers in a quoted candidate list inherit the declared field unit.
        explicit=u.group() if u else inherited
        numbers.append(n*factors[explicit]/scale if scale and explicit else n)
    if not any(math.isclose(n,value,rel_tol=1e-8,abs_tol=1e-10) for n in numbers):raise ValueError('参数数值或单位无法从引用核对：'+key)

def plan_from_text(text,context_kind='specified',client=None,ident=None,parent=None):
    if not isinstance(text,str) or not text.strip() or len(text)>24000:raise ValueError('请填写已有资料（最多24000字）')
    from ..workflow_model import wire
    if wire.credential_risk(text):raise ValueError('资料中含疑似凭据，请移除后重试')
    calls=0;raw=None
    if client is not None:
        from ..product_phase import json_payload
        response=client.complete(ident,json_payload(PROMPT,{'facts':text,'context_kind':context_kind,'parent':parent,'spec_field_descriptions':PUBLIC_SCHEMA,'response_shape':{'spec':'one ExperimentSpec object, or null if missing facts','questions':[]},'parameters':{k:sorted(v) for k,v in PARAMETERS.items()},'metrics':{k:sorted(v) for k,v in METRICS.items()}}))
        calls=int(response['audit'].get('live_dispatch',False))
        if response['audit']['status']!='ASSISTANT_RETURNED':return {'spec':None,'questions':['AI本次未返回可核对草稿，请保留资料后重试。'],'actual_model_calls':calls,'audit':response['audit']}
        raw=response['assistant']['content']
        try:obj=json.loads(raw)
        except (ValueError,TypeError):return {'spec':None,'questions':['AI返回格式无效，未执行任何计算。'],'actual_model_calls':calls,'raw_response':raw}
        if not isinstance(obj,dict) or obj.get('spec') is not None and not isinstance(obj.get('spec'),dict):return {'spec':None,'questions':['AI返回的实验结构无效，未执行计算。'],'actual_model_calls':calls,'raw_response':raw}
        s=obj.get('spec');questions=obj.get('questions',[])
        if not isinstance(questions,list) or any(not isinstance(q,str) for q in questions):questions=['AI问题格式无效，请重新核对资料。']
        if s is None:return {'spec':None,'questions':questions or ['仍缺少计算所需资料。'],'actual_model_calls':calls,'raw_response':raw}
        s['context_kind']=context_kind
    else:
        try:
            obj=json.loads(text)
            if not isinstance(obj,dict):raise ValueError('需要JSON对象')
            s=obj.get('spec',obj);questions=[]
        except (ValueError,TypeError):
            for t in templates():
                if context_kind=='teaching' and text==t['text']:s=t['spec'];questions=[];break
            else:
                return {'spec':None,'questions':['本地模式支持教学卡或完整实验JSON；自由文字请使用真实AI整理。未填写的实际参数不会自动补全。'],'actual_model_calls':0}
    try:
        s,normalizations=normalize_catalog_baselines(s,parent)
        if client is not None:
            s,aperture_changes=normalize_explicit_aperture(s,text);normalizations+=aperture_changes
            s,source_changes=complete_adjacent_catalog_quotes(s,text);normalizations+=source_changes
            _validate_quotes(s,text,parent)
        # Parent identity comes from the stored version, never a model guess.
        s['parent_task_id']=parent.get('id') if parent else None
        s=validate_spec(s,parent);plan=build_plan(s,parent)
        return {'spec':s,'questions':questions,'plan':plan,'actual_model_calls':calls,'raw_response':raw,'normalizations':normalizations}
    except (ValueError,KeyError,TypeError) as e:
        return {'spec':s,'questions':[str(e)],'actual_model_calls':calls,'raw_response':raw,'validation_error':True}
