"""Versioned effective facts, immutable evidence and explicit corrections."""
import copy,math
from ..core import digest
from .case_catalog import get_case
from .planner import unit_for

def equal(a,b):
    if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,dict) and isinstance(b,dict):return set(a)==set(b) and all(equal(a[k],b[k]) for k in a)
    return a==b

def unit(path,case):
    if path.startswith('parameters.'):return unit_for(path.split('.')[1])
    if path.startswith('recipe.'):return unit_for('thickness_um' if case['recipe']['variable']=='layers' else case['recipe']['variable'] or '')
    if path=='goal.wavelength_um':return 'um'
    if path in ('goal.target','goal.tolerance'):
        metric=case['metrics'][0];return unit_for(metric)
    return 'dimensionless'

def parameter_fields(case):
    fields=set(case['required_parameters'])|set(case['teaching']['parameters'])|set(case['numeric_defaults'])|set(case['fixed_parameters'])
    if case['domain']=='film':
        fields.add('wavelengths_um')
        if case['recipe']['variable']=='layer_count':fields.add('layer_count')
    return fields

def allowed(case):
    return {'parameters.'+k for k in parameter_fields(case)}|{'execution.fast_only'}|{'goal.'+k for k in ('metric','operator','target','tolerance','wavelength_um')}|{'recipe.min','recipe.max','recipe.values'}

def effective_facts(state):
    facts=state.get('facts',{})
    explicit=facts.get('parameters.wavelengths_um',{}).get('status')=='resolved'
    unused={'parameters.scan_min_um','parameters.scan_max_um','parameters.scan_points'}
    return {p:f for p,f in facts.items() if not (explicit and p in unused and f.get('source_kind')=='numeric_default')}

def seed(case_id,mode='specified',parent=None):
    case=get_case(case_id);s={'schema_version':2,'revision':0,'case_id':case_id,'mode':mode,'facts':{},'messages':{},'events':[],'questions':[],'issues':[],'parent':None}
    def add(path,value,kind,locked=False,ref=None):
        ident=digest([case_id,path,value,kind,ref])[:20]
        s['facts'][path]={'fact_id':ident,'field':path,'status':'resolved','value':copy.deepcopy(value),'unit':unit(path,case),'locked':locked,'source_kind':kind,'evidence':[ref] if ref else [],'support_events':[]}
    if mode=='teaching' and not parent:
        for k,v in case['teaching']['parameters'].items():add('parameters.'+k,v,'explicit_teaching')
        for k,v in case['teaching']['goal'].items():add('goal.'+k,v,'explicit_teaching')
        if 'values' in case['teaching']:add('recipe.values',case['teaching']['values'],'explicit_teaching')
        for k,v in case['teaching'].get('bounds',{}).items():add('recipe.'+k,v,'explicit_teaching')
    if parent:
        from .case_adaptation import selected_parameters
        p,w=selected_parameters(parent);ref={'record_id':parent['id'],'result_sha256':digest(parent['result']),'candidate_id':w['id']}
        s['parent']=ref
        if parent['spec']['resource_budget']['max_fdtd']==0:add('execution.fast_only',True,'parent_result',False,ref)
        if case['recipe']['method']=='thickness_catalog' and len(p.get('layers',[]))==1:p={**p,'film_n':p['layers'][0]['n'],'thickness_um':p['layers'][0]['thickness_um']}
        for k,v in p.items():
            if 'parameters.'+k in allowed(case):add('parameters.'+k,v,'parent_result',True,{**ref,'field':'parameters.'+k})
        for k,v in parent['spec']['goal'].items():
            if 'goal.'+k in allowed(case):add('goal.'+k,v,'parent_result',False,{**ref,'field':'goal.'+k})
        if case['recipe']['method'] in ('catalog','thickness_catalog'):
            values=parent['spec']['allowed_variables'].get(case['recipe']['variable'])
            if values is not None:
                if case['recipe']['variable']=='layers':values=[x[0]['thickness_um'] for x in values]
                add('recipe.values',values,'parent_result',False,{**ref,'field':'allowed_variables'})
    for k,v in case['fixed_parameters'].items():
        if 'parameters.'+k not in s['facts']:add('parameters.'+k,v,'case_model',True)
    for k,v in case['numeric_defaults'].items():
        if 'parameters.'+k not in s['facts']:add('parameters.'+k,v,'numeric_default')
    return s

def apply(s,event_id,text,operations,*,base_revision,actor='user_text',message_id=None):
    if actor not in ('user_text','user_form','model_checked'):raise ValueError('Actor is assigned by the application')
    fingerprint=digest({'text':text,'operations':operations,'actor':actor})
    for old in s['events']:
        if old['event_id']==event_id:
            if old['fingerprint']!=fingerprint:raise ValueError('重复事件ID包含不同内容')
            return copy.deepcopy(s)
    if base_revision!=s['revision']:raise ValueError('事实版本已改变，迟到变更不能覆盖当前资料')
    out=copy.deepcopy(s);case=get_case(s['case_id']);mid=message_id or event_id
    if mid in out['messages'] and out['messages'][mid]['text']!=text:raise ValueError('原始消息不可覆盖')
    out['messages'][mid]={'text':text,'sha256':digest(text)};changes=[]
    for op in operations:
        path=op.get('field')
        if path not in allowed(case):raise ValueError('字段不属于当前案例：'+str(path))
        evidence=copy.deepcopy(op.get('evidence',[]))
        if actor!='user_form':
            if not evidence:raise ValueError('字段没有已核对的来源')
            for e in evidence:
                if e.get('message_id')!=mid or type(e.get('start')) is not int or type(e.get('end')) is not int or not 0<=e['start']<e['end']<=len(text):raise ValueError('来源位置无效')
                e['quote']=text[e['start']:e['end']];e['text_sha256']=digest(text)
        old=out['facts'].get(path);value=copy.deepcopy(op.get('value'));unknown=op.get('op') in ('unknown','retract')
        item={'fact_id':digest([event_id,path,value])[:20],'field':path,'status':'retracted' if op.get('op')=='retract' else 'unknown' if unknown else 'resolved','value':value,'unit':op.get('unit',unit(path,case)),'locked':False,'source_kind':actor,'evidence':evidence,'support_events':[event_id]}
        if old and old.get('locked') and (unknown or not equal(old.get('value'),value)):
            item=copy.deepcopy(old);item.update(status='conflict',conflict={'attempted_value':value,'evidence':evidence,'requires_physical_branch':True})
        elif old and old['status']=='resolved' and not unknown and equal(old.get('value'),value):
            item=copy.deepcopy(old);item['evidence']+=evidence;item['support_events'].append(event_id)
        elif old and old['status'] in ('resolved','conflict') and not op.get('correction') and old.get('source_kind') not in ('numeric_default','case_model'):
            item=copy.deepcopy(old);item.update(status='conflict',conflict={'attempted_value':value,'evidence':evidence,'requires_physical_branch':False})
        elif old:item['supersedes']=old['fact_id'];item['locked']=old.get('locked',False)
        out['facts'][path]=item;changes.append({'field':path,'before':old,'after':copy.deepcopy(item)})
    out['revision']+=1;out['events'].append({'event_id':event_id,'fingerprint':fingerprint,'base_revision':base_revision,'message_id':mid,'actor':actor,'operations':copy.deepcopy(operations),'changes':changes})
    return refresh(out)

def undo(s,event_id):
    if any(e['event_id']==event_id for e in s['events']):return copy.deepcopy(s)
    out=copy.deepcopy(s)
    undone={e['reverts'] for e in out['events'] if e.get('kind')=='undo'}
    candidates=[e for e in out['events'] if e.get('message_id') and e['event_id'] not in undone]
    if not candidates:raise ValueError('没有可撤销的执行前资料修改')
    previous=candidates[-1]
    out['ambiguities']=copy.deepcopy(previous.get('ambiguities_before',[]));out['notice']=None;out['proposals']=[]
    for c in reversed(previous['changes']):
        if c['before'] is None:out['facts'].pop(c['field'],None)
        else:out['facts'][c['field']]=copy.deepcopy(c['before'])
    out['events'].append({'event_id':event_id,'kind':'undo','reverts':previous['event_id'],'changes':[]});out['revision']+=1
    return refresh(out)

def refresh(s):
    out=copy.deepcopy(s);case=get_case(s['case_id']);f=out['facts'];required=['parameters.'+k for k in case['required_parameters']]+['goal.metric','goal.operator']
    value=lambda p:f.get(p,{}).get('value') if f.get(p,{}).get('status')=='resolved' else None
    if value('goal.operator') not in ('minimize','maximize'):required+=['goal.target']
    if value('goal.operator')=='near':required+=['goal.tolerance']
    if case['domain']=='film':required+=['goal.wavelength_um']
    method=case['recipe']['method']
    if method=='fringe_target':required+=['recipe.min','recipe.max']
    elif method not in ('single','phase'):required+=['recipe.values']
    conflicts=[p for p,x in f.items() if x['status']=='conflict']
    missing=[p for p in required if value(p) is None and p not in conflicts]
    questions=[]
    for p in conflicts:questions.append({'id':digest([s['revision'],p,'conflict'])[:16],'fields':[p],'kind':'FACT_CONFLICT','text':('来源条件已锁定；如确需改变请从新物理任务开始：' if f[p].get('locked') else '两个数值有冲突，请明确更正：')+p})
    if 'recipe.min' in missing or 'recipe.max' in missing:
        fields=[p for p in ('recipe.min','recipe.max') if p in missing];questions.append({'id':digest([s['revision'],fields])[:16],'fields':fields,'kind':'MISSING_FACT','text':'请补充允许的'+str(case['recipe']['variable'])+'范围（'+unit('recipe.min',case)+'）。','unit':unit('recipe.min',case),'variable':case['recipe']['variable']});missing=[p for p in missing if p not in fields]
    for p in missing:questions.append({'id':digest([s['revision'],p])[:16],'fields':[p],'kind':'MISSING_FACT','text':'请补充 '+p+'（'+unit(p,case)+'）。'+(' 透镜为零点，透镜前为负、后为正。' if p=='parameters.waist_z_mm' else ''),'unit':unit(p,case)})
    for ambiguity in out.get('ambiguities',[]):
        fields=ambiguity['fields']
        questions=[q for q in questions if not set(q['fields']) & set(fields)]
        questions.append({'id':digest([s['revision'],ambiguity])[:16],'unit':unit(fields[0],case) if len(fields)==1 else 'dimensionless',**ambiguity})
    out['questions']=questions;return out

def request(s):
    s=refresh(s)
    if s['questions']:raise ValueError('有效事实仍有缺项或冲突')
    r={'case_id':s['case_id'],'parameters':{},'goal':{}}
    for path,f in s['facts'].items():
        if f['status']!='resolved':continue
        if path.startswith('parameters.'):r['parameters'][path.split('.')[1]]=copy.deepcopy(f['value'])
        elif path.startswith('goal.'):r['goal'][path.split('.')[1]]=copy.deepcopy(f['value'])
    if r['goal']['operator'] in ('minimize','maximize'):r['goal'].pop('target',None);r['goal'].pop('tolerance',None)
    elif r['goal']['operator']!='near':r['goal'].pop('tolerance',None)
    if 'recipe.values' in s['facts'] and s['facts']['recipe.values']['status']=='resolved':r['values']=s['facts']['recipe.values']['value']
    if all(s['facts'].get('recipe.'+k,{}).get('status')=='resolved' for k in ('min','max')):r['bounds']={k:s['facts']['recipe.'+k]['value'] for k in ('min','max')}
    policy=s['facts'].get('execution.fast_only',{})
    if policy.get('status')=='resolved':r['fast_only']=policy['value']
    if r['parameters'].get('wavelengths_um'):
        for key in ('scan_min_um','scan_max_um','scan_points'):r['parameters'].pop(key,None)
    return r
