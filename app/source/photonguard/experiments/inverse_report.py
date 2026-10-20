"""One public projection for UI/AI/export; descriptions derive from saved numbers."""
import copy
import csv
import html
import io
import json
import re
from ..core import digest
from ..workflow import WorkflowError
from . import inverse_models as models

FOCI=('overview','parameters','residuals','limitations','measurement','forward')


def explain(s,focus='overview'):
    r=s.get('inverse_result');n=len(s['groups'])
    if s['inverse_settings']['model']==models.FILM:
        return f'本版本含 {n} 组已校准反射率。已知实折射率、法向入射、无损单层，只估计厚度。'+(f'保留 {len(r.get("modes",[]))} 个有限厚度候选；单波长周期歧义及失败区间保留。'+','.join(r['warnings']) if r else '尚未批准计算。')+' 所有观测用于拟合，尚无独立验证。T=1-R 不作为第二份证据；不证明唯一性或置信区间。'
    prefix=f'本版本含 {n} 次采集。各次原 CSV 保留；每五个点留出一个，留出不参与起点选择，仍属于同一扫描。'
    if s['inverse_settings']['model']==models.SLIT:prefix+=' 暗纹不够暗不能单独确定真实缝宽或模糊原因；观测方式及独立校准需另行核对。'
    if not r:return prefix+' 尚无拟合结果。先核对已知条件、待估范围、每组权重及坐标配准，再单独批准计算。'
    result=prefix+f' 本次实际残差调用 {r["resources"]["actual_residual_calls"]} 次，完成 {r["resources"]["local_optimizations"]} 个局部起点尝试。'
    if r.get('estimated_parameters'):result+=' 模型估计：'+', '.join(k+'='+format(v,'.7g') for k,v in r['estimated_parameters'].items())+'。'
    result+=' '+('仍需核对：'+', '.join(r['warnings'])+'。' if r['warnings'] else '通过本次局部诊断；不证明真实参数唯一或仪器精度。')
    for key,p in s.get('inverse_profiles',{}).items():
        result+=f' {key}：保留 {sum(len(v) for v in p["components"])} 个离散格点、{len(p["components"])} 个分离片段，网格间隔 {p["grid_spacing"]:.6g}；不是置信区间，失败点未排除。'
    if focus=='measurement':result+=' 补采按研究目标比较有限模板的局部预测尺度、候选分歧及成本；允许声明的亮度/背景与配准变化。推荐不读取隐藏教学真值，预测尺度不是置信区间。加入后的补采是训练资料，不再是独立验证。'
    if focus=='measurement' and s.get('measurement_plan',{}).get('selection_reason'):result+=' 方案取舍：'+str(s['measurement_plan']['selection_reason'])+'。基础方案也是合法选择。'
    if focus=='residuals':
        result+=' '+('; '.join(f'采集 {i+1}：训练 RMSE {d["training_rmse"]:.6g}，留出 RMSE {d["holdout_rmse"]:.6g}' for i,d in enumerate(r.get('data',[]))))+'；未清洗或删除异常点。'
    if s['inverse_settings']['model']==models.GAUSSIAN:result+=' 假设 M²=1、1/e² 强度半径、自由传播；透镜输入坐标必须为拟合 z0 减去透镜全局位置。'
    if s['inverse_settings']['model']==models.SLIT:result+=' 本模型的低残差不能排除未核验的像素或窗口强度平均、配准及曝光影响；暗纹不够暗不能单独确定真实缝宽或模糊原因。'
    return result


def view(s):
    from .observation_group import can_adopt
    from . import research_actions
    from .task_view import summary as task_summary
    datasets=[]
    for g in s['groups']:
        ds=g['dataset'];datasets.append({k:ds.get(k) for k in ('rows','source_kind','source_name','sha256','raw_sha256','columns','conversion','questions')}|
             {'range_mm':[ds['x_mm'][0],ds['x_mm'][-1]] if ds.get('x_mm') else None,'wavelength_range_nm':[ds['x_nm'][0],ds['x_nm'][-1]] if ds.get('x_nm') else None,'conditions':g['conditions'],'approved':g['approved'],'scale':g['scale'],'scale_source':g['scale_source'],
              'observation':g.get('observation',{'kind':'UNKNOWN'}),'noise':g.get('noise')})
    r=s.get('inverse_result')
    return {'kind':'inverse','task_summary':task_summary(s),'datasets':datasets,'settings':s['inverse_settings'],'parameter_sources':s.get('parameter_sources'),
            'research_input_binding':research_actions.binding(s),'acquisition_constraints':s.get('acquisition_constraints',{}),
            'observation_metadata':s.get('observation_metadata'),
            'decision_preferences':s.get('decision_preferences'),'contrast_calibration':s.get('contrast_calibration'),
            'research_origin':s.get('research_origin'),
            'research_actions':s.get('research_actions'),'research_actions_current':research_actions.current(s),
            'research_goal':s.get('research_goal',{'target':'balanced','source':'DEFAULT_BALANCED'}),
            'acquisition_comparison':{'expected':s.get('acquisition_expectation'),'actual':{'estimated_parameters':r.get('estimated_parameters'),'warnings':r['warnings'],'holdout_rmse':[d['holdout_rmse'] for d in r.get('data',[])]} if r else None,'note':'预期尺度与实际结果分开；参数变化不是误差变化，补采拟合残差不是独立验证。'},
            'estimated_parameters':r.get('estimated_parameters') if r else None,'warnings':r['warnings'] if r else [],
            'profiles':{k:{'components':p['components'],'grid_spacing':p['grid_spacing'],'warnings':p['warnings'],'note':p['note']} for k,p in s.get('inverse_profiles',{}).items()},
            'can_adopt':can_adopt(s),'explanation':explain(s,s.get('inverse_ai',{}).get('focus','overview')),
            'scope':'MODEL_ESTIMATE；模型内有限搜索，不是全局唯一性、严格置信区间或实测精度保证',
            'measurement_plan':{k:v for k,v in s.get('measurement_plan',{}).items() if k not in ('candidate_parameters','plans')}|
                {'plans':[{k:v for k,v in p.items() if k not in ('prediction_x_mm','prediction_envelope')} for p in s.get('measurement_plan',{}).get('plans',[])]}}


def grounded(field,value,quote,text):
    from . import observation_dialogue as old
    from .fact_state import equal
    if field in old.LABELS:return old.grounded(field,value,quote,text)
    if not isinstance(quote,str) or not quote or quote not in text:raise ValueError('新字段需要明确原文出处')
    at=text.index(quote);clause=re.split(r'[，,。；;\n]',text[:at])[-1]+quote+re.split(r'[，,。；;\n]',text[at+len(quote):])[0]
    if field=='design.wavelengths_nm':
        if not isinstance(value,list) or not 2<=len(value)<=9 or any(not models.finite(v) or not 500<=v<=2000 for v in value) or len(set(value))!=len(value):raise ValueError('仅支持 2–9 个明确可用波长')
        if re.search(r'如果|假设|例如|比如|是否|未知|不确定|不是|不可用|没有',clause) or not re.search(r'只有|仅有|可用|拥有|光源|目录|波长列表',clause):raise ValueError('可用波长目录需要明确资源原话')
        pattern=r'('+old.NUM+r'(?:\s*[、,，/]\s*'+old.NUM+r')*)\s*(nm|纳米|um|微米|μm|µm)'
        found=[]
        for match in re.finditer(pattern,quote,re.I):
            factor=1 if match[2] in ('nm','纳米') else 1000
            found.extend(float(v)*factor for v in re.findall(old.NUM,match[1]))
        if equal(value,found):return
        raise ValueError('波长目录、数量或单位与原话不符；不能增加波长')
    if re.search(r'如果|假设|例如|比如|是否|未知|不确定|不是|不要|\?|？',clause):raise ValueError('假设或否定语句不是物理事实')
    if field=='goal.target':
        aliases={'width':'缝宽','separation':'缝距|间距','balanced':'平衡|兼顾','prediction':'预测','waist_radius':'束腰半径','waist_position':'束腰位置'}
        if value in aliases and re.search(aliases[value],quote) and re.search('优先|重点|目标|平衡|兼顾|关注|预测|更重要',quote):return
        raise ValueError('研究目标需要本轮明确原话')
    if field.startswith('design.'):
        key=field.split('.')[1]
        if key=='points' and type(value) is int and 3<=value<=201 and re.search(r'(?<![\d.])'+str(value)+r'\s*(?:(?:个)?(?:点|位置)|次(?:测量|观测)(?:机会)?)',quote):return
        if key=='max_abs_x_mm' and m_finite_positive(value):
            match=re.search(r'(?:范围|绝对位置|正负|±)\s*([\d.]+)\s*(mm|毫米)',quote)
            if match and float(match[1])==value:return
        raise ValueError('补采约束需要明确数量和单位')
    if field.startswith('fixed.') and field[6:] in ('film_index','incident_index','substrate_index','incidence_deg','lossless','layer_order','calibrated_reflectance'):
        key=field[6:]
        if key=='calibrated_reflectance' and value is True and re.search(r'已校准(?:的)?反射率|反射率已(?:经)?校准',quote) and not re.search('未校准|没有校准|未完成|只是亮度',clause):return
        if key=='lossless' and value is True and re.search('无损|无吸收',quote):return
        if key=='layer_order' and value=='incident/film/substrate' and re.search(r'入射介质\s*[/→、]\s*薄膜\s*[/→、]\s*基底',quote):return
        if key=='incidence_deg' and models.finite(value) and value==0 and re.search(r'法向入射|正入射|入射角\s*(?:为|是|=)?\s*0\s*(?:度|°|deg)',quote):return
        aliases={'film_index':r'(?:薄膜|膜层)(?:实)?折射率|薄膜n','incident_index':r'入射(?:介质)?(?:实)?折射率','substrate_index':r'基底(?:实)?折射率'}
        if key in aliases and models.finite(value) and 1<=value<=4 and not re.search(r'估计|拟合|待反演|虚部|吸收|\d\s*[ij]|\d\s*(?:nm|um|mm|微米|纳米|毫米|%|到|至|~)',quote):
            for match in re.finditer('(?:'+aliases[key]+')'+old.SEP+'('+old.NUM+')(?![\\d.])',quote,re.I):
                if equal(value,float(match[1])):return
        raise ValueError('薄膜条件需明确已知实折射率、层序、法向入射、无损及已校准反射率；不能把亮度当反射率')
    if field=='bounds.thickness_nm':
        pattern=r'(?:膜厚|厚度)'+old.SEP+'('+old.NUM+r')\s*('+old.UNIT+r')?\s*(?:到|至|~|～|—|–|-)\s*('+old.NUM+r')\s*('+old.UNIT+')'
        for match in re.finditer(pattern,quote,re.I):
            a,ua,b,ub=match.groups()
            if ua and ua!=ub or ub not in old.SCALE:continue
            values=[float(v)*old.SCALE[ub]/1e-6 for v in (a,b)]
            if equal(value,values) and 0<=values[0]<values[1]<=2000 and values[1]-values[0]<=1000:return
        raise ValueError('厚度只接受明确有限范围与单位，不反演折射率、吸收或增益')
    if field=='fixed.m2' and type(value) in (int,float) and value==1 and re.search(r'M[²2]\s*(?:=|为|是)?\s*1(?![\d.])',quote,re.I):return
    if field=='fixed.propagation' and value=='FREE_SPACE' and '自由传播' in quote:return
    aliases={'slit_width_um':'缝宽','slit_separation_um':'缝距','center_shift_mm':'中心(?:偏移|平移)',
             'amplitude':'幅度','background':'背景','waist_radius_um':'束腰半径','waist_z_mm':'束腰位置'}
    if '.' not in field:raise ValueError('不支持的字段')
    role,key=field.split('.');alias=aliases.get(key)
    if role not in ('fixed','bounds') or not alias:raise ValueError('不支持的参数角色')
    pattern='(?:'+alias+')'+old.SEP+'('+old.NUM+')'
    if role=='bounds':pattern+=r'\s*('+old.UNIT+r')?\s*(?:到|至|~|～|—|–|-)\s*('+old.NUM+')'
    pattern+=r'\s*('+old.UNIT+')?'
    for m in re.finditer(pattern,quote,re.I):
        if role=='bounds':a,ua,b,ub=m.groups();vals=[float(a),float(b)];unit=ub or ua
        else:a,unit=m.groups();vals=[float(a)];ua=ub=None
        if ua and ub and ua!=ub:continue
        if key.endswith(('_um','_mm')):
            if unit not in old.SCALE:continue
            vals=[v*old.SCALE[unit]/(.001 if key.endswith('_um') else 1.) for v in vals]
        elif unit:continue
        if equal(value,vals if role=='bounds' else vals[0]):return
    raise ValueError('参数、角色、单位或数值与原话不符')


def m_finite_positive(value):return models.finite(value) and 0<value<=500


def guidance(store,s,data):
    from .research_advice import guide
    return guide(store,s,data)


def legacy_guidance(store,s,data):
    """Historical v1 receiver kept for reproducibility, never used by the UI/API."""
    text=data.get('text','')
    if not isinstance(text,str) or not 1<=len(text)<=6000:raise WorkflowError('请填写本次问题或条件')
    from ..workflow_model import wire
    if wire.credential_risk(text):raise WorkflowError('请勿发送密钥')
    from ..product_phase import json_payload
    from . import research_actions as actions
    cfg=s['inverse_settings'];allowed=[f for f in actions.fact_fields(s) if not f.startswith('observation.')]
    prompt='''你帮助用户组织反向光学研究。仅返回 JSON {"updates":[{"field":"字段","value":数值或两端范围或字符串,"quote":"本轮逐字原话","correction":false}],"focus":"overview","research_actions":{"input_binding":完整复制本轮research_input_binding,"actions":[{"type":"explain","reason":"简短研究理由，不宣告未核验的物理结论","proposal_id":null,"fact_fields":[],"quote":"本轮逐字原话，或空字符串"}]}}。
只修改本轮用户明确给出的条件。未提供的数值不填。解释结果时 updates=[]。fixed 是用户已知值，bounds 是用户允许估计的范围，不能同时设置。不得把已知量自动改成待估量。替换已有值须原话明确“更正”，correction=true。参数用字段单位。字符串枚举：fixed.propagation 的自由传播是 FREE_SPACE；fixed.measurement_plane 的透镜傅里叶焦平面是 FOURIER_FOCAL_PLANE。只使用 allowed_fields，focus 可为 overview/parameters/residuals/limitations/measurement/forward。不执行计算、补采或批准。不能输出95%置信、精度保证、全球唯一、隐藏真值或未来观测。'''
    prompt+=' 研究目标用 goal.target：缝宽优先 width、缝距优先 separation、平衡 balanced、束腰半径优先 waist_radius、束腰位置优先 waist_position。只修改目标时不得修改物理参数。design.points 是新增测量点数/位置数（5次测量机会对应5点，不是5轮拟合）；design.max_abs_x_mm 是最大绝对坐标（mm），都须逐字来源。不得改变累计额度。'
    prompt+=' 可提出1至4项并列的合理研究路径；不存在唯一标准动作。动作包括 clarify_fact、compare_acquisition、choose_baseline、inspect_observation、request_calibration、refit、propose_followup、explain、stop。reason解释与本轮需求和公开证据的联系。proposal_id只能引用record.measurement_plan已有计划id；没有具体方案时填null并提出待核对步骤。fact_fields可用action_fact_fields。选简单基础方案不算失败。不得把暗纹、低残差或局部通过解释为确诊模糊或真实参数；可以请求核对独立校准。动作只建议，独立操作员批准另行进行。'
    prompt+=' 所有quote（包括研究动作的quote）只能是本轮question字段内的逐字子串，不能引用record中的解释、历史用户原话、旧目标标签或历史AI建议。reason可以依据已保存记录进行推理；如果本轮question没有适合该动作的逐字出处，动作quote必须填空字符串。不得为凑引用改写question。'
    prompt+=' 两种对象结构不要混用：correction只属于updates里的条件更新；每个研究actions对象只能有type、reason、proposal_id、fact_fields、quote五个键，不得添加correction或approve。'
    if cfg['model']==models.FILM:
        prompt+=' 本单膜仅支持已知实折射率、法向入射、无损、入射介质/薄膜/基底的层序以及已校准反射率，只估厚度。未声明的物理条件不可补。fixed.layer_order枚举incident/film/substrate。bounds.thickness_nm明确厚度范围；design.wavelengths_nm是用户逐字明确可用的完整波长目录（nm），不能补入目录外波长。不能把任意亮度改称已校准反射率，不拟合n、吸收、增益、背景。解释已有多解时updates=[]。'
    client=store._model(s,data)
    input_binding=actions.binding(s)
    try:
        answer=client.complete('inverse-ai-'+s['id']+'-'+str(s['model_calls']),json_payload(prompt,{'question':text,'record':view(s),'research_input_binding':input_binding,'allowed_fields':allowed,'action_fact_fields':actions.fact_fields(s)}))
        store.event(s,'INVERSE_AI_RESPONSE',{'response':answer,'public_input':text})
        obj=json.loads(answer['assistant']['content'])
        if not isinstance(obj,dict) or set(obj) not in ({'updates','focus'},{'updates','focus','research_actions'}) or obj['focus'] not in FOCI or not isinstance(obj['updates'],list) or len(obj['updates'])>20:raise ValueError('回复结构不符')
        bundle=None
        if 'research_actions' in obj:
            from .observation_group import root_record
            bundle=actions.validate(s,obj['research_actions'],text,input_binding,ledger=root_record(store,s)['inverse_ledger'])
        changed=copy.deepcopy(cfg);evidence=[];seen=set();newgoal=copy.deepcopy(s.get('research_goal'));design=copy.deepcopy(s.get('acquisition_constraints',{}))
        for op in obj['updates']:
            if not isinstance(op,dict) or set(op)!={'field','value','quote','correction'} or type(op['correction']) is not bool or op['field'] not in allowed or op['field'] in seen:raise ValueError('字段格式或范围不符')
            field=op['field'];seen.add(field)
            # Exact spelling aliases only; still require physical meaning in the user's quote.
            if field=='fixed.propagation' and op['value']=='自由传播':op={**op,'value':'FREE_SPACE'}
            if field=='fixed.measurement_plane' and op['value'] in ('透镜焦平面','傅里叶焦平面'):op={**op,'value':'FOURIER_FOCAL_PLANE'}
            grounded(field,op['value'],op['quote'],text);role,key=field.split('.')
            if role in ('goal','design'):
                if role=='goal':
                    from .goal_design import goal
                    newgoal=goal(cfg['model'],{**(newgoal or {}),'target':op['value'],'source':'USER_TEXT'})
                else:
                    if key=='points' and cfg['model']==models.SLIT and op['value']<20:raise ValueError('当前双缝补采至少需要20点；测量机会不足应澄清或停止，不扩大额度')
                    design[key]=op['value']
                evidence.append({'field':field,'value':op['value'],'quote':op['quote'],'text_sha256':digest(text),'source_kind':'USER_TEXT'});continue
            other='bounds' if role=='fixed' else 'fixed';existing=key in changed.get(role,{}) or key in changed.get(other,{})
            same=changed.get(role,{}).get(key)==op['value'] and key not in changed.get(other,{})
            if existing and not same and not (op['correction'] and re.search('更正|改为|改成',text)):raise ValueError('已有事实发生冲突，请明确更正')
            changed.setdefault(role,{})[key]=copy.deepcopy(op['value']);changed.setdefault(other,{}).pop(key,None)
            evidence.append({'field':field,'value':op['value'],'quote':op['quote'],'text_sha256':digest(text),'source_kind':'USER_TEXT'})
        facts_changed=changed!=cfg
        planning_changed=facts_changed or newgoal!=s.get('research_goal') or design!=s.get('acquisition_constraints',{})
        if planning_changed and s.get('measurement_plan'):
            s.setdefault('measurement_history',[]).append(s.pop('measurement_plan'))
        archived_proposals=copy.deepcopy(s.get('measurement_history',[]))
        if facts_changed:
            if s.get('inverse_approved_sha256') or s.get('inverse_result'):
                from .observation_group import revise
                s=revise(store,s)
                if archived_proposals:s['measurement_history']=archived_proposals
            s.update(inverse_settings=changed,inverse_plan=None,status='DRAFT',questions=['AI 草稿尚未批准；请分别核对每次采集条件及待估范围。'])
            s.setdefault('parameter_sources',{})['latest_text_evidence']=evidence
        if newgoal:s['research_goal']=newgoal
        if design:s['acquisition_constraints']=design
        if evidence:s.setdefault('parameter_sources',{})['latest_text_evidence']=evidence
        if bundle:s['research_actions']=actions.rebind(bundle,s)
        s['inverse_ai']={'status':'ACCEPTED','focus':obj['focus'],'updates':evidence,'text':explain(s,obj['focus'])+(' 当前研究目标：'+newgoal['target']+'；尚未批准补采。' if newgoal else '')}
        if bundle:s['inverse_ai']['research_actions_sha256']=s['research_actions']['sha256']
    except Exception as exc:
        if s.get('research_actions'):s.setdefault('research_actions_history',[]).append(s.pop('research_actions'))
        s['inverse_ai']={'status':'NEEDS_REVIEW','focus':'limitations','text':'本次 AI 回复未通过来源或格式核对；原资料保持，未计算、补采或重试。'}
        store.event(s,'INVERSE_AI_FAILED',{'error_type':type(exc).__name__})
    store.save(s);return s


def table(s):
    if not s.get('inverse_result',{}).get('data'):raise WorkflowError('尚无拟合数组')
    out=io.StringIO();writer=csv.writer(out);writer.writerow(['dataset_index','wavelength_nm' if s['inverse_settings']['model']==models.FILM else 'x_mm','observed','predicted','residual','holdout'])
    for j,d in enumerate(s['inverse_result']['data']):
        writer.writerows([j,*r] for r in zip(d['x'],d['observed'],d['predicted'],d['residual'],d['holdout']))
    return out.getvalue().encode('utf-8-sig')


def summary(s):
    v=view(s);task=v['task_summary']
    from .task_view import chart_svg
    primary=(task['advice'].get('primary') or {})
    blocked=task['advice'].get('blocked_primary');availability=''
    if blocked:
        numbers='；'.join(f'{v["label"]}：{v["value"]} {v["unit"]}' for v in blocked['measurements']+blocked['declared_limits'])
        availability='<h3>这项主建议当前不能准备</h3><p>'+html.escape(blocked['reason'])+'</p><p>'+html.escape(numbers)+'</p><p>'+html.escape(task['advice']['feasible_alternatives_note'])+'</p><ul>'+''.join('<li>'+html.escape(p['label']+' · 程序列出的可行备选')+'</li>' for p in task['advice']['feasible_alternatives'])+'</ul>'
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>研究任务结果</title>'
        '<style>body{font:16px/1.65 system-ui;max-width:920px;margin:32px auto;padding:0 20px;color:#183730}svg{width:100%;height:auto}svg text{font-size:11px}pre{white-space:pre-wrap;overflow-wrap:anywhere}h2{font-size:24px}</style>'
        '<h1>'+html.escape(task['goal'])+'</h1><p>'+html.escape(task['source_label'])+'</p><h2>'+html.escape(task['headline'])+'</h2>'+chart_svg(task['chart'])+
        '<p>'+html.escape(task['change'])+'</p><p>'+html.escape('；'.join(task['warnings']))+'</p><p>'+html.escape(task['scope'])+'</p>'+
        ('<p>'+html.escape(task['pause_reason'])+'</p>' if task['pause_reason'] else '')+
        '<h2>下一步</h2><p>'+html.escape(task['advice']['message'])+'</p><p>'+html.escape(primary.get('label','可调整研究目标或补充资料'))+'</p><p>'+html.escape(primary.get('reason',''))+'</p>'+availability+
        '<details><summary>完整记录与依据</summary><pre>'+html.escape(json.dumps(v,ensure_ascii=False,indent=2))+'</pre></details></html>').encode()
