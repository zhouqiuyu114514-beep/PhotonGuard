"""Versioned script-free film templates. Drafts never imply approval or execution."""
import copy
import hashlib
import re
from pathlib import Path
from . import workflow_intake as intake_api
from .core import digest, POLICY_HASH, task_problem
from .task_mapping import project
from .sampling import frequencies
from .script_import import preview_bytes, validate_provenance

ROOT=Path(__file__).resolve().parents[1]
TEMPLATE_ID='air-film-equal-wavelength-v1'
EXTRA='线性介质，正入射Ex；1 Meep单位=1微米。'
TEMPLATE_TEXT=intake_api.DEMO+'\n'+EXTRA
LABELS={'spatial_dimension':'空间维度','incidence_angle':'入射角','relative_permeability':'相对磁导率','lossless':'无损假设','isotropic':'各向同性','nondispersive':'无色散假设','layer_count':'膜层数量','incident_index':'入射介质','film_index':'膜层折射率','exit_index':'出射介质','film_thickness':'膜厚','wavelength_min':'波长下界','wavelength_max':'波长上界','wavelength_samples':'等波长点数'}

def catalog():
    return [{'id':TEMPLATE_ID,'title':'看一层薄膜怎样反射和透射光','context':'TEACHING_SYNTHETIC',
             'version':1,'source':'PhotonGuard公开合成练习卡，不是真实器件或测量',
             'facts':TEMPLATE_TEXT,'facts_sha256':hashlib.sha256(TEMPLATE_TEXT.encode()).hexdigest(),
             'numerics':{'resolution':80,'after_sources':100,'pml_um':1,'air_um':3},
             'scope':'1D、线性、无损、无色散、非磁、各向同性；空气两侧、正入射Ex。模板设置仍须数值检查。',
             'maximum_fdtd_per_validation':8,'no_runtime_model_required':True}]

def normalize(text):
    # Only explicit lexical aliases and sentence separators, never new facts.
    aliases=[(r'^(?:薄膜折射率|折射率n|n)\s*(?:为|=|:|：)?\s*','膜层折射率为'),
             (r'^(?:薄膜厚度|厚度|膜厚)\s*(?:为|=|:|：)?\s*','膜厚为')]
    lines=[];mapping=[]
    for original in re.split(r'[\n；;]|(?<=。)',text):
        line=original.strip()
        if not line:continue
        for pattern,replacement in aliases:
            line=re.sub(pattern,replacement,line)
        lines.append(line);mapping.append({'original':original.strip(),'normalized':line})
    return '\n'.join(lines),mapping

def source_for(task):
    if task_problem(task):raise ValueError('模板只接受完整受支持任务')
    if len(task['layers'])!=1:raise ValueError('当前无脚本模板仅支持单膜；多层请用高级入口')
    source=(ROOT/'examples/script_import/film_n2.py').read_text()
    values={'n':task['layers'][0]['n'],'d':task['layers'][0]['thickness_um'],'nfreq':task['nfreq']}
    for name,value in values.items():source=re.sub(r'^'+name+r' = .+$',name+' = '+repr(value),source,flags=re.M)
    source=re.sub(r'^fmin = .+$','fmin = 1 / '+repr(task['wavelength_um'][1]),source,flags=re.M)
    source=re.sub(r'^fmax = .+$','fmax = 1 / '+repr(task['wavelength_um'][0]),source,flags=re.M)
    if task.get('sampling'):
        source=source.replace('after = 100','frequencies_for_monitors = '+repr(frequencies(task))+'\nafter = 100')
        source=source.replace('.add_flux(fcen, df, nfreq,','.add_flux(frequencies_for_monitors,')
    preview=preview_bytes(source.encode(),TEMPLATE_ID+'.py')
    if preview['status']!='EXTRACTED':raise ValueError('版本化模板未通过只读解析')
    validate_provenance(preview['candidate'],task)
    return source,preview

def draft(ident,kind,text,*,reviewed_intake=None):
    if kind not in ('teaching','specified'):raise ValueError('请选择教学示例或指定资料')
    if kind=='teaching':text=TEMPLATE_TEXT
    if not isinstance(text,str) or not text.strip() or len(text)>24000:raise ValueError('请提供1–24000字的已有资料')
    text=intake_api.scrub(text);normalized,mapping=normalize(text)
    prepared=intake_api.prepare('novice-'+kind+'-'+ident,normalized)
    if reviewed_intake is not None:
        if reviewed_intake['view']!=prepared['view']:raise ValueError('模型草稿与当前原文不对应')
        intake=copy.deepcopy(reviewed_intake)
    else:intake=intake_api.apply(prepared,{'type':'intake-review','mode':'mock'})
    result=intake.get('result') or {};answer=result.get('normalized_response') or {};fields=answer.get('fields') or {}
    missing=[{'field':k,'label':LABELS.get(k,k),'status':f['status']} for k,f in fields.items() if f['status']!='proposed']
    blockers=list(result.get('scope_problems',[]))
    if re.search(r'绝对.*效率|非线性|SHG|三维|3D',text,re.I):blockers.append('超出支持范围：本入口不计算绝对转换效率或任意非线性过程。')
    ln=bool(re.search(r'铌酸锂|\bLN\b',text,re.I))
    if ln:blockers.append('真实波导需要独立资料：晶轴/传播方向、截面、材料与波长。材料名不能补出这些事实；可另选合成LN教学例。')
    # Unit scale and polarization are explicit versioned template conventions,
    # shown in the approval summary; the user need not know Meep to choose them.
    scale=re.findall(r'1\s*Meep\s*单位\s*=\s*([\d.]+)\s*微米',text)
    if any(v!='1' for v in scale):blockers.append('提供的长度单位映射与当前1微米模板冲突，请核对资料。')
    task=None;generated=None
    if result.get('confirmable') and not missing and not blockers:
        # Projection on an ephemeral copy is a draft, not a persisted human approval.
        reviewed=intake_api.apply(intake,{'type':'intake-confirm','approve':True,'result_sha256':intake['result_sha256']})
        options={'units_um':1,'linear':True,'field_component':'Ex','mapping_source':'用户选择并需确认的版本化模板约定：线性模型、正入射Ex、1Meep单位=1微米；不表示测得真实器件性质。物理参数独立资料：'+text[:3200],
                 'accept_sampling':True,'accept_decimal_projection':True,'background':'所选教学示例' if kind=='teaching' else '用户提供的指定模型资料',
                 'goal':'计算指定薄膜的离散R/T光谱并检查数值可信度','role':'核对研究意图与明确资料的操作者'}
        task,_,context=project(reviewed,options)
        task['intent_note']='教学合成示例；不是实际器件' if kind=='teaching' else '按所提供资料建立指定模型；没有填补未知物理事实'
        generated,preview=source_for(task)
    else:context=None
    plan={'schema_version':1,'template_id':TEMPLATE_ID,'template_facts_sha256':catalog()[0]['facts_sha256'],
          'task_sha256':digest(task) if task else None,'generated_source_sha256':hashlib.sha256(generated.encode()).hexdigest() if generated else None,
          'policy_sha256':POLICY_HASH,'maximum_initial_fdtd':8,'automatic_repair':False,'additional_model_requests':0}
    return {'context_type':'TEACHING_SYNTHETIC' if kind=='teaching' else 'SPECIFIED_MODEL','kind':kind,'original_text':text,
            'normalization':mapping,'intake':intake,'missing':missing,'blockers':blockers,'task':task,'context':context,
            'template_id':TEMPLATE_ID,'template_source':catalog()[0]['source'],'ready':task is not None,
            'plan':plan,'plan_sha256':digest(plan),'source':generated,'evidence_source':'NOT_RUN','approval':False}

def action(store,state,data):
    from .workflow import WorkflowError
    kind=data['type'];novice=state.get('novice')
    if not novice:raise WorkflowError('不是无脚本任务',409)
    if state.get('approval') or state.get('pipeline'):raise WorkflowError('已锁定或运行；请保留当前任务并新建版本',409)
    if kind=='novice-ai-review':
        if set(data)!={'type','expected_revision','approve_data'} or data['approve_data'] is not True:raise WorkflowError('请明确选择将当前原文交给真实AI整理',422)
        if getattr(store,'simulation_context',None):raise WorkflowError('模拟确认不能批准收费；离线评测入口禁用模型',403)
        client=getattr(store,'product_client',None)
        if client is None:raise WorkflowError('当前服务没有真实模型绑定',503)
        from .novice_ai import run
        try:response=run(client,'ui-'+state['id']+'-'+str(state['revision']),novice['intake'])
        except (ValueError,OSError) as e:raise WorkflowError(str(e),409) from None
        store._snapshot(state,'novice-real-ai',response)
        if response['status']=='DRAFT_RETURNED' and response['guard']['accepted']:
            reviewed=copy.deepcopy(novice['intake']);result=response['guard']['result']
            result.update(mode='REAL_MODEL',actual_model_calls=len(response['steps']),origin_verified=True)
            reviewed.update(status='REVIEW',result=result,result_sha256=digest(result),confirmation=None,model_calls=len(response['steps']))
            state['novice']=draft(state['id'],novice['kind'],novice['original_text'],reviewed_intake=reviewed)
            state['intake']=reviewed
        state['novice']['model_attempt']={'status':response['status'],'calls':response['actual_provider_attempts'],
            'guard':response.get('guard'),'evidence':'REAL_DEEPSEEK','automatic_retry':False}
        store._save(state);return store.present(state)
    if kind in ('novice-material','novice-pause'):
        if set(data)!={'type','expected_revision','text'} or novice['kind']!='specified':raise WorkflowError('只允许指定资料任务修改原文',422)
        try:new=draft(state['id'],'specified',data['text'])
        except ValueError as e:raise WorkflowError(str(e),422) from None
        state['novice']=new;state['intake']=new['intake']
        if kind=='novice-pause':state['paused_reason']='无脚本任务资料暂缺；当前原文已保存。'
        store._snapshot(state,'novice-material-paused' if kind=='novice-pause' else 'novice-material',{'original_text':new['original_text'],'draft_plan_sha256':new['plan_sha256'],'task_approved':False})
        store._save(state);return store.present(state)
    if kind!='novice-start' or set(data)!={'type','expected_revision','approve','plan_sha256'}:raise WorkflowError('无脚本任务操作无效',422)
    if data['approve'] is not True or data['plan_sha256']!=novice['plan_sha256']:raise WorkflowError('请确认当前版本的任务摘要；旧确认不能重用',409)
    verified=draft(state['id'],novice['kind'],novice['original_text'],reviewed_intake=novice['intake'])
    if not verified['ready'] or verified['plan']!=novice['plan']:raise WorkflowError('资料仍有缺项、冲突或模板版本变化',409)
    if getattr(store,"simulation_context",None):raise WorkflowError('本次评测禁止新求解；模拟确认不会替代资源许可',403)
    if not store.allow_workers or not store.meep_available:raise WorkflowError('真实Meep不可用；没有锁定或生成结果',503)
    if not hasattr(store,'pipeline_controller'):raise WorkflowError('当前未启用受限执行流程',503)
    # Existing lock/import/run checks and the existing repair approval stay authoritative.
    state.update(task=verified['task'],context=verified['context'],context_unknown_fields=[],context_reviewed=True,task_reviewed=True,diagnostic_mode='rules',three_step=True)
    store._snapshot(state,'novice-plan-approval',{'plan':novice['plan'],'actor_type':state.get('actor_type','USER_ACTION'),'maximum_initial_fdtd':8,'repair_approved':False})
    store._save(state);controller=store.pipeline_controller
    controller.legacy(state['id'],'import',name=TEMPLATE_ID+'.py',source=verified['source'])
    controller.legacy(state['id'],'confirm',approve=True)
    state=store._load(state['id']);state['pipeline']={'status':'CHECKING','phase':'initial','message':'正在按已确认模板完成限定检查；修复需要另行确认。'}
    store._save(state);controller.launch(state['id'],'initial')
    return store.present(state)
