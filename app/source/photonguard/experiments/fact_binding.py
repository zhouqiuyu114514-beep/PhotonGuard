"""Conservative, field-anchored language subset. Offsets always refer to raw text.

This is not a general Chinese semantic proof. Unrecognized prose stays unresolved.
"""
import re,copy
from .case_catalog import get_case
from .fact_state import allowed,unit,refresh

ALIASES={
 'wavelength_nm':['波长'], 'wavelength_min_um':['起始波长','最小波长'], 'wavelength_max_um':['终止波长','最大波长'],
 'focal_length_mm':['焦距'], 'waist_radius_um':['束腰半径'], 'waist_z_mm':['束腰位置','束腰位于','束腰在'],
 'screen_distance_mm':['屏幕距离','屏幕固定在','屏幕在','屏幕位于'],
 'slit_width_um':['缝宽'], 'slit_height_um':['缝高'], 'slit_separation_um':['缝距','双缝间距'],
 'relative_phase_rad':['相对相位','相位差','相位'], 'film_n':['膜折射率','薄膜折射率'],
 'thickness_um':['膜厚','厚度'], 'n_incident':['入射介质折射率'], 'n_substrate':['基底折射率'],
 'material_n_high':['高折射率材料折射率','高折射率材料','高折射率','高折射率层','nH','n_H','NH'],
 'material_n_low':['低折射率材料折射率','低折射率材料','低折射率','低折射率层','nL','n_L','NL'],
 'design_wavelength_um':['膜系设计波长','设计波长','中心设计波长'],
 'layer_count':['总层数','层数','初始为','初始只有','初始'],
 'wavelengths_um':['实际采样波长','计算波长','采样波长','扫描波长','波长列表','波长算','计算的波长','要算的波长','取样波长','要算'],
 'grid_size':['网格点数'], 'window_mm':['计算窗口'], 'z_max_mm':['绘图范围'],
}
METRICS={'screen_radius_um':['屏幕光斑半径','屏幕半径','屏幕1/e²半径','光斑半径'],
 'fringe_period_mm':['条纹周期','条纹间距'], 'first_zero_mm':['第一暗纹位置','第一暗纹'],
 'central_intensity_ratio':['中心强度比'], 'reflectance':['反射率'], 'transmittance':['透射率'],
 'reflectance_mean':['平均反射率'], 'transmittance_mean':['平均透射率'], 'reflectance_min':['最低反射率']}
OPS={'<=':r'不超过|不大于|不高于|至多|小于等于|≤|<=','>=':r'不少于|不小于|不低于|至少|大于等于|≥|>=',
 'near':r'接近|靠近|约为|改成|设为|目标(?:为|是)?', 'minimize':r'最小(?:化)?|尽量小|minimi[sz]e', 'maximize':r'最大(?:化)?|尽量大|maximi[sz]e'}
NUMBER=r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?'
UNIT=r'(?:nm|[uμµ]m|mm|cm|毫米|微米|纳米|厘米|rad|弧度|[%％])'
SCALE={'nm':1e-3,'纳米':1e-3,'um':1,'μm':1,'µm':1,'微米':1,'mm':1e3,'毫米':1e3,'cm':1e4,'厘米':1e4}

def numbers(text,target,allow_bare=False):
    text=re.sub(r'[（(]\s*(?:指\s*)?1/e(?:²|\^2|2)\s*强度半径\s*[）)]',lambda m:' '*len(m.group()),text,re.I)
    text=re.sub(r'(?<=\d)[–—~～-](?=\d)', ' ',text)
    vals=list(re.finditer('('+NUMBER+r')\s*('+UNIT+r')?',text,re.I))
    explicit=[m.group(2) for m in vals if m.group(2)]
    shared=explicit[-1] if explicit else None
    if not shared and vals:
        heading=re.search(r'[（(]\s*('+UNIT+r')\s*[）)]',text[:vals[0].start()],re.I)
        if heading:shared=heading.group(1)
    out=[]
    for m in vals:
        u=m.group(2) or shared
        if not u and target not in ('dimensionless','rad','fraction') and not allow_bare:return []
        v=float(m.group(1))
        if u in SCALE:
            if target not in SCALE:return []
            v*=SCALE[u]/SCALE[target]
        elif u in ('%','％'):
            if target not in ('dimensionless','fraction'):return []
            v/=100
        elif u in ('rad','弧度') and target!='rad':return []
        out.append(v)
    return out

def _parse_assertion(text,state,message_id):
    if re.search(r'如果|假如|若(?:是|为|将|把|波长|焦距)',text):return []
    case=get_case(state['case_id']);paths=allowed(case);operations=[];variable=case['recipe']['variable']
    aliases={**ALIASES,**METRICS,'tolerance':['绝对容差','容差'],'goal_wavelength':['目标波长','评价波长','评估波长']}
    if case['domain']=='film':aliases['goal_wavelength']+=['光源换成','光源换为','光源波长']
    for p in paths:
        if p.startswith('parameters.'):aliases.setdefault(p.split('.')[1],[])
    labels={}
    for k,vs in aliases.items():
        for label in [k,*vs]:labels[label]=k
    anchor=re.compile('|'.join(re.escape(k) for k in sorted(labels,key=len,reverse=True)))
    correction=bool(re.search(r'更正|确认|写错|改为|改成|换成|换为|收紧(?:为|到)|放宽(?:为|到)|调整(?:为|到)|取代|以.+为准|改目标|仅改|更新目标|撤回',text))
    def emit(field,value,start,end,unknown=False,context=None):
        if field not in paths:return
        if field in ('parameters.layer_count','parameters.scan_points','parameters.grid_size') and type(value) is float and value.is_integer():value=int(value)
        if field=='recipe.values' and variable=='layer_count' and isinstance(value,list):value=[int(v) if type(v) is float and v.is_integer() else v for v in value]
        e={'message_id':message_id,'start':start,'end':end}
        if context:e['question_ref']=context
        operations.append({'field':field,'value':value,'op':'unknown' if unknown else 'resolve','correction':correction,'unit':unit(field,case),'evidence':[e]})
    for clause in re.finditer(r'[^，。；;\n]+',text):
        raw=clause.group();matches=list(anchor.finditer(raw))
        for i,m in enumerate(matches):
            key=labels[m.group()];end=matches[i+1].start() if i+1<len(matches) else len(raw)
            tail=raw[m.end():end];start=clause.start()+m.start();stop=clause.start()+end
            correction=bool(re.search(r'更正|确认|写错|改为|改成|换成|换为|收紧(?:为|到)|放宽(?:为|到)|调整(?:为|到)|取代|以.+为准|改目标|仅改|更新目标|撤回|而是',raw[:end] if i==0 else raw[m.start():end]))
            if '撤回' in raw[:m.start()] and 'parameters.'+key in paths:
                emit('parameters.'+key,None,clause.start(),stop,True);operations[-1]['op']='retract';continue
            # Conditional/negated assertions are never promoted to facts.
            if re.search(r'假如|如果|若|不要|不能|并非|不是|不采用',raw[:m.start()+len(m.group())]):continue
            if re.search(r'不是|并非|不要|不能|不采用',tail):continue
            unknown=bool(re.search(r'未知|未确定|未核对|不清楚|待补|尚未',tail))
            is_metric=key in case['metrics'];u=('um' if key.endswith('_um') else 'mm' if key.endswith('_mm') else 'fraction') if is_metric else unit('parameters.'+key,case)
            if key=='tolerance':
                metric=next((o['value'] for o in reversed(operations) if o['field']=='goal.metric'),state['facts'].get('goal.metric',{}).get('value'))
                u='um' if str(metric).endswith('_um') else 'mm' if str(metric).endswith('_mm') else 'fraction'
            if key=='goal_wavelength':u='um'
            ns=numbers(tail,u)
            if unknown:ns=[]
            if is_metric:
                scope=raw[:end] if i==0 else raw[m.start():end]
                ops=[op for op,p in OPS.items() if re.search(p,scope,re.I)]
                # "目标" may accompany an explicit comparator without changing it.
                if len(ops)>1 and 'near' in ops:ops.remove('near')
                if not ops and len(ns)==1:ops=['near']
                if len(ops)!=1:continue
                emit('goal.metric',key,start,stop);emit('goal.operator',ops[0],start,stop)
                if ops[0] not in ('minimize','maximize') and len(ns)==1:emit('goal.target',ns[0],start,stop)
            elif key=='tolerance' and len(ns)==1:emit('goal.tolerance',ns[0],start,stop)
            elif key=='goal_wavelength' and len(ns)==1:emit('goal.wavelength_um',ns[0],start,stop)
            elif key=='wavelengths_um' and ns:emit('parameters.wavelengths_um',ns,start,stop)
            elif key==variable or key=='thickness_um' and variable=='layers':
                if re.search(r'范围|到|至|\.\.|[~～–]',tail):
                    if unknown:emit('recipe.min',None,start,stop,True);emit('recipe.max',None,start,stop,True)
                    elif len(ns)==2:emit('recipe.min',ns[0],start,stop);emit('recipe.max',ns[1],start,stop)
                elif len(ns)>1 or re.search(r'目录|候选|比较',raw):
                    if ns:emit('recipe.values',ns,start,stop)
                    elif unknown:emit('recipe.values',None,start,stop,True)
                elif len(ns)==1 and not re.search(r'最小|最大|至少|不超过',raw[:m.start()]):emit('parameters.'+key,ns[0],start,stop)
                elif unknown:emit('parameters.'+key,None,start,stop,True)
            elif key=='waist_z_mm' and len(ns)==1:
                v=ns[0]
                v=position(tail,v)
                emit('parameters.'+key,v,start,stop)
            elif len(ns)==1 and not re.search(r'最小|最大|至少|不超过',raw[:m.start()]):emit('parameters.'+key,ns[0],start,stop)
            elif unknown:emit('parameters.'+key,None,start,stop,True)
    if case['domain']=='film':
        if variable=='layer_count':
            for m in re.finditer(r'(?:比较|只比|候选|目录|考虑)\s*((?:'+NUMBER+r'\s*层?\s*[、,，/和及]\s*)+'+NUMBER+r')\s*层',text):
                values=numbers(m.group(1),'dimensionless')
                if values:emit('recipe.values',values,m.start(),m.end())
            for m in re.finditer(r'(?:初始(?:只有|为)?|先(?:只)?(?:考虑|做|用))\s*('+NUMBER+r')\s*层',text):
                emit('parameters.layer_count',float(m.group(1)),m.start(),m.end())
        reverse='('+NUMBER+r')\s*('+UNIT+r')\s*(?:的)?(?:膜系)?设计波长'
        quarter='('+NUMBER+r')\s*('+UNIT+r')\s*(?:波长)?(?:对应的?|的)?(?:四分之一|1/4)(?:波(?:长)?(?:光学)?厚度|波长|波)?'
        patterns=[reverse,
            r'光学厚度(?:为|是|取)?\s*('+NUMBER+r')\s*('+UNIT+r')\s*/\s*4(?![\d.])',
            r'(?:四分之一|1/4)波(?:长)?光学厚度(?:对应|按|取)\s*('+NUMBER+r')\s*('+UNIT+r')']
        if re.search(r'光学|(?:四分之一|1/4)波(?:长)?(?:光学)?(?:厚度|来设计)',text):patterns.append(quarter)
        for pattern in patterns:
            for m in re.finditer(pattern,text):
                if re.search(r'不是|并非|不要|不能|如果|假如',text[max(0,m.start()-8):m.start()]):continue
                value=numbers(m.group(1)+' '+m.group(2),'um')
                if len(value)==1:emit('parameters.design_wavelength_um',value[0],m.start(),m.end())
        pattern='('+NUMBER+r')\s*('+UNIT+r')\s*(?:处|时|下|的)?\s*(?:反射率|透射率)'
        for m in re.finditer(pattern,text):
            # A target point must not be a negated or hypothetical alternative.
            if re.search(r'不是|并非|不要|不能|如果|假如',text[max(0,m.start()-8):m.start()]):continue
            value=numbers(m.group(1)+' '+m.group(2),'um')
            if len(value)==1:emit('goal.wavelength_um',value[0],m.start(),m.end())
    # Only the single current question grants an implicit field/unit binding.
    questions=refresh(state)['questions']
    if not operations and len(questions)==1 and not anchor.search(text) and not re.search(r'如果|假如|不要|不是|未知',text):
        q=questions[0];fields=q['fields'];ns=numbers(text,q.get('unit','dimensionless'),allow_bare=True)
        if len(ns)==len(fields) and (q['kind']=='MISSING_FACT' or correction):
            for p,v in zip(fields,ns):
                if p=='parameters.waist_z_mm':
                    v=position(text,v)
                if p not in ('goal.metric','goal.operator'):emit(p,v,0,len(text),context=q['id'])
    if not operations and not anchor.search(text) and state['events'] and not re.search(r'不是|并非|不要|不能|不采用|未核对',text):
        from .fact_state import equal
        previous=state['events'][-1].get('changes',[])
        focus={c['field'] for c in previous if c['field'].startswith('parameters.')}
        if len(focus)==1:
            p=next(iter(focus));ns=numbers(text,unit(p,case));old=state['facts'].get(p,{})
            if len(ns)==1 and (correction or equal(ns[0],old.get('value'))):emit(p,ns[0],0,len(text),context='previous_event:'+state['events'][-1]['event_id'])
    # Duplicate equivalent mentions in one source do not imply a conflict.
    unique=[]
    for o in operations:
        if not any(o['field']==p['field'] and o['value']==p['value'] and o['op']==p['op'] for p in unique):unique.append(o)
    return unique


def position(text,value):
    """An explicit sign is evidence, never erased by a direction word."""
    front=bool(re.search(r'透镜前|镜片前|入射侧',text))
    back=bool(re.search(r'透镜后|镜片后|出射侧',text))
    sign=re.search(r'(?<![\d.])([+-])\d',text)
    if front and back or sign and ((front and sign[1]=='+') or (back and sign[1]=='-')):
        raise ValueError('POSITION_DIRECTION_CONFLICT')
    return -abs(value) if front else abs(value) if back else value


def gaussian_assumption(text):
    """Recognize complete fixed-model declarations, never drop unknown clauses."""
    compact=re.sub(r'[\s*#|]+','',text).lstrip('-•')
    if re.fullmatch(r'(?:确认)?(?:采用)?(?:当前)?(?:理想)?高斯光束模型[:：]TEM00[、,，]M(?:²|\^2|2)[=＝]1(?:\.0+)?',compact,re.I):return True
    if re.search('[:：]',compact):
        title,body=re.split('[:：]',compact,maxsplit=1)
        if re.fullmatch(r'(?:条件|模型|(?:请)?(?:为)?(?:一束)?(?:绿色)?激光(?:选择|选)?聚焦透镜(?:选择|选型)?)',title):compact=body
    patterns=[r'(?:确认)?(?:采用|使用|用|是|光束为)?(?:当前)?(?:空气中(?:传播的)?)?(?:理想)?TEM00(?:高斯光束)?',
              r'M(?:²|\^2|2)[=＝]1(?:\.0+)?',
              r'(?:所有)?(?:光斑)?半径(?:指|均为|为|是)1/e(?:²|\^2|2)强度半径',
              r'空气(?:中传播)?',r'(?:只|仅)?(?:使用|用)?一片理想薄透镜']
    parts=re.split('[、,，]',compact)
    return bool(parts) and all(any(re.fullmatch(p,part,re.I) for p in patterns) for part in parts)


def parse_update(text,state,message_id):
    """Small scoped intent interpreter; proposals never become resolve operations."""
    result={'confirmed_operations':[],'retained_fields':[],'proposed_operations':[],
            'ambiguities':[],'consumed_spans':[],'pending_intent':None}
    case=get_case(state['case_id'])
    labels={label:'parameters.'+key for key,values in ALIASES.items() for label in [key,*values]}
    labels.update({label:'goal.target' for key,values in METRICS.items() for label in [key,*values]})
    labels.update({'快速计算':'execution.fast_only','Meep':'execution.fast_only','FDTD':'execution.fast_only'})
    labels.update({'目标':'goal.target','容差':'goal.tolerance','腰斑':'parameters.waist_z_mm'})
    anchor=re.compile('|'.join(re.escape(k) for k in sorted(labels,key=len,reverse=True)))
    keep=r'先别|别(?:把|将|改)|不要|不用(?:改|把|将)|不(?:要|用)?改|不采用|保持|保留|其余不变|并非|不是|不是本次'
    uncertain=r'尚待核对|未核对|待核对|未确认|没确认|尚未确认|还没确认|草稿|另有记录|记录[上中]|仅供参考|没测量|先别填'
    conditional=r'如果|假如|除非|否则|若(?:获|得到|是|为|将|把|波长|焦距)|待.{0,8}批准|批准后|可以.{0,12}(?:改|设)|是否(?:可以|应该)?(?:把|将|改|设|采用)|是否(?:为|是)?\s*[-+]?\d|会怎样|假设'
    correction=r'更正|写错|改为|改成|换成|换为|取代|以.+为准|改目标|仅改|更新目标|撤回|确认|而是'
    # Semicolon/full stop reset scope. A trailing comma qualifier attaches to
    # its previous field, while conditional scope spans the entire sentence.
    for sentence in re.finditer(r'[^。；;\n]+',text):
        body=sentence.group();parts=list(re.finditer(r'[^，]+',body));clauses=[]
        for part in parts:
            if clauses and not anchor.search(part.group()) and re.search(uncertain,part.group()):
                clauses[-1][1]=part.end()
            else:clauses.append([part.start(),part.end()])
        for start,end in clauses:
            raw=body[start:end];offset=sentence.start()+start
            fields=list(dict.fromkeys(labels[m.group()] for m in anchor.finditer(raw)))
            if not fields and re.search(NUMBER,raw) and len(refresh(state)['questions'])==1:fields=refresh(state)['questions'][0]['fields']
            fields=[p for p in fields if p in allowed(case)]
            # Reporting instructions and table headers contain no physical change.
            header=bool(re.fullmatch(r'[\s|]*(?:(?:参数|项目|条件|数值|取值|值|单位|说明|设置)[\s|]*)+',raw))
            reporting=not anchor.search(body) and not re.search(NUMBER,body) and bool(re.search(r'(?:如果|若).*?(?:没有|无|未|不).*?(?:候选|方案|达标).*?(?:说明|告诉|报告|如实|照实|直说|告知|提示)',body))
            # A conditional request to report the best feasible candidate is not
            # a hypothetical edit to physical conditions or to the threshold.
            ranking_report=bool(re.fullmatch(r'\s*(?:如果|若)(?:有)?多个(?:候选)?达标[，,]\s*(?:请)?指出(?:其中)?光斑最小(?:的)?(?:候选|那个|者)\s*',body)) and case['domain']=='gaussian'
            fixed_assumption=case['domain']=='gaussian' and gaussian_assumption(raw)
            incompatible_radius=(case['domain']=='gaussian' and re.search(r'FWHM|半高全宽|半高宽|1/e(?![²2^])(?:强度)?半径',raw,re.I)
                                 and not re.search(r'不是|不用|不采用|不要|不按',raw))
            excluded_mode=case['domain']=='gaussian' and re.search(r'(?:不是|非|不用|不采用)\s*TEM00',raw,re.I)
            if incompatible_radius or excluded_mode:
                result['ambiguities'].append({'start':offset,'end':offset+len(raw),'kind':'UNRESOLVED_MODEL_CONVENTION','fields':[],
                    'text':'当前高斯模型采用 TEM00、M²=1 和 1/e² 强度半径；这项定义不一致，不能直接代入：'+raw})
                result['consumed_spans'].append([offset,offset+len(raw)]);continue
            if header or reporting or ranking_report or fixed_assumption:
                result['consumed_spans'].append([offset,offset+len(raw)]);continue
            is_conditional=bool(re.search(conditional,body)) and bool(fields or re.search(NUMBER,raw) or re.search(r'如果|假如|除非|否则|批准',raw))
            is_uncertain=bool(re.search(uncertain,raw))
            is_keep=(bool(re.search(keep,raw)) or not re.search(NUMBER,raw) and bool(re.search(r'不变|照旧|沿用',raw))) and not raw.lstrip().startswith('而是')
            if not re.search(NUMBER,raw) and not is_conditional and not re.search(r'只|仅|Meep|FDTD',raw,re.I) and re.search(r'计算|说明|解释|确认使用',raw) and not re.search(r'改为|改成|设为|旋转|更换',raw):
                result['retained_fields'].extend(fields)
                result['consumed_spans'].append([offset,offset+len(raw)])
                continue
            policy=None
            if re.search(r'(?:只|仅)(?:做|用|使用|进行|运行|需要)?\s*(?:快速|TMM)|(?:不做|不要|不用|禁止|不运行|不进行|无需|不需要)\s*(?:Meep|FDTD|独立验证|独立核对|全波)',raw,re.I):policy=True
            elif re.search(r'^(?:确认|明确)?(?:允许|启用|开启|执行)\s*(?:Meep|FDTD)(?:独立)?(?:验证|核对|计算)?[。！!\s]*$',raw,re.I):policy=False
            if policy is not None and not is_conditional and not is_uncertain:
                result['confirmed_operations'].append({'field':'execution.fast_only','value':policy,'op':'resolve','correction':True,'unit':'dimensionless','evidence':[{'message_id':message_id,'start':offset,'end':offset+len(raw)}]})
                result['consumed_spans'].append([offset,offset+len(raw)]);continue
            # A later assertion can explicitly replace a negated earlier one.
            if is_keep and not is_conditional:
                result['retained_fields'].extend(fields)
                result['consumed_spans'].append([offset,offset+len(raw)])
                continue
            if is_conditional or is_uncertain:
                kind='CONDITIONAL_PROPOSAL' if is_conditional else 'UNCONFIRMED_VALUE'
                result['pending_intent']=kind
                for field in fields:
                    vals=numbers(raw,unit(field,case))
                    result['proposed_operations'].append({'field':field,'value':vals[0] if len(vals)==1 else None,'status':'proposed','activated':False,'source_kind':'user_proposal','evidence':[{'message_id':message_id,'start':offset,'end':offset+len(raw)}]})
                    result['ambiguities'].append({'start':offset,'end':offset+len(raw),'kind':kind,'fields':[field],'text':('先作为待确认的比较方案；原实验不变。请明确确认：' if is_conditional else '这项资料尚待核对，旧值未修改。请确认：')+field})
                if not fields:result['ambiguities'].append({'start':offset,'end':offset+len(raw),'kind':kind,'fields':[],'text':'这项比较或待核对资料尚未明确，原实验不变。'})
                result['consumed_spans'].append([offset,offset+len(raw)])
                continue
            # Unique metric short correction keeps the established metric/operator.
            if re.search(r'目标(?:改成|改为|更正)',raw) and state['facts'].get('goal.metric',{}).get('status')=='resolved':
                metric=state['facts']['goal.metric']['value'];u='um' if metric.endswith('_um') else 'mm' if metric.endswith('_mm') else 'fraction'
                vals=numbers(raw,u)
                ops=[{'field':'goal.target','value':vals[0],'correction':True,'unit':u,'evidence':[{'message_id':message_id,'start':0,'end':len(raw)}]}] if len(vals)==1 else []
            else:
                context=copy.deepcopy(state)
                for prior in result['confirmed_operations']:
                    context['facts'][prior['field']]={'value':prior['value'],'status':'resolved' if prior.get('op','resolve')=='resolve' else 'unknown','locked':False}
                try:ops=_parse_assertion(raw,context,message_id)
                except ValueError as exc:
                    if str(exc)!='POSITION_DIRECTION_CONFLICT':raise
                    result['ambiguities'].append({'start':offset,'end':offset+len(raw),'kind':str(exc),'fields':['parameters.waist_z_mm'],'text':'束腰方位与正负号矛盾：透镜前为负、后为正。请只确认束腰位置（mm）。'})
                    result['consumed_spans'].append([offset,offset+len(raw)]);continue
            for op in ops:
                # The anchored parser assigns correction per field, not per sentence.
                if op['field']=='goal.tolerance' and any(o['field']=='goal.target' and o.get('correction') for o in result['confirmed_operations']):op['correction']=True
                for evidence in op['evidence']:evidence['start']+=offset;evidence['end']+=offset
            result['confirmed_operations'].extend(ops)
            if ops:result['consumed_spans'].append([offset,offset+len(raw)])
            elif re.search(r'改|更正|设为|采用|计算|求解|范围|参数|\d',raw) and not (not fields and not re.search(r'\d|参数|范围|改|设为',raw) and re.search(r'计算|求解|运行',raw)):
                result['ambiguities'].append({'start':offset,'end':offset+len(raw),'kind':'UNRESOLVED_CLAUSE','fields':fields,'text':'这部分条件尚不能确定，请核对：'+raw})
    return result


def parse(text,state,message_id):
    return parse_update(text,state,message_id)['confirmed_operations']
