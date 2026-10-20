"""Local workbench state, approval-bound execution, and grounded model explanations."""
from __future__ import annotations
import copy
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import uuid
import zipfile
from ..core import digest
from ..workflow import WorkflowError,atomic_json
from .registry import TOOLS
from .planner import templates,build_plan,plan_from_text
from .executor import execute_plan
from .contracts import METRICS,validate_spec
from .report import comparison_csv,curve_csv,report_record,compare_versions

def now():return datetime.now(timezone.utc).isoformat()

class ExperimentStore:
    def __init__(self,owner):
        self.owner=owner;self.root=owner.root/'experiments';self.root.mkdir(exist_ok=True)
        self.lock=threading.RLock();self.running=set()
        for path in self.root.glob('*/case.json'):
            s=json.loads(path.read_text(encoding='utf-8'))
            if s['status']=='RUNNING':
                s.update(status='FAILED',error='服务曾中断；保留原任务与证据，未自动重跑。');self.save(s)

    @property
    def client(self):
        binding=getattr(self.owner,'ai_binding',None)
        return binding.client if binding and binding.managed else getattr(self.owner,'product_client',None)
    def folder(self,ident):
        if not isinstance(ident,str) or not re.fullmatch('[a-f0-9]{32}',ident):raise WorkflowError('实验编号无效',404)
        p=self.root/ident
        if p.is_symlink():raise WorkflowError('实验目录无效',422)
        return p
    def get(self,ident):
        with self.lock:
            p=self.folder(ident)/'case.json'
            if not p.is_file() or p.is_symlink():raise WorkflowError('实验不存在',404)
            return json.loads(p.read_text(encoding='utf-8'))
    def save(self,s):
        s['revision']+=1;s['updated_at']=now();atomic_json(self.folder(s['id'])/'case.json',s)
        if s.get('command_receipt'):
            from .record_view import record_view,view_errors
            parent=self.get(s['parent_id']) if s.get('parent_id') else None
            receipt=s['command_receipt'];receipt['rendered']=record_view(s,parent)
            receipt['tool_terminal']=s['status'] if s['status'] in ('COMPLETED','FAILED') else None
            reread=self.get(s['id']);receipt['display_errors']=view_errors(receipt['rendered'],reread,parent)
            receipt['delivered_error']=bool(receipt['display_errors'])
            atomic_json(self.folder(s['id'])/'case.json',s)
    def presentation(self,s):
        if s.get('kind')=='inverse':
            from .inverse_report import view
            out=view(s)
            parent=self.get(s['inverse_reference_parent']) if s.get('inverse_reference_parent') else {}
            out['comparison_origin']=s.get('comparison_origin') or parent.get('comparison_origin')
            root=s if s['inverse_root']==s['id'] else self.get(s['inverse_root'])
            out['ledger']=root['inverse_ledger'];return out
        if s.get('kind')=='observation':
            from .inference_report import view
            return view(s)
        from .record_view import record_view
        parent=self.get(s['parent_id']) if s.get('parent_id') else None
        view=record_view(s,parent);versions=[];events=[]
        for path in self.root.glob('*/case.json'):
            r=json.loads(path.read_text())
            if r['family_id']!=s['family_id']:continue
            logs=[json.loads(p.read_text()) for p in (path.parent/'events').glob('*.json')]
            if r.get('result'):
                created=min((e['at'] for e in logs if e['kind']=='CREATED'),default=r['updated_at'])
                versions.append({'id':r['id'],'sha256':digest(r['result']),'goal':r['spec']['goal'],'created_order':created})
            for e in logs:
                if e['kind']=='SESSION_COMMAND':
                    receipt=e['value']['receipt'];command=receipt.get('command') or {}
                    events.append({'at':e['at'],'action':command.get('action'),'status':receipt['status'],'record_id':receipt['record_id'],'computed':receipt['computed'],'reused':receipt['reused']})
        view['history']=sorted(events,key=lambda e:e['at']);view['available_versions']=sorted(versions,key=lambda v:v['created_order'])
        return view
    def public_record(self,s):
        out=copy.deepcopy(s);out['experiment_record']=self.presentation(s);return out
    def event(self,s,kind,value):
        p=self.folder(s['id'])/'events';p.mkdir(exist_ok=True)
        atomic_json(p/(uuid.uuid4().hex+'.json'),{'at':now(),'kind':kind,'value':value,'case_revision':s['revision']})
    def bootstrap(self):
        rows=[];records=[]
        for path in self.root.glob('*/case.json'):
            s=json.loads(path.read_text(encoding='utf-8'));records.append(s);rows.append({k:s.get(k) for k in ('id','title','status','domain','updated_at','family_id')})
        binding=getattr(self.owner,'ai_binding',None)
        ai=self.client.status() if self.client else binding.status() if binding else {'live_enabled':False,'reason':'此环境未启用 AI 连接。'}
        if binding:ai={**ai,'binding':binding.status()}
        from .case_catalog import catalog,library_digest
        library=catalog()
        for item in library:
            matches=[]
            for record in records:
                if record.get('library_origin',{}).get('case_id')==item['id'] and record.get('result') and record.get('kind')=='teaching':
                    matches.append({'id':record['id'],'at':record['updated_at'],'status':'EXISTING_COMPUTATION_PREVIEW','label':'已有计算预览；改变参数后必须另行计算'})
            if matches:item['preview']=max(matches,key=lambda x:x['at'])
        import importlib.util
        capabilities={'saved_results':True,'local_workers':bool(getattr(self.owner,'allow_workers',False)),
          'numpy':importlib.util.find_spec('numpy') is not None,'tmm':importlib.util.find_spec('tmm') is not None,
          'lightpipes':importlib.util.find_spec('LightPipes') is not None,'meep':bool(getattr(self.owner,'meep_available',False)),
          'live_ai':bool(ai.get('live_enabled')),'analysis':importlib.util.find_spec('scipy') is not None}
        from .observation_workflow import samples
        from .case_catalog import missions
        return {'csrf':self.owner.csrf,'tools':TOOLS,'templates':templates(),'case_library':library,'library_sha256':library_digest(),'metrics':{k:sorted(v) for k,v in METRICS.items()},'cases':sorted(rows,key=lambda x:x['updated_at'],reverse=True),'ai':ai,'capabilities':capabilities,'missions':missions(),'data_samples':samples()}
    def create(self,data):
        if set(data)-{'kind','template_id','text'} or data.get('kind') not in ('teaching','specified'):raise WorkflowError('请选择教学示例或指定资料')
        kind=data['kind'];text=data.get('text','');template=None
        if kind=='teaching':
            template=next((x for x in templates() if x['id']==data.get('template_id')),None)
            if template is None:raise WorkflowError('教学卡不存在')
            text=template['text']
        if not isinstance(text,str) or len(text)>24000:raise WorkflowError('资料过长或格式无效')
        from ..workflow_model import wire
        if wire.credential_risk(text):raise WorkflowError('请勿在实验资料中填写API密钥')
        ident=uuid.uuid4().hex;self.folder(ident).mkdir()
        s={'id':ident,'title':template['title'] if template else '指定资料实验','revision':0,'domain':template['domain'] if template else None,'status':'DRAFT','kind':kind,'text':text,'questions':[],'spec':template['spec'] if template else None,'plan':None,'result':None,'model_calls':0,'family_id':ident,'parent_id':None,'updated_at':now()}
        self.save(s);self.event(s,'CREATED',{'kind':kind,'actor':'BROWSER_USER_ACTION','teaching_facts_explicitly_selected':bool(template)})
        return s
    def _model(self,s,data):
        if data.get('approve_data') is not True:raise WorkflowError('真实AI需要明确同意发送当前资料')
        if getattr(self.owner,'simulation_context',None):raise WorkflowError('模拟确认不能批准收费模型',403)
        if not self.client:raise WorkflowError('真实AI当前不可用',503)
        family=self.get(s['family_id']) if s['family_id']!=s['id'] else s
        # The frozen evaluation owns its per-task call cap. Interactive follow-ups
        # remain explicitly approved and bounded by the persistent financial ledger.
        self.client.preflight()
        family['family_model_calls']=family.get('family_model_calls',0)+1
        if family is not s:self.save(family)
        else:s['family_model_calls']=family['family_model_calls']
        s['model_calls']+=1;self.save(s)
        self.event(s,'AI_DATA_APPROVAL',{'actor':'BROWSER_USER_ACTION','text_sha256':digest(s['text']),'call_number':family['family_model_calls']})
        return self.client
    def action(self,ident,data):
        with self.lock:
            s=self.get(ident)
            if data.get('event_id') and any(e['event_id']==data['event_id'] for e in s.get('fact_state',{}).get('events',[])):
                from .dialogue_update import action
                return action(self,s,data)
            if data.get('expected_revision')!=s['revision']:raise WorkflowError('资料版本已改变，请刷新后核对',409)
            kind=data.get('type')
            if s['status']=='RUNNING':raise WorkflowError('当前计划正在运行，请等待结果',409)
            if s.get('kind')=='inverse':
                from .observation_group import action
                return action(self,s,data)
            if s.get('kind')=='observation':
                from .observation_workflow import action
                return action(self,s,data)
            if kind=='session_ai':
                from .session_ai import action
                return action(self,s,data)
            if kind=='session_input':
                from .session_commands import ingest
                return ingest(self,s,data.get('text',''),event_id=data.get('input_id') or uuid.uuid4().hex,request=data.get('request'),live_data={'mode':'live','force_model':True,'approve_data':data.get('approve_data')} if data.get('mode')=='live' else None)
            if kind=='session_command':
                from .session_commands import dispatch
                return dispatch(self,s,data.get('command',{}),approve=data.get('approve') is True,plan_sha256=data.get('plan_sha256'))
            if (s.get('session_version')==2 or data.get('session_version')==2) and kind in ('plan','library_plan','supplement','save','explore_case','fact_update','undo_fact'):
                from .dialogue_update import action
                return action(self,s,data)
            if kind=='plan' and (s.get('library_context') or s.get('library_origin')) and not s.get('parent_context'):
                if data.get('mode')!='live':raise WorkflowError('案例资料请通过案例参数表或 AI 案例规划继续，避免丢失来源条件')
                from .case_workflow import action
                return action(self,s,{**data,'type':'library_plan'})
            if kind in ('library_plan','explore_case','restore_result','choose_observation_candidate'):
                from .case_workflow import action
                return action(self,s,data)
            if kind=='revise_goal':
                if set(data)-{'type','expected_revision','goal'}:raise WorkflowError('快捷修改仅接受目标，不接受物理参数变化')
                if not s.get('plan'):raise WorkflowError('先完成原任务规划，再修改目标')
                parent={'id':s['id'],'spec':s['spec'],'plan_sha256':s['plan']['sha256']}
                spec=copy.deepcopy(s['spec']);spec['goal']=copy.deepcopy(data.get('goal'));spec['parent_task_id']=s['id']
                spec=validate_spec(spec,parent);plan=build_plan(spec,parent)
                if s.get('result'):
                    from .result_reuse import rescore
                    reused=rescore(self,s,spec,plan)
                    if reused is not None:return reused
                text='用户通过目标表单明确设置：'+json.dumps(spec['goal'],ensure_ascii=False)+'。物理参数、候选目录与资源额度全部沿用来源实验。'
                child=self.create({'kind':'specified','text':text})
                child.update(parent_id=s['id'],family_id=s['family_id'],kind=s['kind'],title=s['title']+' · 新目标',domain=s['domain'],
                             parent_context=parent,spec=spec,plan=plan,status='PLANNED')
                from .case_workflow import inherit
                inherit(self,s,child)
                self.save(child);self.event(child,'EXPLICIT_GOAL_REVISION',{'parent_id':s['id'],'goal':spec['goal'],'model_calls':0,'physical_parameters_changed':False})
                return child
            if kind=='supplement':
                if s.get('approved_plan_sha256') or s.get('result'):raise WorkflowError('已经批准执行的资料不可补写，请另存修订',409)
                mode=data.get('mode','save')
                if mode not in ('save','live'):raise WorkflowError('未知补充方式')
                if mode=='live' and data.get('approve_data') is not True:raise WorkflowError('真实AI需要明确同意发送当前资料')
                addition=data.get('text','')
                if not isinstance(addition,str) or not addition.strip():raise WorkflowError('请填写要补充的已知事实')
                from ..workflow_model import wire
                if wire.credential_risk(addition):raise WorkflowError('请移除API密钥')
                combined=s['text']+'\n\n补充资料：\n'+addition.strip()
                if len(combined)>24000:raise WorkflowError('原资料与补充合计不能超过24000字')
                self.event(s,'FACTS_SUPPLEMENTED',{'original_text':s['text'],'added_text':addition.strip(),'actor':'BROWSER_USER_ACTION','previous_questions':s.get('questions',[])})
                s.update(text=combined,plan=None,spec=None,status='DRAFT',questions=[]);s.pop('error',None);self.save(s)
                if mode=='live':
                    try:return self.action(ident,{'type':'plan','expected_revision':s['revision'],'mode':'live','approve_data':True})
                    except (WorkflowError,ValueError) as exc:
                        s=self.get(ident);s.update(status='NEEDS_INFORMATION',error='补充资料已保存；'+str(exc),questions=['请核对服务状态；未自动重复发送请求。']);self.save(s)
                return s
            if kind=='save':
                if s.get('result') or s.get('approved_plan_sha256'):raise WorkflowError('已批准执行的版本不能覆盖，请创建修订',409)
                text=data.get('text')
                if not isinstance(text,str) or not 1<=len(text)<=24000:raise WorkflowError('请填写有效资料')
                from ..workflow_model import wire
                if wire.credential_risk(text):raise WorkflowError('请移除API密钥')
                s.update(text=text,plan=None,spec=None,status='DRAFT',questions=[]);s.pop('error',None);self.save(s);return s
            if kind in ('plan','revise'):
                parent=None
                if kind=='revise':
                    if not s.get('plan'):raise WorkflowError('先完成原任务规划，才能保留约束修订')
                    parent={'id':s['id'],'spec':s['spec'],'plan_sha256':s['plan']['sha256']}
                    text=data.get('text','')
                    if not isinstance(text,str) or not text.strip() or len(text)>24000:raise WorkflowError('请写明要修改的目标')
                    child=self.create({'kind':'specified','text':text})
                    child.update(parent_id=s['id'],family_id=s['family_id'],kind=s['kind'],title=s['title']+' · 修订',domain=s['domain'],parent_context=parent)
                    from .case_workflow import inherit
                    inherit(self,s,child)
                    self.save(child);s=child
                elif s.get('result') or s.get('approved_plan_sha256'):raise WorkflowError('已批准执行的计划不可重写，请创建修订',409)
                mode=data.get('mode','rules')
                if mode not in ('rules','live'):raise WorkflowError('未知整理方式')
                client=self._model(s,data) if mode=='live' else None
                parent=parent or s.get('parent_context')
                try:response=plan_from_text(s['text'],s['kind'],client,'experiment-'+s['id']+'-'+str(s['model_calls']),parent)
                except Exception as exc:
                    s.update(status='NEEDS_INFORMATION',plan=None,error='本次AI整理未完成，已保存资料；没有自动重试。',questions=['请检查AI调用记录后再决定是否重试。'])
                    self.event(s,'AI_FAILED',{'error_type':type(exc).__name__,'automatic_retry':False});self.save(s);return s
                s.update(spec=response.get('spec'),questions=response.get('questions',[]),plan=response.get('plan'),status='PLANNED' if response.get('plan') and not response.get('questions') else 'NEEDS_INFORMATION')
                if s['status']=='PLANNED':s.pop('error',None)
                if s['spec']:s['domain']=s['spec'].get('domain')
                self.event(s,'PLAN_DRAFT',response);self.save(s);return s
            if kind=='run':
                if data.get('approve') is not True or not s.get('plan') or data.get('plan_sha256')!=s['plan']['sha256'] or s['status']!='PLANNED':raise WorkflowError('请批准当前有效计划，旧确认不能复用',409)
                if not self.owner.allow_workers or getattr(self.owner,'simulation_context',None):raise WorkflowError('当前服务禁止新求解',403)
                if self.running:raise WorkflowError('本工作台已有计算任务，请稍候',409)
                if build_plan(s['spec'],s.get('parent_context'))!=s['plan']:raise WorkflowError('计划校验失败',409)
                from .case_workflow import reserve
                reserve(self,s)
                self.event(s,'PLAN_APPROVED',{'actor':'BROWSER_USER_ACTION','plan_sha256':s['plan']['sha256'],'resource_budget':s['plan']['resource_budget']})
                s['status']='RUNNING';s['approved_plan_sha256']=s['plan']['sha256'];self.running.add(s['id']);self.save(s)
                threading.Thread(target=self._run,args=(s['id'],),daemon=True).start();return s
            if kind=='explain':
                if not s.get('result'):raise WorkflowError('先运行实验，再解释实际结果')
                client=self._model(s,data);facts=[]
                for c in s['result']['candidates']:
                    if c.get('goal'):facts.append({'id':c['id'],'goal':c['goal'],'checks_passed':c.get('all_checks_passed'),'is_finite_best':c['id']==s['result']['winner_id'],'verification':c.get('verification')})
                from ..product_phase import json_payload
                try:response=client.complete('experiment-explain-'+s['id']+'-'+str(s['model_calls']),json_payload('只从事实选择应向新手展示的候选。输出JSON {candidate_ids:[实际id],next_step:"review_assumptions"|"try_new_goal"|"collect_missing_facts"}。不输出额外数值或伪造解释。程序将引用实际结果生成说明。',{'facts':facts,'assumptions':s['plan']['assumptions']}))
                except Exception as exc:
                    s['explanation']={'status':'FAILED','text':'本次AI解释未完成；原计算结果已保留，没有自动重试。'}
                    self.event(s,'EXPLANATION_FAILED',{'error_type':type(exc).__name__,'automatic_retry':False});self.save(s);return s
                try:
                    obj=json.loads(response['assistant']['content']);ids=obj['candidate_ids']
                    if not ids or any(i not in {f['id'] for f in facts} for i in ids):raise ValueError('未知候选引用')
                    texts=[]
                    for i in ids:
                        f=next(f for f in facts if f['id']==i);g=f['goal']
                        conclusion='数值检查未通过，不能认定达标。' if f['checks_passed'] is not True else ('达到目标。' if g['met'] is True else '未达到目标。' if g['met'] is False else '这是有限候选中的优化比较，未设置达标阈值。')
                        labels={'screen_radius_um':'屏幕光斑半径','reflectance':'反射率','transmittance':'透射率','fringe_period_mm':'条纹周期','first_zero_mm':'第一暗纹位置','central_intensity_ratio':'中心强度比'}
                        origin=g.get('source',{}).get('label','实际候选计算')
                        texts.append(f"{i}：{labels.get(g['metric'],g['metric'])} = {g['value']:.6g} {g['unit']}（{origin}）；"+conclusion)
                        v=f.get('verification') or {};mg=v.get('goal_meep') or {}
                        if mg.get('value') is not None:
                            texts.append(f"同一候选独立Meep值为 {mg['value']:.6g}；"+('独立数值检查通过。' if v.get('numerical_status')=='NUMERICAL_PASS' else '独立数值检查尚未通过，不能据此确认达标。'))
                    steps={'review_assumptions':'请核对模型假设与实际条件是否一致。','try_new_goal':'可以保留原参数，另存一个目标修订。','collect_missing_facts':'请先补充未确定的实际资料。'}
                    texts.append(steps[obj['next_step']]);s['explanation']={'status':'GROUNDED_IN_ACTUAL_RESULTS','text':'\n'.join(texts),'selected_ids':ids,'model_selects_facts_only':True}
                except (ValueError,TypeError,KeyError):s['explanation']={'status':'REJECTED','text':'AI解释没有通过实际结果引用核对；计算结果仍可直接查看。'}
                self.event(s,'EXPLANATION',{'response':response,'grounded':s['explanation']});self.save(s);return s
            raise WorkflowError('不支持的实验操作')
    def _run(self,ident):
        try:
            s=self.get(ident);result=execute_plan(s['plan'],self.folder(ident)/'execution')
            with self.lock:
                s=self.get(ident);s.update(result=result,status='COMPLETED' if result['status']=='RUN_COMPLETED' else 'FAILED')
                if s.get('parent_id'):s['parent_comparison']=compare_versions(self.get(s['parent_id']),s)
                self.save(s)
                # Publish a terminal result and its output accounting under one lock.
                from .case_workflow import settle_output
                settle_output(self,s)
                self.running.discard(ident)
        except Exception as exc:
            with self.lock:
                s=self.get(ident);s.update(status='FAILED',error=str(exc));self.save(s)
        finally:
            with self.lock:
                from .case_workflow import settle_output
                try:settle_output(self,self.get(ident))
                finally:self.running.discard(ident)
    def verified_case(self,ident):
        s=self.get(ident)
        if s['status']=='RUNNING':raise WorkflowError('计算中不能导出未完成证据',409)
        folder=self.folder(ident)
        if s.get('kind')=='inverse':
            from .observation_group import verify
            verify(self,s)
        if s.get('kind')=='observation':
            from .observation_workflow import verify
            verify(self,s)
        if s.get('result'):
            execution=folder/'execution';manifest=json.loads((execution/'manifest.json').read_text(encoding='utf-8'))
            for name,h in manifest['files'].items():
                path=execution/name
                if not path.resolve().is_relative_to(execution.resolve()) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=h:raise WorkflowError('运行证据发生变化，停止导出',409)
            if s['result']!=json.loads((execution/'result.json').read_text(encoding='utf-8')):raise WorkflowError('界面结果与运行证据不一致',409)
        return s
    def export_table(self,ident):
        s=self.verified_case(ident)
        if s.get('kind')=='inverse':
            from .inverse_report import table
            return table(s)
        if s.get('kind')=='observation':
            from .inference_report import table
            return table(s)
        if not s.get('result'):raise WorkflowError('尚无计算数据可以导出')
        return comparison_csv(s)
    def export_summary(self,ident):
        from .summary_html import render_summary
        s=self.verified_case(ident)
        if s.get('kind')=='inverse':
            from .inverse_report import summary
            return summary(s)
        if s.get('kind')=='observation':
            from .inference_report import summary
            return summary(s)
        if not s.get('result'):raise WorkflowError('尚无实际结果可以生成只读摘要')
        return render_summary(s,self.presentation(s))
    def export_family(self,ident):
        """Snapshot a data family, including rejected versions, without computing."""
        with self.lock:
            current=self.verified_case(ident)
            members=[self.get(p.parent.name) for p in self.root.glob('*/case.json')]
            members=sorted((s for s in members if s.get('family_id')==current['family_id']),key=lambda s:s['id'])
            if not any(s.get('kind') in ('observation','inverse') for s in members):raise WorkflowError('此导出入口仅用于数据任务链')
            # Bound input and expansion before constructing in-memory ZIPs.
            limit=128*1024**2;size=0
            for s in members:
                self.verified_case(s['id'])
                for p in self.folder(s['id']).rglob('*'):
                    if p.is_symlink():raise WorkflowError('证据目录包含不支持的链接',422)
                    if p.is_file():size+=p.stat().st_size
                if size>limit:raise WorkflowError('任务链超过导出上限，请分别导出版本',422)
            buffer=io.BytesIO();files={};rows=[];expanded=0
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as bundle:
                for s in members:
                    with zipfile.ZipFile(io.BytesIO(self.export(s['id']))) as part:
                        for info in part.infolist():
                            expanded+=info.file_size
                            if expanded>limit:raise WorkflowError('任务链超过导出上限，请分别导出版本',422)
                            raw=part.read(info.filename);name=s['id']+'/'+info.filename
                            files[name]=hashlib.sha256(raw).hexdigest();bundle.writestr(name,raw)
                    rows.append({k:s.get(k) for k in ('id','parent_id','kind','status','title')})
                bundle.writestr('FAMILY_MANIFEST.json',json.dumps({'family_id':current['family_id'],'selected_id':ident,'versions':rows,'files':files,'new_computations':0,'model_calls':0},ensure_ascii=False,indent=2))
                bundle.writestr('README_ZH.md','每个版本单独保存原始数据、计划、结果和复跑说明。FAMILY_MANIFEST.json 记录父子关系与文件校验值；失败和缺条件的版本也保留。模型估计不等于实测，重新计算需显式批准。\n')
            return buffer.getvalue()
    def export(self,ident):
        s=self.verified_case(ident);folder=self.folder(ident);buffer=io.BytesIO();files={}
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_symlink():raise WorkflowError('证据目录包含不支持的链接',422)
                if p.is_file():
                    raw=p.read_bytes();name=p.relative_to(folder).as_posix();files[name]=hashlib.sha256(raw).hexdigest();z.writestr(name,raw)
            if s.get('result'):
                derived={'SUMMARY.html':self.export_summary(ident),'tables/candidates.csv':comparison_csv(s),'tables/curves.csv':curve_csv(s),
                         'tables/report.json':json.dumps({**report_record(s),'experiment_record':self.presentation(s)},ensure_ascii=False,indent=2).encode('utf-8')}
                for name,raw in derived.items():
                    if name in files:raise WorkflowError('导出表格与已有文件重名',409)
                    files[name]=hashlib.sha256(raw).hexdigest();z.writestr(name,raw)
            if s.get('kind')=='observation':
                from .inference_report import summary,table,view
                derived={'SUMMARY.html':summary(s),'tables/report.json':json.dumps(view(s),ensure_ascii=False,indent=2).encode()}
                if s.get('fit_result',{}).get('data'):derived['tables/fit-and-residual.csv']=table(s)
                for name,raw in derived.items():files[name]=hashlib.sha256(raw).hexdigest();z.writestr(name,raw)
            if s.get('kind')=='inverse':
                from .inverse_report import summary,table,view
                derived={'SUMMARY.html':summary(s),'tables/report.json':json.dumps(view(s),ensure_ascii=False,indent=2).encode()}
                if s.get('inverse_result',{}).get('data'):derived['tables/fit-and-residual.csv']=table(s)
                for name,raw in derived.items():files[name]=hashlib.sha256(raw).hexdigest();z.writestr(name,raw)
                raw='原始扫描、计划与局部结果均保留；MODEL_ESTIMATE 不是真实参数保证。复跑：python -m photonguard.experiments.inverse_cli inverse-execution/request.json --out rerun --approve。教学隐藏对象不导出到分析资料；复跑使用已保存 CSV，不重新生成测量。\n'.encode()
                files['INVERSE_README_ZH.md']=hashlib.sha256(raw).hexdigest();z.writestr('INVERSE_README_ZH.md',raw)
            z.writestr('EXPORT_MANIFEST.json',json.dumps({'case_id':ident,'files':files},indent=2))
            z.writestr('README_ZH.md','模型估计不代表实测参数；原始数据未清洗。拟合复跑：python -m photonguard.experiments.inference_cli fit-execution/request.json --out rerun --approve。后续版本通过 case.json 的 forward_children / parent_id 关联，各版本可分别导出。\n' if s.get('kind')=='observation' else '这是指定理想模型和有限候选的可复核记录。计划及数值结果保存在JSON中。\n重新运行需明确再次消耗计算资源：python -m photonguard.experiments.cli run execution/plan.json --out rerun --approve\n运行完成、数值检查通过、目标达标是三个不同状态。教学结果不代表实际器件。\n')
        return buffer.getvalue()

def store_for(owner):
    with owner.lock:
        if not hasattr(owner,'experiment_store'):owner.experiment_store=ExperimentStore(owner)
        return owner.experiment_store

def route_get(handler,path,parts):
    if path=='/api/experiments/ai/status':
        from .ai_binding import manager_for
        handler.json(manager_for(handler.store).status());return True
    if path=='/api/experiments/library':
        from .case_catalog import catalog,library_digest
        handler.json({'cases':catalog(),'library_sha256':library_digest()});return True
    if path=='/api/experiments/bootstrap':handler.json(store_for(handler.store).bootstrap());return True
    if len(parts)==4 and parts[:3]==['api','experiments','cases']:
        store=store_for(handler.store);handler.json(store.public_record(store.get(parts[3])));return True
    if len(parts)==5 and parts[:3]==['api','experiments','cases'] and parts[4]=='export':handler.send(store_for(handler.store).export(parts[3]),'application/zip');return True
    if len(parts)==5 and parts[:3]==['api','experiments','cases'] and parts[4]=='family-export':handler.send(store_for(handler.store).export_family(parts[3]),'application/zip');return True
    if len(parts)==5 and parts[:3]==['api','experiments','cases'] and parts[4]=='summary':handler.send(store_for(handler.store).export_summary(parts[3]),'text/html; charset=utf-8');return True
    if len(parts)==5 and parts[:3]==['api','experiments','cases'] and parts[4]=='table':handler.send(store_for(handler.store).export_table(parts[3]),'text/csv; charset=utf-8');return True
    return False

def route_post(handler,path,parts,data):
    if path=='/api/experiments/task-start':
        from .task_entry import start
        store=store_for(handler.store)
        with store.lock:result=start(store,data)
        handler.json(result,201 if result['status']=='CREATED' else 200);return True
    if path=='/api/experiments/inverse':
        from .observation_group import create
        store=store_for(handler.store)
        with store.lock:record=create(store,data)
        handler.json(store.public_record(record),201);return True
    if path=='/api/experiments/observations':
        from .observation_workflow import create
        store=store_for(handler.store)
        with store.lock:record=create(store,data)
        handler.json(store.public_record(record),201);return True
    if path in ('/api/experiments/ai/connect','/api/experiments/ai/disconnect'):
        from .ai_binding import manager_for
        binding=manager_for(handler.store)
        if path.endswith('/disconnect'):
            if data:raise WorkflowError('断开连接不接受额外字段')
            result=binding.disconnect()
        else:result=binding.connect(data)
        handler.json(result);return True
    if path=='/api/experiments/library/search':
        from .case_catalog import search,library_digest
        handler.json({'cases':search(data.get('query',''),data.get('domain'),data.get('metric'),data.get('variables')),'library_sha256':library_digest()});return True
    if path=='/api/experiments/library/create':
        from .case_workflow import create
        handler.json(create(store_for(handler.store),data),201);return True
    if path=='/api/experiments/cases':handler.json(store_for(handler.store).create(data),201);return True
    if len(parts)==5 and parts[:3]==['api','experiments','cases'] and parts[4]=='action':
        store=store_for(handler.store);handler.json(store.public_record(store.action(parts[3],data)));return True
    return False
