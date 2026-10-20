"""Three-step orchestration. User approval precedes task lock and repair/run."""
import copy
from datetime import datetime,timezone
from pathlib import Path
import threading
import time
import uuid

from .agent import propose_patch
from .core import digest,load,POLICY_HASH,verify_lock
from .runner import verify_evidence
from .script_import import preview_bytes,validate_provenance,MAX_BYTES
from .task_mapping import project
from . import workflow_intake as intake_api

ACTIVE={'CHECKING','DIAGNOSING','REVERIFYING'}

class ThreeStepPipeline:
    def __init__(self,store,broker=None):
        self.store=store;self.broker=broker;self.local=threading.local();self.threads={}
    def internal(self):return getattr(self.local,'internal',False)
    def legacy(self,ident,kind,**data):
        self.local.internal=True
        try:
            state=self.store.get(ident)
            return self.store.action(ident,{'type':kind,'expected_revision':state['revision'],**data})
        finally:self.local.internal=False
    def snapshot(self,state,prefix,value):
        self.store._snapshot(state,prefix,value);self.store._save(state)
    def action(self,state,data):
        from .workflow import WorkflowError
        ident=state['id'];kind=data['type']
        if state.get('pipeline',{}).get('status') in ACTIVE:
            raise WorkflowError('后台正在完成本轮检查；重复点击没有派发。',409)
        if kind=='start-review':
            if state['approval'] or state.get('pipeline'):
                raise WorkflowError('这份任务已有检查记录；不会重放。修改需求请建新版本。',409)
            if data.get('approve') is not True or data.get('accept_initial_checks') is not True:
                raise WorkflowError('请明确确认需求，并允许这轮限定检查。',422)
            mode=data.get('diagnostic_mode')
            if mode not in ('rules','live'):raise WorkflowError('请选择规则或真实AI诊断。',422)
            if mode=='live':
                if data.get('approve_diagnostic_data') is not True or not self.broker:
                    raise WorkflowError('真实AI需明确同意发送有限诊断数据且服务端已绑定授权。',403)
                try:self.broker.preflight()
                except (ValueError,OSError):raise WorkflowError('模型源码、费用或密钥绑定不可用；没有锁定、派发或重置账本。',409) from None
            current=state.get('intake')
            if not current or data.get('result_sha256')!=current.get('result_sha256'):
                raise WorkflowError('当前草稿不存在或已变化；请重新读取资料。',409)
            try:
                semantic=intake_api.apply(current,{'type':'intake-confirm','approve':True,'result_sha256':data['result_sha256']})
                task,mapping,context=project(semantic,data.get('options'))
                source=data.get('source')
                if type(source) is not str or len(source.encode())>MAX_BYTES:raise ValueError('请提供支持范围内的有限脚本。')
                preview=preview_bytes(source.encode(),'film_scan.py')
                if preview['status']!='EXTRACTED':raise ValueError('脚本不受支持：'+preview['unresolved'][0]['reason'])
                validate_provenance(preview['candidate'],task)
            except (ValueError,TypeError,KeyError) as exc:raise WorkflowError(str(exc),422) from None
            if not self.store.allow_workers or not self.store.meep_available:
                raise WorkflowError('真实Meep环境不可用；没有确认任务。',503)
            # All validation precedes side effects. One explicit user action covers
            # semantic review, mapping, lock and only the first bounded check.
            state.update(intake=semantic,task=task,task_reviewed=True,context=context,
                context_reviewed=True,context_unknown_fields=[],mapping_review=mapping,
                diagnostic_mode=mode,three_step=True)
            self.snapshot(state,'one-user-task-review',{'result_sha256':data['result_sha256'],
                'mapping':mapping,'mode':mode,'initial_meep_runs_max':8,
                'model_requests_max':1 if mode=='live' else 0,'repair_approved':False,
                'diagnostic_data_explicitly_approved':mode=='live'})
            self.legacy(ident,'import',name='film_scan.py',source=source)
            self.legacy(ident,'confirm',approve=True)
            state=self.store._load(ident)
            state['pipeline']={'status':'CHECKING','phase':'initial','operation_id':uuid.uuid4().hex,
                'message':'正在后台解析并完成必要Meep检查；不会自动应用修复。'}
            self.snapshot(state,'pipeline-start',state['pipeline'])
            self.launch(ident,'initial')
            return self.store.present(state)
        if kind=='approve-repair':
            card=state.get('repair_card')
            if (data.get('approve') is not True or not card or data.get('card_sha256')!=digest(card)
                    or state.get('repair_permit') or not state.get('proposal')):
                raise WorkflowError('需要批准当前这一张修复卡；旧卡或重复批准不能执行。',409)
            task=state['task'];patch=state['proposal'];candidate=state['candidate']
            explanation = card.get('explanation_audit_status')
            if explanation in ('UNSUPPORTED', 'UNVERIFIED_LEGACY_TEXT') and data.get('acknowledge_explanation_warning') is not True:
                raise WorkflowError('模型说明含未支持断言；请审阅事实和审计警告后明确批准，旧批准不沿用。',422)
            if (card['task_sha256']!=digest(task) or card['candidate_sha256']!=digest(candidate)
                    or card['patch_sha256']!=digest(patch) or card['policy_sha256']!=POLICY_HASH
                    or not verify_lock(task,load(self.store.safe(ident,'task.lock.json')))):
                raise WorkflowError('任务、配方、修复卡或阈值绑定已变化；停止。',409)
            from .approved_gui import source_manifest
            if source_manifest(self.store.project_root)!=card['source_binding']:
                raise WorkflowError('执行源码已变化；请重新审阅新版本，旧批准不覆盖它。',409)
            permit={'card_sha256':digest(card),'task_sha256':digest(task),'patch_sha256':digest(patch),
                'max_fresh_fdtd_runs':8,'additional_model_requests':0,'status':'APPROVED',
                'explanation_audit_status':explanation,
                'explanation_warning_acknowledged':data.get('acknowledge_explanation_warning') is True,
                'at':datetime.now(timezone.utc).isoformat()}
            state['repair_permit']=permit
            state['pipeline']={'status':'REVERIFYING','phase':'repair','message':'按已批准的这一项修改自动应用并完成8次以内Meep复验。'}
            self.snapshot(state,'one-repair-approval',permit)
            self.launch(ident,'repair')
            return self.store.present(state)
        if kind=='retry-check':
            pipeline=state.get('pipeline') or {}
            if (data.get('approve') is not True or pipeline.get('status')!='FAILED'
                    or pipeline.get('phase')!='initial' or state.get('job',{}).get('status')!='failed'):
                raise WorkflowError('只能明确重试未完成的初次求解；模型失败不自动重试。',409)
            state['pipeline']={'status':'CHECKING','phase':'initial','message':'显式重试初次求解；旧失败保留。'}
            self.snapshot(state,'explicit-check-retry',state['pipeline']);self.launch(ident,'initial')
            return self.store.present(state)
        if kind=='resume-rule-review':
            pipeline=state.get('pipeline') or {}
            if (state.get('diagnostic_mode')!='rules' or pipeline.get('status')!='FAILED'
                    or pipeline.get('phase')!='initial' or state.get('job',{}).get('status')!='completed'
                    or not state.get('runs') or state.get('repair_permit')):
                raise WorkflowError('只能显式恢复已完成数值检查的规则审阅；不重放模型或求解。',409)
            run=state['runs'][-1];path=self.store.case_dir(ident)/'artifacts'/run['run_id']
            if not verify_evidence(path):raise WorkflowError('旧证据完整性未通过，停止。',409)
            report=load(path/'report.json')
            from .approved_gui import source_manifest
            source_manifest(self.store.project_root)  # committed source required
            patch=propose_patch(state['task'],state['candidate'],report)
            diagnosis={'status':'PROPOSED' if patch else 'NO_PATCH','reason':patch['rationale'] if patch else '规则没有可安全提出的修复。',
                'actual_model_calls':0,'issues':[],'mode':'DETERMINISTIC_RULES','recovered_existing_evidence':run['run_id']}
            state.update(diagnosis=diagnosis,proposal=patch)
            if patch:
                state['repair_card']=self.card(state,patch,diagnosis)
                state['pipeline'].update(status='AWAITING_APPROVAL',message='已恢复原数值证据的规则审阅；没有重跑求解或模型，需批准当前修复卡。')
            else:state['pipeline'].update(status='NO_PATCH',message='旧证据没有安全单项修复；未重复运行。')
            self.snapshot(state,'explicit-rule-review-recovery',{'evidence_run_id':run['run_id'],'model_calls':0,'fresh_solver_runs':0})
            return self.store.present(state)
        raise WorkflowError('未知三步流程操作',422)
    def launch(self,ident,phase):
        thread=threading.Thread(target=self.run,args=(ident,phase),daemon=True)
        self.threads[ident]=thread;thread.start()
    def wait_solver(self,ident):
        self.legacy(ident,'run')
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            time.sleep(.25)
            state=self.store.get(ident)
            if state['job']['status']=='completed':return state
            if state['job']['status']=='failed':raise ValueError('Solver did not produce completed evidence')
        raise ValueError('Bounded solver completion deadline exceeded')
    def card(self,state,patch,diagnosis):
        from .approved_gui import source_manifest
        locations=state['candidate']['origin']['script_import']['source_locations']
        changes=[]
        for c in patch['changes']:
            key='.'.join(str(v) for v in c['path'])
            changes.append({**c,'source_locations':locations.get(key,[])})
        return {'schema_version':1,'mode':state['diagnostic_mode'],'changes':changes,
            'why':patch['rationale'],'issues':diagnosis.get('issues',[]),
            'patch_policy_valid':True,'reverification_status':'NOT_RUN',
            'explanation_audit_status':diagnosis.get('explanation_audit_status','DETERMINISTIC_RULE_TEXT'),
            'explanation_audit':diagnosis.get('explanation_audit'),
            'task_sha256':digest(state['task']),'candidate_sha256':digest(state['candidate']),
            'patch_sha256':digest(patch),'policy_sha256':POLICY_HASH,
            'source_binding':source_manifest(self.store.project_root),
            'scope':'仅修规范化配方，原脚本保留；不是已修复原脚本。',
            'reverification':{'max_fdtd_runs':8,'max_seconds_per_pair':65,'max_memory_mib':1536,
                'mandatory':'原设置、网格、时间、PML四组参考/目标配对和独立tmm验收',
                'additional_model_calls':0},'new_modifications_require_new_approval':True,
            'based_on_run':patch['based_on_run']}
    def run(self,ident,phase):
        try:
            if phase=='repair':
                self.legacy(ident,'apply',approve=True)
                with self.store.lock:
                    state=self.store._load(ident);state['repair_permit']['status']='APPLIED'
                    self.store._save(state)
            state=self.wait_solver(ident)
            path=self.store.case_dir(ident)/'artifacts'/state['runs'][-1]['run_id']
            if not verify_evidence(path):raise ValueError('Evidence integrity failed')
            report=load(path/'report.json')
            if phase=='repair':
                with self.store.lock:
                    state=self.store._load(ident);state['repair_permit']['status']='COMPLETED'
                    state['pipeline'].update(status='RESULT',message='限定复验已完成；结果不通过时也保留，不自行追加修改。')
                    state['repair_result']={'status':report['status'],'run_id':report['run_id'],
                        'patch_policy_valid':True,'reverification_status':report['status'],
                        'explanation_audit_status':state.get('diagnosis',{}).get('explanation_audit_status','DETERMINISTIC_RULE_TEXT'),
                        'candidate_sha256':report['candidate_hash'],'scope':'CANONICAL_RECIPE_ONLY',
                        'source_script_modified':False,'download_ready':True}
                    self.snapshot(state,'one-approval-result',state['repair_result'])
                return
            if report['status']!='FAIL':
                with self.store.lock:
                    state=self.store._load(ident)
                    state['initial_result']={'status':report['status'],'run_id':report['run_id'],
                        'download_ready':True,'repair_applied':False,'design_goal_status':'NOT_EVALUATED'}
                    message={'PASS':'初次计算已通过限定数值检查，可以查看曲线和下载结果。',
                        'INCONCLUSIVE':'初次计算检查已结束，但证据不足以判断通过；请查看未决项。',
                        'UNSUPPORTED':'这份任务或输入超出当前检查范围；请查看具体范围说明。'}.get(report['status'],'初次检查已结束；请按报告状态查看结果。')
                    state['pipeline'].update(status='RESULT',message=message)
                    self.snapshot(state,'initial-no-repair',state['initial_result'])
                return
            with self.store.lock:
                state=self.store._load(ident);state['pipeline'].update(status='DIAGNOSING',message='正在根据锁定任务、AST位置和实际证据生成诊断。')
                self.store._save(state)
            if state['diagnostic_mode']=='live':
                diagnosis=self.broker.diagnose(path)
                patch=diagnosis.get('patch')
            else:
                patch=propose_patch(state['task'],state['candidate'],report)
                diagnosis={'status':'PROPOSED' if patch else 'NO_PATCH','reason':patch['rationale'] if patch else '规则没有可安全提出的修复。',
                    'actual_model_calls':0,'issues':[],'mode':'DETERMINISTIC_RULES'}
            with self.store.lock:
                state=self.store._load(ident);state['diagnosis']=diagnosis;state['proposal']=patch
                if patch:
                    state['repair_card']=self.card(state,patch,diagnosis)
                    state['pipeline'].update(status='AWAITING_APPROVAL',message='请审阅这一项修复；批准后自动应用并限定复验。')
                else:
                    state['pipeline'].update(status='NO_PATCH',message='诊断未得到可批准修复；原因与失败证据保留，没有规则补写或自动重试。')
                self.snapshot(state,'diagnosis-return',diagnosis)
        except Exception:
            with self.store.lock:
                state=self.store._load(ident)
                state.setdefault('pipeline',{}).update(status='FAILED',phase=phase,message='本轮停止。失败证据与费用预留保留；未自动重试、修改目标或追加修复。')
                self.snapshot(state,'pipeline-failure',{'phase':phase,'generic_reason':'CONTROLLED_PIPELINE_STOP'})
