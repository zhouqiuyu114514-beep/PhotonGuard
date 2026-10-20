"""Feature-flagged modes/QPM extension in the existing local three-step workspace."""
import copy,json,os,subprocess,sys,uuid,threading
from pathlib import Path
from .core import load,digest
from .workflow import WorkflowError,write_once,now,PROJECT
from .runner import clean_environment,verify_evidence
from .adapters import registry,mpb_modes,qpm_phase
from . import mode_execution,mode_diagnosis

ACTIONS={'mode-save':{'mode_task','qpm_goal','qpm_source'},
    'mode-confirm-run':{'approve','accept_resources','diagnostic_mode','approve_diagnostic_data'},
    'mode-diagnose':{'diagnostic_mode','approve_diagnostic_data'},
    'mode-reassess':set(),
    'mode-approve-repair':{'approve','card_sha256'},
    'mode-pause':set(),'mode-resume':set(),'mode-new-version':{'reason'}}
GOAL={'process':'SHG','pump_wavelength_um':1.55,'length_um':10,'poling_period_um':20,'qpm_order':1,'target_phase_factor_min':.8}

def validate_goal(goal,task):
    if type(goal) is not dict or not qpm_phase.finite(goal.get('pump_wavelength_um')) or goal['pump_wavelength_um']<=0:
        raise ValueError('基波真空波长未知；请查独立光学过程说明，不从脚本猜。')
    # Validate goal against sourced synthetic mode placeholders without trusting them.
    modes=[{'wavelength_um':w,'neff':n,'beta_rad_per_um':qpm_phase.beta(w,n),'mode_id':str(w),
        'source_sha256':'0'*64,'source':'validation-only-not-evidence','verification_status':'IMPORTED_NOT_VERIFIED','neff_sensitivity_estimate':1}
        for w,n in ((goal.get('pump_wavelength_um',0),1.9),(goal.get('pump_wavelength_um',0)/2,2.1))]
    qpm_phase.validate_task({'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':'goal-structure-validation',
        'requirements':goal,'modes':modes,'provenance':{'reference':'Structure validation only'}})
    if task['requirements']['wavelengths_um']!=[goal['pump_wavelength_um'],goal['pump_wavelength_um']/2]:
        raise ValueError('模态波长与SHG需求顺序不一致；不自动转换。')

class ModePipeline:
    def __init__(self,store,broker=None):self.store=store;self.broker=broker;self.threads={}

    def status(self):
        return {'experimental_enabled':True,'mode':'CONSTRAINED_AI_AND_PHYSICS' if self.broker else 'RULES_AND_PHYSICS_ONLY',
            'ai':self.broker.status() if self.broker else {'live_enabled':False,'mode':'RULES_ONLY'},
            'automatic_model_retry':False,'numerical_repair_only':True}

    def arguments(self,state):
        flow=state['adapter_flow'];result=flow.get('result')
        if not result or result.get('status')!='completed':raise ValueError('没有完整真实证据；不派发模型。')
        registry.verify_lock(flow['mode_task'],flow['mode_lock'])
        if digest(flow['qpm_goal'])!=flow['qpm_goal_sha256']:raise ValueError('独立目标发生变化。')
        candidate=flow.get('candidate') or mode_execution.initial_candidate(flow['mode_task'])
        relative=Path(result['mode_bundle'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('模态证据必须位于当前案例内。')
        bundle=self.store.safe(state['id'],*relative.parts)
        return (flow['mode_task'],flow['mode_lock'],candidate,flow['qpm_goal'],flow['qpm_source'],
            bundle,result.get('qpm_report'))

    def launch_diagnosis(self,state,mode):
        flow=state['adapter_flow'];ident=state['id']
        if flow.get('diagnosis_job') or flow.get('repair_count',0):raise WorkflowError('本份证据已经有诊断预约或修复；不会自动重放。',409)
        self.arguments(state)  # controlled validation before any dispatch marker
        if mode=='live':
            if not self.broker or not flow.get('diagnostic_data_approved'):raise WorkflowError('真实AI需明确资料发送同意和当前源码/费用绑定。',403)
            self.broker.preflight()
        elif mode!='rules':raise WorkflowError('请选择规则或真实AI。')
        flow.setdefault('initial_result',copy.deepcopy(flow['result']))
        flow.setdefault('candidate',mode_execution.initial_candidate(flow['mode_task']))
        flow['selected_diagnostic_mode']=mode;flow['diagnosis_job']={'id':uuid.uuid4().hex,'status':'running','mode':mode,'started_at':now()}
        flow['stage']='DIAGNOSING';state['pipeline']={'status':'DIAGNOSING','message':'根据锁定器件目标和真实场/数值证据诊断；不会自行批准或修改。'}
        self.store._snapshot(state,'mode-diagnosis-start',flow['diagnosis_job']);self.store._save(state)
        thread=threading.Thread(target=self.diagnose,args=(ident,),daemon=True);self.threads[ident]=thread;thread.start()

    def diagnose(self,ident):
        try:
            with self.store.lock:
                state=self.store._load(ident);arguments=self.arguments(state);mode=state['adapter_flow']['selected_diagnostic_mode']
            diagnosis=self.broker.diagnose(*arguments) if mode=='live' else mode_diagnosis.rules_diagnosis(*arguments)
            with self.store.lock:
                state=self.store._load(ident);flow=state['adapter_flow'];flow['diagnosis']=diagnosis
                flow['model_requests']=flow.get('model_requests',0)+(diagnosis.get('provider_attempts',diagnosis.get('actual_model_calls')) or 0)
                flow['diagnosis_job'].update(status='completed',finished_at=now())
                self.store._snapshot(state,'mode-diagnosis-return',diagnosis);self.store._save(state)
                if diagnosis.get('patch'):
                    flow['repair_card']=self.card(state,diagnosis);flow['stage']='AWAITING_APPROVAL'
                    state['pipeline']={'status':'AWAITING_APPROVAL','message':'请审阅这一张数值修复卡；一次批准后自动复验，没有新的模型调用。'}
                else:
                    flow['stage']='RESULT';state['pipeline']={'status':'NO_PATCH','message':'诊断与拒绝/失败均保留；没有自动补写建议或再次调用。'}
                self.store._save(state)
        except Exception:
            with self.store.lock:
                state=self.store._load(ident);flow=state['adapter_flow'];flow['diagnosis_job'].update(status='failed',finished_at=now())
                flow['stage']='RESULT';flow.setdefault('diagnosis',{'status':'FAILED','reason':'MODE_DIAGNOSIS_CONTROLLED_STOP; evidence/fees retained; no automatic retry','patch':None})
                flow['diagnosis_processing_failure']='CONTROLLED_STOP_NO_RETRY'
                state['pipeline']={'status':'FAILED','message':'AI或独立证据核验停止；已有结果和费用保留，没有自动重试。'}
                self.store._snapshot(state,'mode-diagnosis-failure',flow['diagnosis']);self.store._save(state)

    def card(self,state,diagnosis):
        from .approved_gui import source_manifest
        flow=state['adapter_flow'];patch=diagnosis['patch'];candidate=flow.get('candidate') or mode_execution.initial_candidate(flow['mode_task'])
        after=mode_execution.apply_change(flow['mode_task'],candidate,{k:patch['change'][k] for k in ('path','new')})
        return {'schema_version':1,'mode':flow['selected_diagnostic_mode'],'change':patch['change'],
            'why':diagnosis['reason'],'issues':diagnosis.get('issues',[]),'patch_policy_valid':True,
            'explanation_audit_status':diagnosis['explanation_audit_status'],'reverification_status':'NOT_RUN',
            'task_sha256':digest(flow['mode_task']),'qpm_goal_sha256':digest(flow['qpm_goal']),
            'candidate_sha256':digest(candidate),'after_candidate_sha256':digest(after),'patch_sha256':digest(patch),
            'execution_policy_sha256':digest(mode_execution.POLICY),'source_binding':source_manifest(PROJECT),
            'based_on_manifest':patch['based_on_manifest'],'scope':'只改独立数值候选；器件、长度、制造周期、目标与验收器不变。',
            'resources':copy.deepcopy(mpb_modes.POLICY['resource_limits']),
            'output_estimate':mode_execution.output_estimate(flow['mode_task'],after),
            'additional_model_requests':0,'automatic_retry':False,'pass_guaranteed':False}

    def start_worker(self,state,*,phase):
        flow=state['adapter_flow'];ident=uuid.uuid4().hex;base=self.store.case_dir(state['id'])
        receipt='mode-receipt-'+ident+'.json';request=base/('mode-request-'+ident+'.json')
        write_once(request,{'job_id':ident,'receipt':receipt,'flow':copy.deepcopy(flow),'phase':phase})
        flow['stage']='RUNNING';flow['job']={'id':ident,'status':'running','receipt':receipt,'pid':None,'started_at':now(),'phase':phase}
        state['pipeline']={'status':'REVERIFYING' if phase=='repair' else 'CHECKING',
            'message':'按已批准的数值候选完成最多6个真实MPB检查；任务与阈值不变，没有非线性功率仿真。'}
        self.store._save(state)
        try:
            with (base/('mode-'+ident+'.stdout.log')).open('x') as output,(base/('mode-'+ident+'.stderr.log')).open('x') as errors:
                proc=subprocess.Popen([sys.executable,'-B',str(PROJECT/'tools/run_mode_case.py'),str(request)],cwd=PROJECT,
                    env=clean_environment(),stdout=output,stderr=errors,start_new_session=True)
            flow['job']['pid']=proc.pid;self.store.processes[ident]=proc
        except OSError:
            flow['stage']='FAILED';flow['job']['status']='failed';state['pipeline']={'status':'FAILED','message':'工作进程启动失败；原批准和记录保留，不自动重试。'}

    def ensure_solver_slot(self,state):
        if not self.store.allow_workers or not self.store.meep_available:raise WorkflowError('此入口没有启用真实求解。',409)
        for item in self.store.list_cases():
            other=self.store._load(item['id'])
            if (other.get('job') or {}).get('status')=='running' or (other.get('adapter_flow',{}).get('job') or {}).get('status')=='running':
                raise WorkflowError('另一项真实求解仍在运行；先保留当前资料。',409)

    def create_demo(self, workspace_id="default"):
        state=self.store._load(self.store.create('own',workspace_id)['id']);state.update(three_step=True,label='模态/QPM · 公开合成教学例')
        state['adapter_flow']={'mode_task':load(PROJECT/'examples/mode_qpm/ridge.task.json'),'qpm_goal':copy.deepcopy(GOAL),
            'qpm_source':'独立公开合成开发任务卡：预先规定10 μm长度、20 μm制造周期、F≥0.8；不是用户器件',
            'stage':'DRAFT','paused':False,'job':None,'original_requirement_text':'合成x-cut沿晶体Y传播的矩形LN脊波导，在1550/775 nm求模态；以模态值检查事先规定的SHG极化周期与归一化相位因子。目标未达不修改制造参数。',
            'diagnosis_mode':'RULES_AND_PHYSICS_ONLY','model_requests':0}
        self.store._save(state);return self.store.present(state)

    def reconcile(self,state):
        flow=state.get('adapter_flow');job=(flow or {}).get('job')
        diagnosis_job=(flow or {}).get('diagnosis_job')
        if diagnosis_job and diagnosis_job['status']=='running':
            thread=self.threads.get(state['id'])
            if not thread or not thread.is_alive():
                diagnosis_job.update(status='interrupted',finished_at=now());flow['stage']='RESULT'
                state['pipeline']={'status':'INTERRUPTED','message':'诊断工作曾中断；请求与费用保留，没有自动重放。'};self.store._save(state)
            return
        if not job or job['status']!='running':return
        base=self.store.case_dir(state['id']);receipt=base/job['receipt']
        if receipt.exists():
            result=load(receipt)
            if result.get('job_id')!=job['id']:raise WorkflowError('模态运行回执不匹配',409)
            if result['status']=='completed' and not verify_evidence(base/result['mode_bundle']):raise WorkflowError('模态证据哈希变化',409)
            job.update(status=result['status'],finished_at=now());flow['result']=result;flow['stage']='RESULT' if result['status']=='completed' else 'FAILED'
            flow.setdefault('results',[]).append(copy.deepcopy(result))
            if job.get('phase')!='repair' and result['status']=='completed':flow.setdefault('initial_result',copy.deepcopy(result))
            if job.get('phase')=='repair':
                flow['repair_result']={'status':result['status'],'mode_verification':(result.get('mode_report') or {}).get('verification_status'),
                    'qpm_verification':(result.get('qpm_report') or {}).get('verification_status'),
                    'design_goal':(result.get('qpm_report') or {}).get('design_goal_status'),
                    'task_sha256':digest(flow['mode_task']),'qpm_goal_sha256':digest(flow['qpm_goal']),
                    'candidate_sha256':digest(flow['candidate']),'additional_model_requests':0,'original_task_modified':False,
                    'actual_solver_counts':(result.get('mode_report') or {}).get('solver_counts')}
            state['pipeline']={'status':'COMPLETED' if result['status']=='completed' else 'FAILED','message':'实际MPB/QPM结果已保留；没有新增模型调用。'}
            self.store._save(state)
            if (result['status']=='completed' and job.get('phase')!='repair'
                and flow.get('auto_diagnosis') and not flow.get('diagnosis_job')):
                self.launch_diagnosis(state,flow['selected_diagnostic_mode'])
        else:
            if type(job.get('pid')) is not int:
                state['pipeline']['message']='启动预约已保存但没有进程身份；保留阻塞，不自动补启动。'
                return
            try:os.kill(job['pid'],0)
            except ProcessLookupError:
                job['status']='failed';flow['stage']='FAILED';state['pipeline']={'status':'FAILED','message':'工作进程已结束且没有完成回执；保留失败，不自动恢复。'};self.store._save(state)

    def action(self,state,data):
        flow=state['adapter_flow'];kind=data['type'];self.reconcile(state)
        if state.get('mode_evidence_archive') and kind!='mode-new-version':
            raise WorkflowError('这是已完成开发验收的只读迁移记录；旧批准与请求不会重放。需要修改请建立明确的新任务版本。',409)
        if (flow.get('job') or {}).get('status')=='running':raise WorkflowError('当前批准的真实MPB仍在运行；没有重复启动。',409)
        if (flow.get('diagnosis_job') or {}).get('status')=='running':raise WorkflowError('诊断请求正在处理；重复点击未派发。',409)
        if kind=='mode-save':
            if flow.get('mode_lock'):raise WorkflowError('任务已锁定；修改需求请建立新版本。',409)
            if type(data['mode_task']) is not dict or type(data['qpm_goal']) is not dict or type(data['qpm_source']) is not str or not 3<=len(data['qpm_source'])<=4000:
                raise WorkflowError('需要独立任务与QPM来源；未知可保存暂停。')
            flow.update(mode_task=copy.deepcopy(data['mode_task']),qpm_goal=copy.deepcopy(data['qpm_goal']),qpm_source=data['qpm_source'])
            # Saving incomplete input never starts computation or fills missing parameters.
            try:registry.validate_task(flow['mode_task']);validate_goal(flow['qpm_goal'],flow['mode_task'])
            except ValueError as error:flow['validation_message']=str(error)+' 请保留未知，查独立器件任务书。'
            except (TypeError,KeyError):flow['validation_message']='信息缺失或格式不完整；请保留未知，查独立器件任务书。'
            else:flow['validation_message']='资料结构完整，可逐项核对后明确确认。'
            self.store._snapshot(state,'mode-input',copy.deepcopy(flow))
        elif kind=='mode-pause':flow.update(paused=True,stage='PAUSED')
        elif kind=='mode-resume':flow.update(paused=False,stage='DRAFT' if not flow.get('mode_lock') else 'RESULT')
        elif kind=='mode-new-version':
            if type(data.get('reason')) is not str or not 3<=len(data['reason'])<=1000:raise WorkflowError('请说明新任务的原因。')
            child=self.store._load(self.store.create('own',state.get('workspace_id','default'))['id']);child.update(three_step=True,record_type=state.get('record_type','UNCLASSIFIED'),label=state['label']+' · 新任务版本')
            child['adapter_flow']={k:copy.deepcopy(flow[k]) for k in ('mode_task','qpm_goal','qpm_source','original_requirement_text','diagnosis_mode','model_requests')}
            child['adapter_flow'].update(stage='DRAFT',paused=False,job=None,model_requests=0)
            child['parent_version']={'case_id':state['id'],'task_sha256':digest(flow['mode_task']),'qpm_goal_sha256':digest(flow['qpm_goal']),'reason':data['reason'],'at':now()}
            self.store._snapshot(child,'mode-version-parent',child['parent_version']);self.store._save(child);return self.store.present(child)
        elif kind=='mode-confirm-run':
            if flow.get('mode_lock') or flow.get('job'):raise WorkflowError('本任务已确认或启动；不能重复执行。',409)
            if flow['paused'] or data.get('approve') is not True or data.get('accept_resources') is not True:raise WorkflowError('需要本人明确确认任务和限定运行；暂停不会运行。')
            registry.validate_task(flow['mode_task']);validate_goal(flow['qpm_goal'],flow['mode_task'])
            mode=data.get('diagnostic_mode','rules')
            if mode not in ('rules','live'):raise WorkflowError('请选择规则或真实AI诊断。')
            if mode=='live':
                if data.get('approve_diagnostic_data') is not True or not self.broker:raise WorkflowError('需要明确同意发送有限诊断资料和当前AI授权绑定。',403)
                self.broker.preflight()
            candidate=mode_execution.initial_candidate(flow['mode_task'])
            try:size=mode_execution.validate_output_size(flow['mode_task'],candidate)
            except ValueError as error:
                raise WorkflowError('这份数值设置的文件或总输出估计超过当前资源上限。资料已保留，未锁定或启动；需要另做有上限的数值研究，不能保证直接加密就能解决。',409) from error
            self.ensure_solver_slot(state)
            self.store.storage_guard(size['estimated_total_output_bytes'])
            flow['mode_lock']=registry.lock_task(flow['mode_task'],approve=True,confirmation_kind='SIMULATED' if state.get('development_confirmation') else 'USER')
            flow['candidate']=candidate
            flow['permit']=mode_execution.permit(flow['mode_task'],flow['mode_lock'],flow['candidate'],approve=True)
            flow.update(qpm_goal_sha256=digest(flow['qpm_goal']),selected_diagnostic_mode=mode,
                diagnostic_data_approved=data.get('approve_diagnostic_data') is True,auto_diagnosis='diagnostic_mode' in data)
            self.start_worker(state,phase='initial')
        elif kind=='mode-diagnose':
            if flow['paused']:raise WorkflowError('暂停中的任务不会派发诊断。',409)
            flow['diagnostic_data_approved']=data.get('approve_diagnostic_data') is True
            self.launch_diagnosis(state,data.get('diagnostic_mode'))
        elif kind=='mode-reassess':
            from .approved_gui import source_manifest
            old=flow.get('diagnosis') or {}
            if old.get('status')!='REJECTED' or flow.get('repair_count') or flow['paused']:
                raise WorkflowError('只能显式离线重审保留的拒绝返回；不重放模型或重做求解。',409)
            source=source_manifest(PROJECT)
            if flow.get('reassessment_source_commit')==source['git_commit']:raise WorkflowError('当前源码已经重审过；不会重复处理。',409)
            directory=Path(old['evidence_directory'])
            if not directory.is_absolute():directory=PROJECT/directory
            directory=directory.resolve()
            if not directory.is_relative_to(PROJECT/'local-validation') or not directory.name.startswith('mode-request-'):
                raise WorkflowError('原返回不在受控项目证据目录，停止。',409)
            self.store._snapshot(state,'mode-original-rejected-before-reassessment',old)
            flow['reassessment_source_commit']=source['git_commit'];self.store._save(state)
            value=mode_diagnosis.reassess_saved(self.arguments(state),directory)
            flow['diagnosis']=value
            if value.get('patch'):
                flow['repair_card']=self.card(state,value);flow['stage']='AWAITING_APPROVAL'
                state['pipeline']={'status':'AWAITING_APPROVAL','message':'旧安全返回已离线重审；引用规范化有记录，新模型请求0。'}
            else:
                flow['stage']='RESULT';state['pipeline']={'status':'NO_PATCH','message':'旧返回仍被拒绝；已核验部分独立展示，没有新费用或求解。'}
            self.store._snapshot(state,'mode-explicit-reassessment',value)
        elif kind=='mode-approve-repair':
            from .approved_gui import source_manifest
            card=flow.get('repair_card');diagnosis=flow.get('diagnosis') or {};patch=diagnosis.get('patch')
            candidate=flow.get('candidate') or mode_execution.initial_candidate(flow['mode_task'])
            if (data.get('approve') is not True or not card or data.get('card_sha256')!=digest(card)
                or not patch or flow.get('repair_count',0) or flow['paused']):raise WorkflowError('需要明确批准当前这一张卡；旧卡、重复批准或暂停不会执行。',409)
            if (card['source_binding']!=source_manifest(PROJECT) or card['task_sha256']!=digest(flow['mode_task'])
                or card['qpm_goal_sha256']!=digest(flow['qpm_goal']) or card['candidate_sha256']!=digest(candidate)
                or card['patch_sha256']!=digest(patch) or card['execution_policy_sha256']!=digest(mode_execution.POLICY)
                or diagnosis.get('explanation_audit_status')!='VERIFIED_STRUCTURED_CLAIMS'):
                raise WorkflowError('卡片、目标、候选、解释或执行源码绑定变化；旧批准不可用。',409)
            arguments=self.arguments(state);mode_diagnosis.build_request(*arguments)
            if patch['based_on_manifest']!=digest_manifest(arguments[5]):raise WorkflowError('原证据已变化。',409)
            after=mode_execution.apply_change(flow['mode_task'],candidate,{k:patch['change'][k] for k in ('path','new')})
            if digest(after)!=card['after_candidate_sha256']:raise WorkflowError('批准后的数值候选不匹配。',409)
            self.ensure_solver_slot(state);self.store.storage_guard(mode_execution.output_estimate(flow['mode_task'],after)['estimated_total_output_bytes'])
            flow['candidate_before_repair']=copy.deepcopy(candidate);flow['candidate']=after
            flow['repair_approval']={'card_sha256':digest(card),'confirmation_kind':flow['mode_lock']['confirmation_kind'],
                'at':now(),'additional_model_requests':0,'device_goal_changed':False}
            flow['permit']=mode_execution.permit(flow['mode_task'],flow['mode_lock'],after,approve=True,phase='repair',card_sha256=digest(card))
            flow['repair_count']=1;self.store._snapshot(state,'mode-one-repair-approval',flow['repair_approval'])
            self.start_worker(state,phase='repair')
        self.store._save(state);return self.store.present(state)

def digest_manifest(bundle):
    import hashlib
    return hashlib.sha256((Path(bundle)/'manifest.json').read_bytes()).hexdigest()
