"""Explicit independent layer-list intake; preserves order and unknowns."""
import copy, json, re
from decimal import Decimal
from .core import digest, task_problem
from .backend import _strict_json, _redact

SCHEMA='film_stack_task_v2'
KEYS={'schema','case_id','incident_direction','layer_order','units_um','physics','layers','wavelength_um','nfreq','sampling','source'}

def is_stack_text(text):
    if type(text) is not str:return False
    if text.lstrip().startswith('{'):
        try:return _strict_json(text).get('schema')==SCHEMA
        except (ValueError,AttributeError):return False
    return bool(re.search(r'(?m)^第\d+层[：:]',text))

def natural_document(case_id,text):
    from .workflow_intake import rule_candidate
    view={'packet':{'case_id':case_id,'documents':[{'id':'requirements','title':'用户提供的独立层列表','lines':text.splitlines()}]},'clarification_documents':[],'input_sha256':digest(text)}
    fields=rule_candidate(view)['fields']
    def number(key,divisor=1):
        f=fields[key]
        return float(Decimal(str(f['value']))/Decimal(divisor)) if f['status']=='proposed' else None
    def boolean(key):
        f=fields[key];return f['value'] if f['status']=='proposed' else None
    layers=[];seen=set()
    pattern=r'^第(\d+)层[：:]\s*折射率为\s*([\d.]+)，\s*厚度为\s*([\d.]+)\s*(nm|um|µm|μm)，\s*出处为(.+?)。?$'
    for line in text.splitlines():
        m=re.fullmatch(pattern,line.strip())
        if m:
            index=int(m[1])
            if index in seen or index!=len(layers)+1:raise ValueError('层号冲突或顺序不连续；不自动重排。')
            seen.add(index);unit=1000 if m[4]=='nm' else 1
            layers.append({'n':float(Decimal(m[2])),'thickness_um':float(Decimal(m[3])/unit),'source':m[5]})
        elif re.match(r'^第\d+层[：:]',line.strip()):raise ValueError('每层需要明确折射率、厚度单位和出处；不猜缺项。')
    if number('layer_count') != len(layers):raise ValueError('声明层数与独立层列表不一致。')
    unit=re.search(r'(?m)^1个Meep单位为([\d.]+)\s*(um|µm|μm)。?$',text)
    physics={'dimensions':1 if fields['spatial_dimension']['value']=='1D' else None,
        'angle_deg':number('incidence_angle'),'mu':number('relative_permeability'),
        'lossless':boolean('lossless'),'isotropic':boolean('isotropic'),'dispersive':not boolean('nondispersive') if boolean('nondispersive') is not None else None,
        'n_incident':number('incident_index'),'n_exit':number('exit_index'),
        'linear':True if '所有介质线性。' in text.splitlines() else None,
        'field_component':'Ex' if '场分量为Ex。' in text.splitlines() else None}
    return {'schema':SCHEMA,'case_id':case_id,'incident_direction':'+z' if '入射方向为+z。' in text.splitlines() else None,
        'layer_order':'incident_to_exit' if '层序为从入射侧到出射侧。' in text.splitlines() else None,
        'units_um':float(unit[1]) if unit else None,'physics':physics,'layers':layers,
        'wavelength_um':[number('wavelength_min',1000),number('wavelength_max',1000)],'nfreq':number('wavelength_samples'),
        'sampling':{'kind':'equal_wavelength'},'source':'独立自然语言原文 SHA256 '+digest(text)}

def to_task(document):
    if type(document) is not dict or set(document)!=KEYS:raise ValueError('层列表字段不完整或含额外字段。')
    if document['schema']!=SCHEMA or document['incident_direction']!='+z' or document['layer_order']!='incident_to_exit':
        raise ValueError('必须明确+z入射与从入射侧到出射侧的层顺序；不重排。')
    if type(document['source']) is not str or len(document['source'].strip())<3:raise ValueError('缺少独立任务出处。')
    if re.search(r'待检脚本|ast_observation|script_observation',document['source'],re.I):raise ValueError('需求不能仅来自待检脚本。')
    physical=document['physics']
    if type(physical) is not dict or set(physical)!={'dimensions','angle_deg','mu','lossless','isotropic','dispersive','n_incident','n_exit','linear','field_component'}:
        raise ValueError('需要完整独立物理资料；未知不得补为默认参数。')
    if physical['linear'] is not True or physical['field_component']!='Ex':raise ValueError('只支持明确线性、正入射Ex任务。')
    if type(document['layers']) is not list or not 1<=len(document['layers'])<=8:raise ValueError('仅支持1–8层。')
    layers=[];sources=[{'kind':'independent-film-stack','reference':document['source'],'note':'按已确认入射方向及层序；每层来源单独保留。'}]
    for i,layer in enumerate(document['layers']):
        if type(layer) is not dict or set(layer)!={'n','thickness_um','source'} or type(layer['source']) is not str or len(layer['source'].strip())<3:
            raise ValueError(f'第{i+1}层参数或独立出处不完整。')
        if re.search(r'待检脚本|ast_observation|script_observation',layer['source'],re.I):raise ValueError('每层需要独立于待检脚本的出处。')
        layers.append({'n':layer['n'],'thickness_um':layer['thickness_um']})
        sources.append({'kind':'independent-layer','reference':layer['source'],'note':f'incident_to_exit layer {i+1}; units um'})
    count=document['nfreq']
    if type(count) is float and count.is_integer():count=int(count)
    task={'schema_version':1,'case_id':document['case_id'],'physics':{k:v for k,v in physical.items() if k not in ('linear','field_component')},
        'units_um':document['units_um'],'layers':layers,'wavelength_um':document['wavelength_um'],
        'nfreq':count,'sampling':document['sampling'],'sources':sources,
        'intent_note':'Explicit film_stack_task_v2 independent input; preserve incidence order and actual sampling.'}
    if task.get('sampling')!={'kind':'equal_wavelength'}:raise ValueError('层列表入口当前只接已明确的等波长需求。')
    problem=task_problem(task)
    if problem:raise ValueError(problem['reason'])
    return task

def prepare_stack(case_id,text):
    if type(text) is not str or not 1<=len(text)<=24000:raise ValueError('独立层列表长度不合法。')
    safe=_redact(text,None);errors=[];document=None;task=None
    try:
        document=_redact(_strict_json(safe),None) if safe.lstrip().startswith('{') else natural_document(case_id,safe)
        task=to_task(document)
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError) as exc:errors.append(str(exc))
    fields={}
    if task:
        for i,layer in enumerate(task['layers']):
            for key,unit in [('n','dimensionless'),('thickness_um','um')]:
                fields[f'layer_{i+1}_{key}']={'status':'proposed','value':layer[key],'unit':unit,'evidence':[{'document':document['layers'][i]['source'],'line':i+1,'quote':f'第{i+1}层 {key}={layer[key]}; 入射侧→出射侧'}]}
        for key,value,unit in [('layer_count',len(task['layers']),None),('wavelength_min',task['wavelength_um'][0]*1000,'nm'),('wavelength_max',task['wavelength_um'][1]*1000,'nm'),('wavelength_samples',task['nfreq'],None)]:
            fields[key]={'status':'proposed','value':value,'unit':unit,'evidence':[{'document':document['source'],'line':1,'quote':'独立层列表与明确等波长采样'}]}
    result={'mode':'EXPLICIT_LAYER_LIST_NOT_AI','confirmable':bool(task),'scope_problems':errors,
        'normalized_response':{'case_id':case_id,'fields':fields,'questions':[{'text':e} for e in errors],'conflicts':[]},
        'independent_document':document,'normalized_task':task}
    return {'kind':SCHEMA,'status':'DRAFT','source_text':safe,'redacted':safe!=text,
        'view':{'input_sha256':digest(safe)},'result':result,'result_sha256':digest(result),'confirmation':None,'model_calls':0,'solver_calls':0}

def apply_stack(intake,data):
    out=copy.deepcopy(intake);kind=data['type']
    if kind=='intake-review':
        if data.get('mode')!='mock' or out['status']=='CANCELLED':raise ValueError('层列表只做离线独立资料核对，不调用模型或恢复旧请求。')
        fresh=prepare_stack(out['result']['normalized_response']['case_id'],out['source_text'])
        out.update(result=fresh['result'],result_sha256=fresh['result_sha256'],status='REVIEW',confirmation=None)
    elif kind=='intake-confirm':
        fresh=prepare_stack(out['result']['normalized_response']['case_id'],out['source_text'])
        if out['status']!='REVIEW' or not fresh['result']['confirmable'] or fresh['result_sha256']!=out['result_sha256'] or data.get('approve') is not True or data.get('result_sha256')!=digest(out['result']):
            raise ValueError('层列表未知、冲突、变更或没有当前明确确认。')
        out.update(status='HUMAN_REVIEWED',confirmation={'result_sha256':digest(out['result']),'input_sha256':out['view']['input_sha256'],'task_approved':False})
    elif kind=='intake-cancel':out.update(status='CANCELLED',confirmation=None)
    elif kind=='intake-resume':
        if out['status']!='CANCELLED':raise ValueError('草稿未撤回。')
        out.update(status='DRAFT',confirmation=None)
    else:raise ValueError('层列表操作不支持。')
    return out

def project_stack(intake,options):
    if intake.get('status')!='HUMAN_REVIEWED' or not intake.get('confirmation') or intake['confirmation'].get('result_sha256')!=digest(intake['result']):
        raise ValueError('层列表需要当前人工确认。')
    fresh=prepare_stack(intake['result']['normalized_response']['case_id'],intake['source_text'])
    if fresh['result']!=intake['result'] or fresh['view']!=intake['view']:raise ValueError('层列表或出处改变，旧确认不适用。')
    required={'units_um','linear','field_component','mapping_source','accept_sampling','accept_decimal_projection','background','goal','role'}
    if type(options) is not dict or set(options)!=required or type(options['units_um']) not in (int,float) or options['units_um']!=1 or options['linear'] is not True or options['field_component']!='Ex' or options['accept_sampling'] is not True or options['accept_decimal_projection'] is not True:
        raise ValueError('需要确认单位、线性Ex及等波长映射。')
    if any(type(options[k]) is not str or not 3<=len(options[k].strip())<=4000 for k in ('mapping_source','background','goal','role')):raise ValueError('映射出处、背景和角色缺失。')
    task=copy.deepcopy(fresh['result']['normalized_task'])
    record={'schema_version':2,'mapping_adapter':SCHEMA,'semantic_input_sha256':intake['view']['input_sha256'],'semantic_result_sha256':digest(intake['result']),
        'native_task_sha256':digest(task),'original_request':intake['source_text'],'options':options,
        'layer_order':'incident_to_exit','incident_direction':'+z','task_approved':False,'solver_calls':0}
    context={'background':options['background'],'goal':options['goal'],'role':options['role'],'materials':intake['source_text'],'parameter_source':options['mapping_source'],'unknowns':'Explicit independent layers reviewed; script correctness unknown.'}
    return task,record,context
