"""Thin source-bound observation adapter; no alternate solver or autonomous approval."""
import copy
import json
import re
from ..core import digest
from ..workflow import WorkflowError
from . import inference, observations
from .fact_state import equal

LABELS={'fixed.wavelength_nm':'波长','fixed.focal_length_mm':'透镜焦距','fixed.slit_width_um':'缝宽',
 'fixed.relative_phase_rad':'相对相位','fixed.measurement_plane':'测量平面','position_unit':'位置单位',
 'bounds.slit_separation_um':'缝距范围','bounds.center_shift_mm':'中心平移范围',
 'bounds.amplitude':'幅度范围','bounds.background':'背景范围','loss':'损失方式','f_scale':'残差尺度'}
FOCI=['overview','parameters','residuals','outliers','limitations','next_step']
NUM=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
UNIT=r'(?:nm|um|μm|µm|mm|cm|纳米|微米|毫米|厘米|米|m)'
ALIASES={'fixed.wavelength_nm':r'波长','fixed.focal_length_mm':r'(?:透镜)?焦距',
 'fixed.slit_width_um':r'缝宽|等宽','fixed.relative_phase_rad':r'(?:相对)?相位',
 'bounds.slit_separation_um':r'缝距','bounds.center_shift_mm':r'中心(?:平移|偏移)',
 'bounds.amplitude':r'幅度','bounds.background':r'背景','f_scale':r'f_scale|残差尺度'}
SEP=r'\s*(?:是|为|等于|=|约|在|范围|估计|从|改为|更正为|：|:|\s)*\s*'
SCALE={'nm':1e-6,'纳米':1e-6,'um':.001,'μm':.001,'µm':.001,'微米':.001,'mm':1.,'毫米':1.,'cm':10.,'厘米':10.,'m':1000.,'米':1000.}


def flattened(settings):
    out={}
    for k in ('fixed','bounds'):
        for field,value in (settings.get(k) or {}).items():out[k+'.'+field]=copy.deepcopy(value)
    for k in ('loss','f_scale'):
        if k in settings:out[k]=settings[k]
    return out


def facts(record):
    out=copy.deepcopy(record.get('observation_facts',{}))
    # Legacy/manual conditions are retained with their actual source, never inferred.
    for field,value in flattened(record.get('fit_settings') or {}).items():
        if field not in out and value is not None:
            out[field]={'value':value,'status':'resolved','source_kind':'EXPLICIT_TEACHING' if record.get('sample_id') else 'USER_FORM','evidence':[]}
    if 'position_unit' not in out and record['observation'].get('position_unit'):
        out['position_unit']={'value':record['observation']['position_unit'],'status':'resolved','source_kind':'CSV_METADATA','evidence':[]}
    return out


def grounded(field,value,quote,text):
    """Reject borrowed numbers, negative/hypothetical facts and unquoted changes."""
    if field not in LABELS or not isinstance(quote,str) or not quote or quote not in text:raise ValueError('字段缺少本轮原文出处')
    at=text.index(quote)
    clause=re.split(r'[，,。；;\n]',text[:at])[-1]+quote+re.split(r'[，,。；;\n]',text[at+len(quote):])[0]
    if re.search(r'如果|假如|假设|例如|比如|能否|是不是|是否|\?|？',clause):raise ValueError('假设或问句不能直接登记为事实')
    alias=ALIASES.get(field,r'测量平面|焦平面|近场' if field=='fixed.measurement_plane' else r'位置|坐标|单位' if field=='position_unit' else r'损失')
    if value is None:
        if re.search(alias,quote) and re.search(r'未知|不确定|未确认|不知道|不清楚|未测|撤回',quote):return
        raise ValueError('撤回事实需要明确未知或撤回出处')
    if re.search(r'不是|并非|并不|不采用|不要|不确定|未确认|未知|不对|写错|不同相|不等于|不为',clause):raise ValueError('不能把否定或未知条件当已知')
    if field=='fixed.measurement_plane':
        if value=='FOURIER_FOCAL_PLANE' and re.search(r'(?:透镜|傅里叶).*?焦平面',quote):return
        if value=='NEAR_FIELD' and re.search(r'近场|自由传播',quote):return
    elif field=='fixed.relative_phase_rad':
        if type(value) in (int,float) and value==0 and re.search(r'同相|相位(?:差)?\s*(?:为|是|=)?\s*0(?:\.0+)?(?![\d.])',quote):return
        for m in re.finditer(r'(?:相对)?相位(?:差)?'+SEP+'('+NUM+r')\s*(?:rad|弧度)',quote):
            if equal(value,float(m.group(1))):return
    elif field=='position_unit':
        units={'毫米':'mm','mm':'mm','微米':'um','um':'um','μm':'um','µm':'um','米':'m','m':'m','像素':'pixel','pixel':'pixel'}
        found=re.search(r'毫米|微米|\bmm\b|\bum\b|[μµ]m|米|\bm\b|像素|pixel',quote)
        if found and value==units[found.group()] and re.search(r'位置|坐标|单位',quote):return
    elif field=='loss':
        if value=='soft_l1' and re.search(r'soft_l1|鲁棒损失',quote):return
        if value=='linear' and re.search(r'linear|普通最小二乘|普通平方残差',quote):return
    elif field in ALIASES:
        is_range=field.startswith('bounds.')
        pattern='(?:'+alias+')'+SEP+'('+NUM+')'
        if is_range:pattern+=r'\s*('+UNIT+r')?\s*(?:到|至|~|～|—|–|-)\s*('+NUM+')'
        pattern+=r'\s*('+UNIT+')?'
        for m in re.finditer(pattern,quote,re.I):
            if is_range:
                a,ua,b,ub=m.groups();unit=ub or ua
                if ua and ub and ua!=ub:continue
                vals=[float(a),float(b)]
            else:a,unit=m.groups();vals=[float(a)]
            length=field in ('fixed.wavelength_nm','fixed.focal_length_mm','fixed.slit_width_um','bounds.slit_separation_um','bounds.center_shift_mm')
            if length:
                if unit not in SCALE:continue
                target=1e-6 if field.endswith('wavelength_nm') else .001 if field.endswith(('slit_width_um','slit_separation_um')) else 1.
                vals=[n*SCALE[unit]/target for n in vals]
            elif unit:continue
            if equal(value,vals if is_range else vals[0]):return
    raise ValueError('字段与原文的含义、单位或数值不符：'+LABELS[field])


def numerical_recipe(dataset,settings):
    """Single fixed recipe; training points only; never supplies physical facts."""
    import numpy as np
    settings=copy.deepcopy(settings);settings.setdefault('fixed',{});settings.setdefault('bounds',{})
    keep=np.arange(dataset['rows'])%5!=0;y=np.asarray(dataset['intensity'])[keep]
    low,high=map(float,np.quantile(y,[.05,.95]));span=max(high-low,1e-6)
    suggestions={'bounds.amplitude':[max(1e-9,span*.001),max(span*4,1e-6)],'bounds.background':[low-span,high+span],
                 'loss':'soft_l1','f_scale':max(1e-6,span*.02)}
    if dataset['x_mm'] is not None:
        x=np.asarray(dataset['x_mm'])[keep];half=max(float(x[-1]-x[0])*.1,1e-6);middle=float((x[0]+x[-1])/2)
        suggestions['bounds.center_shift_mm']=[middle-half,middle+half]
    added={}
    for path,value in suggestions.items():
        part=path.split('.');container=settings.setdefault(part[0],{}) if len(part)==2 else settings;key=part[-1]
        if key not in container or container[key] is None:
            container[key]=value;added[path]={'value':value,'status':'resolved','source_kind':'NUMERICAL_SUGGESTION','recipe':'training_scale_v1','evidence':[]}
    return settings,added,{'id':'training_scale_v1','split':'every fifth point held out before initialization','training_count':int(keep.sum()),'holdout_used':False,
      'note':'训练点的强度分位差给幅度、背景和残差尺度建议；训练坐标中点附近的扫描跨度10%给平移范围。不是光轴测量或仪器标定；只补空缺，不扩大已有范围。'}


def apply_proposal(record,text,proposal):
    if not isinstance(proposal,dict) or set(proposal)!={'updates','recipe','focus'} or proposal['focus'] not in FOCI or proposal['recipe'] not in (None,'training_scale_v1') or not isinstance(proposal['updates'],list) or len(proposal['updates'])>len(LABELS):raise ValueError('数据向导回复格式无效')
    state=facts(record);settings=copy.deepcopy(record.get('fit_settings') or {});settings.setdefault('fixed',{});settings.setdefault('bounds',{})
    seen=set();changes=[]
    for op in proposal['updates']:
        if not isinstance(op,dict) or set(op)!={'field','value','quote','correction'} or type(op['correction']) is not bool:raise ValueError('字段修改格式无效')
        path,value,quote=op['field'],op['value'],op['quote']
        if path in seen:raise ValueError('同一轮字段重复修改')
        seen.add(path);grounded(path,value,quote,text)
        if op['correction'] and not re.search(r'更正|改为|改成|写错|撤回|未知|不确定|未确认|未测|不清楚',text):raise ValueError('没有明确更正依据')
        evidence={'quote':quote,'start':text.index(quote),'end':text.index(quote)+len(quote),'text_sha256':digest(text)}
        old=state.get(path);item={'value':value,'status':'unknown' if value is None else 'resolved','source_kind':'USER_TEXT','evidence':[evidence]}
        if old and old['status']=='resolved' and equal(old['value'],value):item={**old,'evidence':old.get('evidence',[])+[evidence]}
        elif old and old['status'] in ('resolved','conflict') and old['source_kind']!='NUMERICAL_SUGGESTION' and not op['correction']:
            item={**old,'status':'conflict','conflict':{'attempted_value':value,'evidence':[evidence]}}
        state[path]=item;changes.append({'field':path,'before':old,'after':item})
    # Rebuild only explicitly tracked values; unresolved facts cannot sign a plan.
    dataset=copy.deepcopy(record['observation']);questions=[]
    for path,item in state.items():
        value=item['value'] if item['status']=='resolved' else None
        if item['status']=='conflict':questions.append(LABELS[path]+'与已有资料冲突；请明确说“更正”或在高级面板确认。')
        if path=='position_unit':
            if value and value!=dataset.get('position_unit'):
                if dataset['columns'][0]!='position' or dataset['position_unit']=='pixel':raise ValueError('CSV 列名与新单位冲突；像素不能只改标签变成长度，请提供真实刻度的 CSV')
                dataset.update(position_unit=value,x_mm=[x*observations.UNITS[value] for x in dataset['position']] if value in observations.UNITS else None)
                dataset['questions']=[] if value in observations.UNITS else ['缺少物理长度刻度；不能从像素报告 μm 缝距。']
                dataset['sha256']=digest({k:v for k,v in dataset.items() if k!='sha256'})
            if value is None:questions.append('请核对位置单位，当前单位未确认。')
        elif path in LABELS:
            part=path.split('.');container=settings[part[0]] if len(part)==2 else settings;container[part[-1]]=value
    recipe=None
    if proposal['recipe']:
        settings,added,recipe=numerical_recipe(dataset,settings);state.update(added)
    problems,missing=inference.issues(dataset,settings)
    return {'settings':settings,'facts':state,'dataset':dataset,'questions':questions+problems,'missing':missing,'changes':changes,'recipe':recipe,'focus':proposal['focus']}


def request(store,s,data):
    text=data.get('text','')
    if not isinstance(text,str) or not 1<=len(text)<=6000:raise WorkflowError('请填写已知条件或本次结果的问题')
    from ..workflow_model import wire
    if wire.credential_risk(text):raise WorkflowError('请勿发送密钥')
    from .inference_report import view
    from ..product_phase import json_payload
    prompt='''整理一维双缝数据任务，只返回 JSON：{"updates":[{"field":"fixed.wavelength_nm","value":633,"quote":"波长633nm","correction":false}],"recipe":"training_scale_v1","focus":"overview"}。
仅提议本轮原文明确给出的字段变化，quote 必须逐字引用包含字段含义的短句，数值转换到字段单位。不能借屏幕距离填焦距，不能从同相以外猜相位0，不能猜测量平面。未知值为null；明确更正或撤回才correction=true。补充缺项不重复/清空已有字段。没有新条件时updates=[]，尤其解释结果时不要重写设置。
可用字段 fixed.wavelength_nm(nm),fixed.focal_length_mm(mm),fixed.slit_width_um(um),fixed.relative_phase_rad(rad),fixed.measurement_plane(FOURIER_FOCAL_PLANE或NEAR_FIELD),position_unit(mm/um/m/pixel),bounds.slit_separation_um([下界,上界],um),bounds.center_shift_mm(mm范围),bounds.amplitude(范围),bounds.background(范围),loss(linear或soft_l1),f_scale。
用户需要整理拟合配置且配置不全时 recipe="training_scale_v1"，否则null。配方由程序给数值，只补数值配置，不补实验事实。focus只能为overview,parameters,residuals,outliers,limitations,next_step，选最适合本轮问题的一个。不要回答额外数值、改善比例、仪器故障、置信百分比或批准计算。'''
    client=store._model(s,data)
    try:
        answer=client.complete('observation-wizard-'+s['id']+'-'+str(s['model_calls']),json_payload(prompt,{'question':text,'current_record':view(s),'field_state':facts(s),'allowed_fields':LABELS}))
        store.event(s,'OBSERVATION_WIZARD_RESPONSE',{'response':answer,'public_input':text})
        proposal=json.loads(answer['assistant']['content']);draft=apply_proposal(s,text,proposal)
    except Exception as exc:
        s['fit_ai_guidance']={'status':'NEEDS_REVIEW','text':'本次建议未通过来源核对或未完整返回；原条件保留，可补充更明确的原话或使用高级面板。','error_type':type(exc).__name__}
        store.save(s);store.event(s,'OBSERVATION_WIZARD_REJECTED',{'error_type':type(exc).__name__,'automatic_retry':False});return s
    changed=not equal(s.get('fit_settings') or {},draft['settings']) or s['observation']['sha256']!=draft['dataset']['sha256'] or bool(draft['changes'])
    if changed and (s.get('fit_approved_sha256') or s.get('fit_result')):
        from .observation_workflow import action
        s=action(store,s,{'type':'fit_revise'})
    if changed or not (s.get('fit_approved_sha256') or s.get('fit_result')):
        s.update(observation=draft['dataset'],fit_settings=draft['settings'],observation_facts=draft['facts'],questions=draft['questions'],missing_fields=draft['missing'],fit_plan=None,status='NEEDS_INFORMATION')
        if draft['recipe']:s['numerical_recipe']=draft['recipe']
        if not draft['questions']:s.update(fit_plan=inference.plan(s['observation'],s['fit_settings']),status='PLANNED')
        store.event(s,'OBSERVATION_SOURCE_UPDATE',{'text':text,'text_sha256':digest(text),'changes':draft['changes'],'numerical_recipe':draft['recipe'],'new_computation':False})
    from .inference_report import explanation
    s['fit_ai_guidance']={'status':'ACCEPTED','focus':draft['focus'],'text':explanation(s,draft['focus']),
                         'basis':'AI 选择本轮原文中的字段和解释焦点；字段须通过出处检查，数值与解释由当前记录生成。不是 AI 优势评分。'}
    store.save(s);return s
