"""Bounded research suggestions. No action here approves or dispatches a solver."""
import copy
import re
from ..core import digest

TYPES=('clarify_fact','compare_acquisition','choose_baseline','inspect_observation',
       'request_calibration','refit','propose_followup','explain','stop')
PREFERENCE_FIELDS=('preference.mode','preference.protected_parameter','preference.max_travel_mm')
LABELS=dict(zip(TYPES,('补充事实','比较补采方案','采用基础方案','核对观测条件','索取校准资料',
                      '准备重新分析','准备后续观测','解释现有证据','停止当前分支')))
NOTES={
    'clarify_fact':'补充缺少的事实后再核对计划；不自动填入条件。',
    'compare_acquisition':'使用当前目标与允许的资源比较有限方案；指标是预测，不保证实际误差。',
    'choose_baseline':'基础方案是合法研究选择；生成并核对具体计划后仍须单独批准。',
    'inspect_observation':'核对点采样、强度平均、坐标、配准和曝光记录；低残差不能排除未建模因素。',
    'request_calibration':'请求独立校准资料；未收到资料不假定校准存在，也不确诊模糊原因。',
    'refit':'核对同一根任务的剩余额度与数据条件，再单独生成和批准计算计划。',
    'propose_followup':'仅准备有限后续观测；不控制仪器，不自动生成教学数据。',
    'explain':'只解释当前公开资料；参数变化不是误差变化，局部通过不是唯一性证明。',
    'stop':'结束当前研究分支；原始资料、失败和累计额度保留。',
}


def state(s):
    """Public facts only: no hidden object, raw observations, API key, or truth."""
    result={'record_id':s['id'],'settings':s['inverse_settings'],
            'groups':[{'dataset_sha256':g['dataset']['sha256'],'conditions':g.get('conditions'),
                       'scale':g.get('scale'),'scale_source':g.get('scale_source'),
                       'noise':g.get('noise'),
                       'approved':g.get('approved'),'observation':g.get('observation',g['dataset'].get('observation'))}
                      for g in s.get('groups',[])],
            'goal':s.get('research_goal'),'constraints':s.get('acquisition_constraints'),
            'observation_metadata':s.get('observation_metadata'),
            'fit_result_id':(s.get('inverse_result') or {}).get('id'),
            'profile_ids':{k:v.get('id') for k,v in s.get('inverse_profiles',{}).items()},
            'proposal_sha256':(s.get('measurement_plan') or {}).get('sha256')}
    for key in ('decision_preferences','contrast_calibration'):
        if key in s:result[key]=s[key]
    return result


def binding(s):
    p=state(s)
    return {'record_id':s['id'],'input_revision':s['revision'],'facts_sha256':digest(p),
            'fit_result_id':p['fit_result_id'],'proposal_sha256':p['proposal_sha256']}


def proposal_availability(s):
    """Project the saved plan's decision, without rescoring or relaxing it."""
    plan=s.get('measurement_plan') or {};feasible=[];blocked=[]
    prefs=plan.get('decision_preferences') or {};constraints=plan.get('constraints') or {}
    limits=[{'label':label,'value':obj[key],'unit':unit} for obj,key,label,unit in (
        (prefs,'max_travel_mm','最大移动行程','mm'),(prefs,'max_points','取舍设置点数上限','点'),
        (constraints,'points','本次声明点数','点'),(constraints,'max_abs_x_mm','最大绝对位置','mm')) if obj.get(key) is not None]
    for p in plan.get('plans',[]):
        if p.get('execution_allowed') is not False:feasible.append(p['id']);continue
        cost=p.get('cost') or {}
        blocked.append({'id':p['id'],'reason':p.get('selection_reason') or '当前保存计划标记为不可执行，请核对限制。',
            'measurements':[{'label':label,'value':cost[key],'unit':unit} for key,label,unit in (
                ('travel_mm','移动行程','mm'),('points','采样点数','点')) if cost.get(key) is not None],
            'declared_limits':copy.deepcopy(limits),'source':'SAVED_PLAN_EXECUTION_FLAG'})
    return {'source':'PROGRAM_SAVED_PLAN_NOT_MODEL_RANKING','input_binding':binding(s),
            'currently_feasible_proposal_ids':feasible,'blocked_proposals':blocked,
            'note':'资格沿用当前保存计划；不表示已经批准、必须补采或能改善真实精度。'}


def fact_fields(s):
    cfg=s['inverse_settings']
    from . import inverse_models as m
    if cfg['model']==m.FILM:
        from .film_inverse import PHYSICS
        fields=['fixed.'+k for k in PHYSICS]+['bounds.thickness_nm','design.wavelengths_nm']
    else:
        physics=('wavelength_nm','focal_length_mm','relative_phase_rad','measurement_plane') if cfg['model']==m.SLIT else ('wavelength_nm','m2','propagation')
        fields=['fixed.'+k for k in physics]+[role+'.'+k for k in m.parameters(cfg['model']) for role in ('fixed','bounds')]
        fields+=['goal.target','design.points','design.max_abs_x_mm',*PREFERENCE_FIELDS]
    return fields+['observation.sampling','observation.calibration','observation.registration','observation.exposure','observation.noise']


def baseline_ids(s):
    p=s.get('measurement_plan') or {};ids=set()
    explicit_catalog='baseline_id' in p or 'baseline_catalog' in p
    if isinstance(p.get('baseline_id'),str):ids.add(p['baseline_id'])
    for item in p.get('plans',[]):
        legacy=not explicit_catalog and not item.get('role') and not item.get('identity') and item.get('id') in ('repeat','fixed_extension','fixed2','fixed_2mm')
        if item.get('is_baseline') or item.get('role')=='BASELINE' or item.get('identity')=='BASELINE' or legacy:
            ids.add(item['id'])
    return ids


def _reason_limits(s,reason,text):
    """Reject explicit unsupported conclusions/resources, retain honest caveats."""
    certainty=r'确诊|确定是|已证明|保证.{0,8}(?:精度|正确|唯一)|95\s*%|真实(?:缝宽|厚度|参数)\s*(?:为|是|=)|已排除模糊'
    for clause in re.split(r'[，,。；;\n]',reason):
        for match in re.finditer(certainty,clause):
            if not re.search(r'不能|无法|不|未|没有|不足以|并非|避免|谨防|防止',clause[max(0,match.start()-16):match.start()]):
                raise ValueError('研究理由不能宣告未核验的物理结论')
    catalog=(s.get('acquisition_constraints') or {}).get('wavelengths_nm')
    from .inverse_models import FILM
    if s['inverse_settings']['model']==FILM:
        from .inverse_report import grounded
        # A fresh explicit list may replace the earlier list in the same reply.
        explicit=re.search(r'(?:只有|仅有|可用|拥有|光源目录)[^。；;\n]*',text)
        if explicit:
            quote=explicit[0];values=[]
            for match in re.finditer(r'(\d+(?:\.\d+)?(?:\s*[、,，/]\s*\d+(?:\.\d+)?)*)\s*(nm|纳米)',quote):
                values.extend(float(v) for v in re.findall(r'\d+(?:\.\d+)?',match[1]))
            try:grounded('design.wavelengths_nm',values,quote,text)
            except ValueError:pass
            else:catalog=values
        if catalog:
            requested=re.findall(r'(?:补测|采集|测量|新增|增加|使用)\s*(\d+(?:\.\d+)?)\s*(?:nm|纳米)',reason)
            if any(float(w) not in catalog for w in requested):raise ValueError('研究步骤不得要求可用目录外波长')


def validate(s,payload,text,input_binding=None,*,source='LIVE_AI',ledger=None):
    """Validate choices against the *input*; callers rebind after accepted drafts.

    Model output: {input_binding: <copied input>, actions: [{type, reason,
    proposal_id: null|saved ID, fact_fields: [...], quote: verbatim text|""}]}.
    Multiple sensible choices are allowed. No expected/unique answer is supplied.
    """
    expected=input_binding or binding(s)
    if not isinstance(payload,dict) or set(payload)!={'input_binding','actions'} or payload['input_binding']!=expected:
        raise ValueError('研究建议未绑定本次版本、事实与真实结果')
    actions=payload['actions']
    if not isinstance(actions,list) or not 1<=len(actions)<=4:raise ValueError('研究建议必须为 1–4 个有限步骤')
    proposal=s.get('measurement_plan') or {};available={p['id'] for p in proposal.get('plans',[])}
    seen=set();validated=[]
    for item in actions:
        if not isinstance(item,dict) or set(item)!={'type','reason','proposal_id','fact_fields','quote'}:raise ValueError('研究步骤字段无效')
        kind=item['type'];reason=item['reason'];fields=item['fact_fields'];quote=item['quote'];pid=item['proposal_id']
        if kind not in TYPES or kind in seen:raise ValueError('研究步骤未知或重复')
        if not isinstance(reason,str) or not 1<=len(reason)<=500:raise ValueError('研究步骤需要简短理由')
        # Reasons organize work, not a second unverified scientific-result channel.
        _reason_limits(s,reason,text)
        if not isinstance(quote,str) or len(quote)>1000 or quote and quote not in text:raise ValueError('研究步骤引用不是本轮原话')
        if not isinstance(fields,list) or len(fields)>8 or any(f not in fact_fields(s) for f in fields) or len(set(fields))!=len(fields):raise ValueError('研究步骤引用了不支持的事实')
        if pid is not None and (not isinstance(pid,str) or pid not in available):raise ValueError('研究步骤引用了不存在的方案')
        if kind=='choose_baseline' and pid is not None and pid not in baseline_ids(s):raise ValueError('局部推荐不能伪装成基础方案')
        needs=[]
        if kind=='refit' and not all(g.get('approved') for g in s.get('groups',[])):needs.append('OBSERVATION_REVIEW')
        if kind in ('compare_acquisition','choose_baseline','propose_followup') and not s.get('inverse_result'):needs.append('FIT_RESULT')
        if kind in ('choose_baseline','propose_followup') and pid is None:needs.append('SAVED_EXECUTABLE_PROPOSAL')
        if kind in ('compare_acquisition','choose_baseline','propose_followup') and not s.get('acquisition_constraints'):needs.append('DECLARED_ACQUISITION_CONSTRAINTS')
        if ledger:
            key,cap=('fit_runs_reserved','max_fit_runs') if kind=='refit' else ('acquisitions_reserved','max_acquisitions')
            if kind in ('refit','propose_followup') and ledger.get(key,0)>=ledger.get(cap,0):needs.append('ROOT_BUDGET_EXHAUSTED')
        entry=copy.deepcopy(item)|{'label':LABELS[kind],'note':NOTES[kind],
            'status':'NEEDS_REVIEW' if needs else 'SUGGESTED_ONLY','required_before_execution':needs,
            'approval':False,'executed':False}
        entry['id']=digest({'binding':expected,'action':item});validated.append(entry);seen.add(kind)
    result={'schema':'photonguard.research-actions.v1','source_kind':source,'input_binding':copy.deepcopy(expected),
            'state_binding':state(s),'actions':validated,'approval':False,'executed':False,
            'note':'仅为研究步骤建议；由独立操作员核对，现有计划与批准合同仍适用。'}
    result['sha256']=digest(result);return result


def rebind(bundle,s):
    """Accepted source-bound draft changes keep original model input for audit."""
    result=copy.deepcopy(bundle);result['state_binding']=state(s)
    # A goal/fact change archives its proposal; never carry an old chosen plan forward.
    ids={p['id'] for p in (s.get('measurement_plan') or {}).get('plans',[])}
    for item in result['actions']:
        # Source-bound fact updates may create a fresh draft with no result.
        # Rebinding an old input must not carry its satisfied prerequisites over.
        kind=item['type'];pid=item['proposal_id']
        needs=[v for v in item['required_before_execution'] if v=='ROOT_BUDGET_EXHAUSTED']
        if kind=='refit' and not all(g.get('approved') for g in s.get('groups',[])):needs.append('OBSERVATION_REVIEW')
        if kind in ('compare_acquisition','choose_baseline','propose_followup') and not s.get('inverse_result'):needs.append('FIT_RESULT')
        if kind in ('choose_baseline','propose_followup') and (pid is None or pid not in ids):needs.append('SAVED_EXECUTABLE_PROPOSAL')
        if kind in ('compare_acquisition','choose_baseline','propose_followup') and not s.get('acquisition_constraints'):needs.append('DECLARED_ACQUISITION_CONSTRAINTS')
        item['required_before_execution']=needs
        item['status']='NEEDS_REVIEW' if needs else 'SUGGESTED_ONLY'
        if item['proposal_id'] is not None and item['proposal_id'] not in ids:
            item['status']='STALE_PROPOSAL';item['required_before_execution'].append('REGENERATE_PROPOSAL')
    result.pop('sha256',None);result['sha256']=digest(result);return result


def current(s,bundle=None):
    bundle=bundle or s.get('research_actions')
    if bundle and bundle.get('source_kind')=='LIVE_AI' and s.get('inverse_ai',{}).get('status')=='NEEDS_REVIEW':return False
    return bool(bundle and bundle.get('sha256')==digest({k:v for k,v in bundle.items() if k!='sha256'}) and bundle.get('state_binding')==state(s))


def fallback(s,text='',*,ledger=None):
    """Transparent local navigation aid; never presented as a live-model decision."""
    kind='explain';fields=[];reason='离线展示当前资料与可继续的研究步骤。';pid=None
    if re.search('暗纹|不够暗|模糊|平均|像素',text):
        kind='inspect_observation';fields=['observation.sampling','observation.calibration'];reason='先核对观测方式与独立校准；不能由暗纹或低残差确定真实几何。'
    elif re.search('简单|固定扫描|基础方案|基线',text):
        kind='choose_baseline';reason='用户倾向简单方案，先核对基础方案是否满足当前资源与目标。'
        pid=next((p['id'] for p in (s.get('measurement_plan') or {}).get('plans',[]) if p['id'] in baseline_ids(s)),None)
    elif re.search('校准',text):kind='request_calibration';fields=['observation.calibration'];reason='需要独立校准出处，不推断校准已完成。'
    elif not s.get('inverse_settings',{}).get('fixed'):
        kind='clarify_fact';reason='当前已知物理条件未齐全，先核对来源。'
    elif s.get('inverse_result'):
        kind='compare_acquisition';reason='已有分析结果，可核对允许资源后比较基础与有限补采方案。'
    payload={'input_binding':binding(s),'actions':[{'type':kind,'reason':reason,'proposal_id':pid,'fact_fields':fields,'quote':text[:1000]}]}
    return validate(s,payload,text,source='DETERMINISTIC_FALLBACK',ledger=ledger)


def offline(store,s,data):
    from .observation_group import root_record
    from ..workflow import WorkflowError
    text=data.get('text','')
    if not isinstance(text,str) or len(text)>6000:raise WorkflowError('离线研究问题过长')
    from ..workflow_model import wire
    if wire.credential_risk(text):raise WorkflowError('请勿发送密钥')
    s['research_actions']=fallback(s,text,ledger=root_record(store,s)['inverse_ledger'])
    store.event(s,'INVERSE_OFFLINE_RESEARCH_SUGGESTION',{'sha256':s['research_actions']['sha256'],'model_calls':0})
    store.save(s);return s
