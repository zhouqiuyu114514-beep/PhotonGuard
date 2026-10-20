"""Independent semantic reading plus application-checked source/value evidence.

This is model agreement, not a mathematical proof of language semantics. It is
used only when the deterministic reader cannot bind the original text.
"""
import copy, math, re
from . import fact_state as fs
from .case_catalog import get_case
from .fact_binding import numbers, position, parse_update, UNIT, NUMBER
from .action_protocol import canonical_field, decode

PROMPT = """你是独立的原文证据阅读器，不是设计助手。只读用户原文、当前已确认事实和支持的字段；不得补教学默认值或猜测。输出JSON：{bindings:[{field:字段路径,value:规范单位的值,quote:含该数值的逐字短片段,context:能确定该字段语义及否定/条件作用域的完整逐字句子,assertion:true,correction:false}],nonfacts:[{quote:逐字片段,kind:"presentation"}]}。不要输出计算计划。
独立提取原文明确断言的条件，允许上下文指代、并列省略、范围句承接上一句。quote逐字复制，context必须包含quote并包含字段指代所需上下文。quote应尽量只包含该字段对应的单个数值及单位，宽和高分别给出的两个数值也分别提取。goal.target出现时必须同时输出goal.metric及goal.operator，即使这两个字段没有数值也必须提取。goal.wavelength_um仅适用于薄膜场景，高斯和双缝的光源波长必须写parameters.wavelength_nm。必须遍历所有明确条件，不遗漏并列句的宽高、材料折射率和候选目录。只用allowed_fields列出的精确字段及对应单位，禁止自造wavelength_um等字段或保留cm的未换算值。所有数值应来自quote，单位可换算；数组保留完整顺序。字段路径为parameters.xxx、recipe.min/max/values、goal.metric/operator/target/tolerance/wavelength_um、execution.fast_only。goal.metric为当前案例支持指标，operator仅<=、>=、near、minimize、maximize。recipe是允许修改的变量，不将范围改成目录，不将候选数量当初始参数。对高斯位置透镜前为负，后为正。只有明确改动已知值时correction=true。
不要提取未知、猜测、假设、被否定、冲突未解、条件成立后才修改的值；仅想比较和当前确定使用不同。不能从别的字段借数值。目标波长与设计波长、采样波长不同。只做快速计算表示execution.fast_only=true，不能自动启用独立验证。
对提供的unresolved_clauses逐条判断：若只是展示、安排比较、筛选已有候选、课堂背景或确认执行的要求，必须完整收入nonfacts；若有物理约束不能这样处理。nonfacts只收录没有额外物理条件或数值、仅说明展示/挑选结果/确认后执行/教学背景的原句，例如没有可行方案就如实说明。绝不能把未支持物理条件归为展示要求。固定模型超出能力范围必须留待核对。可额外输出assumptions:[{field:"mode|beam_quality|radius_definition|medium|lens_count",value:"TEM00|1|1/e2_intensity_radius|air|1",quote:逐字声明}]。这些只用于识别当前高斯固定模型的等价描述；不得遗漏明确声明，数值1用JSON数字。所有提取只是待核验建议。"""


def needs_review(state,text,model_obj):
    parsed=parse_update(text,state,'preview')
    ops=parsed['confirmed_operations'];case=get_case(state['case_id'])
    return bool(parsed['ambiguities']) or any(not any(o['field']==canonical_field(p.get('field'),case) and fs.equal(o['value'],p.get('value')) for o in ops) for p in model_obj.get('patches',[]) if isinstance(p,dict))


def checked(state,text,mid,model_obj,review):
    """Both readers must agree; numeric/source/enum/constraint gates stay local."""
    case=get_case(state['case_id']);ops=[];spans=[];notes=[]
    patches=model_obj.get('patches',[])
    local=parse_update(text,state,mid)['confirmed_operations']
    for b in review.get('bindings',[]):
        if not isinstance(b,dict) or b.get('assertion') is not True:continue
        field=canonical_field(b.get('field'),case);value=b.get('value')
        if field not in fs.allowed(case):continue
        quote=b.get('quote');context=b.get('context')
        if not isinstance(quote,str) or not quote or not isinstance(context,str) or not context or len(context)>1200:continue
        if text.count(context)!=1:continue
        locations=[m.start() for m in re.finditer(re.escape(quote),context) if not (quote[0].isdigit() and m.start()>0 and context[m.start()-1] in '0123456789.') and not (quote[-1].isdigit() and m.end()<len(context) and context[m.end()] in '0123456789.')]
        if len(locations)!=1:continue
        quote_start=locations[0]
        if not any(canonical_field(p.get('field'),case)==field and fs.equal(p.get('value'),value) for p in patches if isinstance(p,dict)):continue
        # Exclude conditional/uncertain readings even if two model calls agree.
        if re.search(r'如果|假如|除非|批准后|未确认|待核对|不确定|可能|猜测|尚未|不是|并非|不要改|先别',context):continue
        if any(o['field']==field and not fs.equal(o['value'],value) for o in ops):continue
        selected_offset=None
        u=fs.unit(field,case)
        metric=next((p.get('value') for p in patches if p.get('field')=='goal.metric'),state.get('facts',{}).get('goal.metric',{}).get('value'))
        if field in ('goal.target','goal.tolerance') and isinstance(metric,str):
            u='um' if metric.endswith('_um') else 'mm' if metric.endswith('_mm') else 'fraction'
        if field=='goal.metric':valid=value in case['metrics']
        elif field=='goal.operator':valid=value in ('<=','>=','near','minimize','maximize')
        elif field=='execution.fast_only':
            # Never authorize extra compute through the semantic fallback.
            valid=value is True and bool(re.search(r'快速|不做.*(?:Meep|FDTD)|不要.*(?:Meep|FDTD)',context,re.I))
        else:
            vals=numbers(quote,u)
            if not vals and not re.search(UNIT,quote,re.I):
                units=set(re.findall(UNIT,context,re.I))
                if len(units)==1:vals=numbers(quote+' '+next(iter(units)),u)

            if isinstance(value,list):valid=bool(value) and fs.equal(vals,value)
            elif type(value) in (int,float) and math.isfinite(value):
                # Select the exact numeric token from a coordinated phrase.
                # Both independent readers already agreed on its field meaning.
                candidates=[]
                for token in re.finditer('('+NUMBER+r')\s*('+UNIT+r')?',quote,re.I):
                    piece=token.group();units=set(re.findall(UNIT,quote,re.I)) or set(re.findall(UNIT,context,re.I))
                    if u not in ('dimensionless','fraction','rad') and not token.group(2) and len(units)==1:piece+=' '+next(iter(units))
                    nv=numbers(piece,u)
                    if field=='parameters.waist_z_mm' and len(nv)==1:
                        begin=quote_start+token.start()
                        left=max(context.rfind(c,0,begin) for c in '，,。；;、\n')+1
                        ends=[context.find(c,begin) for c in '，,。；;、\n'];right=min([x for x in ends if x>=0] or [len(context)])
                        try:nv=[position(context[left:right],nv[0])]
                        except ValueError:continue
                    if len(nv)==1 and fs.equal(nv[0],value):candidates.append((token.start(),token.end()))
                valid=len(candidates)==1
                if valid:
                    lo,hi=candidates[0];selected_offset=quote_start+lo;quote=quote[lo:hi]
            else:valid=False
        if not valid:continue
        start=text.index(context);qstart=start+(selected_offset if selected_offset is not None else quote_start)
        if any(o['field']!=field and fs.equal(o['value'],value) and any(e['start']<=qstart and e['end']>=qstart+len(quote) for e in o['evidence']) for o in local) and not any(o['field']==field and fs.equal(o['value'],value) for o in local):
            continue
        ops.append({'field':field,'value':value,'op':'resolve','correction':b.get('correction') is True,'unit':u,'evidence':[{'message_id':mid,'start':qstart,'end':qstart+len(quote),'context_start':start,'context_end':start+len(context),'verification':'independent_semantic_agreement_with_numeric_check'}]})
        spans.append((start,start+len(context)))
    # A context is not automatically consumed: every numeric clause must have
    # its own accepted value-bearing quote. Thus a long quote cannot hide extras.
    coverage=[]
    for o in ops:
        if type(o['value']) in (int,float) or isinstance(o['value'],list):
            e=o['evidence'][0];coverage.append((e['start'],e['end']))
    for n in review.get('nonfacts',[]):
        if not isinstance(n,dict) or n.get('kind')!='presentation':continue
        q=n.get('quote','')
        if not q or text.count(q)!=1 or re.search(r'\d|改为|改成|设为|改到|换成|增加|减少|旋转|偏振|吸收|非线性|像差|截断|损伤',q):continue
        start=text.index(q);coverage.append((start,start+len(q)))
    supported={'mode':'TEM00','beam_quality':1,'radius_definition':'1/e2_intensity_radius','medium':'air','lens_count':1}
    if case['domain']=='gaussian':
        for a in review.get('assumptions',[]):
            if not isinstance(a,dict) or a.get('field') not in supported or not fs.equal(a.get('value'),supported[a['field']]):continue
            q=a.get('quote','')
            if not isinstance(q,str) or not q or text.count(q)!=1 or re.search(r'不是|非TEM|不用|不采用|如果|未知|待核对',q):continue
            if not any(isinstance(x,dict) and x.get('field')==a['field'] and fs.equal(x.get('value'),a['value']) for x in model_obj.get('assumptions',[])):continue
            expected={'mode':[0.0],'beam_quality':[1.0],'radius_definition':[1.0],'medium':[],'lens_count':[]}[a['field']]
            actual=[float(x) for x in re.findall(NUMBER,q)]
            if actual!=expected:continue
            coverage.append((text.index(q),text.index(q)+len(q)))
    notes.append({'kind':'SEMANTIC_EVIDENCE_REVIEW','accepted_fields':[o['field'] for o in ops],'basis':'two_model_readings_plus_exact_source_numeric_and_scope_checks','not_a_formal_semantic_proof':True})
    return ops,coverage,notes


def fit_numerical_defaults(state):
    """Fit only unclaimed numerical defaults; never change user/parent facts."""
    case=get_case(state['case_id'])
    if case['domain']!='diffraction':return state
    facts=state['facts'];get=lambda p:facts.get(p,{})
    width=get('parameters.slit_width_um').get('value');height=get('parameters.slit_height_um').get('value')
    if type(width) not in (int,float) or type(height) not in (int,float):return state
    separation=get('parameters.slit_separation_um').get('value',0)
    if case['recipe']['variable']=='slit_separation_um':separation=get('recipe.max').get('value',separation)
    values=get('recipe.values').get('value')
    if case['recipe']['variable']=='slit_separation_um' and isinstance(values,list) and values:separation=max(values)
    if type(separation) not in (int,float):return state
    window=get('parameters.window_mm');grid=get('parameters.grid_size')
    wanted=max(width+separation,height)/800
    changes=[];before_defaults={p:copy.deepcopy(facts.get(p)) for p in ('parameters.window_mm','parameters.grid_size')}
    if window.get('source_kind')=='numeric_default' and window.get('status')=='resolved' and wanted>window['value']:
        old=window['value'];window['value']=round(math.ceil(wanted*1000)/1000,3)
        window['fact_id']=__import__('hashlib').sha256(str(['numerical_fit',window['value'],width,height,separation]).encode()).hexdigest()[:20]
        changes.append({'field':'parameters.window_mm','before':old,'after':window['value']})
    if window.get('status')=='resolved' and grid.get('source_kind')=='numeric_default' and grid.get('status')=='resolved' and min(width,height)/(window['value']*1000/grid['value'])<8 and grid['value']==256:
        grid['value']=512;grid['fact_id']=__import__('hashlib').sha256(b'numerical_fit_grid512').hexdigest()[:20]
        changes.append({'field':'parameters.grid_size','before':256,'after':512})
    if changes:
        for c in changes:
            state['events'][-1].setdefault('changes',[]).append({'field':c['field'],'before':before_defaults[c['field']],'after':copy.deepcopy(facts[c['field']])})
        state['events'][-1].setdefault('interpretation_notes',[]).append({'kind':'NUMERICAL_DEFAULTS_FIT_APERTURE','changes':changes,'physical_conditions_changed':False,'basis_fields':['parameters.slit_width_um','parameters.slit_height_um','recipe.max','recipe.values','parameters.slit_separation_um']})
    return state
