"""Opt-in, bounded full-vector x-cut ridge modes with independent policy."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,math,resource,subprocess,sys,time,uuid
from ..core import digest,load
from ..runner import clean_environment,verify_evidence
from ..materials.ln_sellmeier import MODEL_ID,dielectric_tensor
from ..mode_verification import verify

POLICY={'version':'mode-xcut-v1','max_neff_grid_delta':.002,'max_neff_domain_delta':.0005,
    'min_overlap_squared':.98,'min_identity_margin':.05,'max_outer_energy_fraction':.05,
    'resource_limits':{'max_worker_wall_seconds':300,'max_total_wall_seconds':1800,'max_memory_mib':2048,'max_worker_processes':6,'max_model_requests':0},
    'max_base_resolution':128,'max_base_domain_um':8,'absolute_efficiency_supported':False}

def finite(value):return type(value) in (int,float) and math.isfinite(value)

def validate_task(task):
    if set(task)!={'schema_version','adapter','task_id','requirements','numerics','provenance'} or task.get('adapter')!='mode-xcut-v1':raise ValueError('模态任务字段不完整。')
    r=task['requirements']
    required={'wavelengths_um','film_thickness_um','slab_thickness_um','ridge_width_um','top_index','bottom_index','orientation','material_model','temperature_c','composition','length_unit'}
    if type(r) is not dict or set(r)!=required:raise ValueError('波长、截面、晶轴、材料组成或温度缺项；不猜。')
    if r['orientation']!='xcut-yprop-v1' or r['material_model']!=MODEL_ID or r['temperature_c']!=21 or r['composition']!='undoped-congruent' or r['length_unit']!='um':raise ValueError('仅支持明确未掺杂21℃、x-cut沿Y传播的教学分支。')
    if not all(finite(r[k]) for k in ('film_thickness_um','slab_thickness_um','ridge_width_um','top_index','bottom_index')) or not .2<=r['film_thickness_um']<=1.2 or not 0<r['slab_thickness_um']<r['film_thickness_um'] or not .5<=r['ridge_width_um']<=2.5 or r['top_index']!=1 or r['bottom_index']!=1.44:
        raise ValueError('首版矩形脊与人工空气/1.44包层范围不支持这些数据。')
    waves=r['wavelengths_um']
    if type(waves) is not list or not 1<=len(waves)<=2 or not all(finite(w) and .4<=w<=5 for w in waves) or len(set(waves))!=len(waves):raise ValueError('首版只求1–2个明确波长，不做密集扫描。')
    for wave in waves:dielectric_tensor(wave)
    n=task['numerics']
    if type(n) is not dict or set(n)!={'resolution','domain_um'} or type(n['resolution']) is not int or not 24<=n['resolution']<=POLICY['max_base_resolution']:raise ValueError('基础网格需24–128。')
    domain=n['domain_um']
    if type(domain) is not list or len(domain)!=2 or not all(finite(d) and 4<=d<=POLICY['max_base_domain_um'] for d in domain):raise ValueError('基础横向域需各4–8微米。')
    if type(task['task_id']) is not str or not task['task_id'] or type(task['provenance']) is not dict or not task['provenance'].get('reference'):raise ValueError('需要独立任务ID及出处。')

def plan_checks(task):
    validate_task(task);n=task['numerics']
    variants=[('base',n['resolution'],n['domain_um']),('grid',round(n['resolution']*1.5),n['domain_um']),('domain',n['resolution'],[d*1.5 for d in n['domain_um']])]
    return [{'variant':name,'resolution':res,'domain_um':domain,'wavelength_um':wave} for name,res,domain in variants for wave in task['requirements']['wavelengths_um']]

def process_limits():
    available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
    bound=min(POLICY['resource_limits']['max_memory_mib']*1024**2,available//2)
    resource.setrlimit(resource.RLIMIT_AS,(bound,bound));resource.setrlimit(resource.RLIMIT_CPU,(300,300));resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024**2,32*1024**2))

def run(task,lock,permit,out_root,*,candidate=None):
    from .registry import verify_permit
    from ..approved_gui import source_manifest
    if candidate is None:
        verify_permit(task,lock,permit);worker_task=task
    else:
        from .. import mode_execution
        mode_execution.verify_permit(task,lock,candidate,permit)
        worker_task=mode_execution.execution_task(task,candidate)
    project_root=Path(__file__).resolve().parents[2];binding=source_manifest(project_root)
    if digest(binding)!=permit['source_binding_sha256']:raise ValueError('批准后的源码已改变；不执行。')
    out=Path(out_root)/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);out.mkdir(parents=True,exist_ok=False)
    for name,value in [('task.json',task),('lock.json',lock),('permit.json',permit),('source-binding.json',binding)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    if candidate is not None:
        for name,value in [('numerical-candidate.json',candidate),('execution-task.json',worker_task)]:
            (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    records=[];attempts=[];start=time.monotonic()
    for step in plan_checks(worker_task):
        remaining=POLICY['resource_limits']['max_total_wall_seconds']-(time.monotonic()-start)
        if remaining<=0:break
        ident=step['variant']+'-'+str(step['wavelength_um']);request=out/(ident+'.request.json');folder=out/ident
        request.write_text(json.dumps({'task':worker_task,'step':step}))
        stdout=out/(ident+'.stdout.log');stderr=out/(ident+'.stderr.log');t=time.monotonic()
        try:
            with stdout.open('w') as stream,stderr.open('w') as errors:
                result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('mpb_worker.py')),str(request),str(folder)],cwd=out,
                    env=clean_environment(),stdout=stream,stderr=errors,timeout=min(300,remaining),preexec_fn=process_limits)
            code=result.returncode
        except subprocess.TimeoutExpired:code='TIMEOUT'
        attempts.append({'step':step,'returncode':code,'wall_seconds':time.monotonic()-t,'automatic_retry':False})
        if code!=0 or not (folder/'result.json').exists():break
        records.append({'variant':step['variant'],'path':str(folder),'result':load(folder/'result.json')})
    verification=verify(records,POLICY) if len(records)==len(plan_checks(worker_task)) else {'verification_status':'INCONCLUSIVE','design_goal_status':'NOT_EVALUATED','checks':[],'mode_inputs':[],'reason':'Bounded worker failed; no retry or fabricated result'}
    report={'schema_version':1,'adapter':task['adapter'],'task_sha256':digest(task),'policy_sha256':digest(POLICY),'confirmation_kind':lock['confirmation_kind'],
        **verification,'worker_attempts':attempts,'solver_kind':'REAL_MPB','actual_worker_processes':len(attempts),
        'solver_counts':{'find_k_invocations':sum(r['result']['solver_counts']['find_k_invocations'] for r in records),
            'eigenproblem_solves':sum(r['result']['solver_counts']['eigenproblem_solves'] for r in records),'fdtd_runs':0},
        'wall_seconds':time.monotonic()-start,'model_requests':0,'source_binding_sha256':digest(binding)}
    if candidate is not None:
        report.update(candidate_sha256=digest(candidate),execution_policy_sha256=digest(mode_execution.POLICY),
            numerical_scope='NUMERICAL_CANDIDATE_ONLY; locked device, QPM goal and verifier unchanged')
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    (out/'manifest.json').write_text(json.dumps({'schema_version':1,'files':files},indent=2))
    for p in out.rglob('*'):
        if p.is_file():p.chmod(0o444)
    for p in sorted(out.rglob('*'),reverse=True):
        if p.is_dir():p.chmod(0o555)
    out.chmod(0o555)
    assert verify_evidence(out)
    return report,out

def qpm_sources(bundle):
    if not verify_evidence(bundle):raise ValueError('模态证据哈希未通过。')
    root=Path(bundle);report=load(root/'report.json');source_sha=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    if report['policy_sha256']!=digest(POLICY):raise ValueError('模态验证策略不一致。')
    task=load(root/'task.json');validate_task(task)
    from .registry import verify_lock
    lock=load(root/'lock.json');verify_lock(task,lock)
    permit=load(root/'permit.json');binding=load(root/'source-binding.json')
    numerical=(root/'numerical-candidate.json').exists()
    if numerical:
        from .. import mode_execution
        candidate=load(root/'numerical-candidate.json');worker_task=mode_execution.execution_task(task,candidate)
        if (load(root/'execution-task.json')!=worker_task or report.get('candidate_sha256')!=digest(candidate)
            or report.get('execution_policy_sha256')!=digest(mode_execution.POLICY)
            or permit.get('candidate_sha256')!=digest(candidate) or permit.get('execution_policy_sha256')!=digest(mode_execution.POLICY)
            or permit.get('phase') not in ('initial','repair') or permit.get('confirmation_kind')!=lock['confirmation_kind']):
            raise ValueError('模态数值候选或独立执行策略变化。')
        if permit['phase']=='initial' and candidate!=mode_execution.initial_candidate(task):raise ValueError('初始候选与任务种子不同。')
        if permit['phase']=='repair':mode_execution.validate_repair_candidate(task,candidate)
    else:worker_task=task
    if (report['task_sha256']!=digest(task) or report['source_binding_sha256']!=digest(binding)
        or permit.get('source_binding_sha256')!=digest(binding) or permit.get('task_sha256')!=digest(task)
        or permit.get('lock_sha256')!=digest(lock) or (not numerical and permit.get('policy_sha256')!=digest(POLICY))
        or permit.get('approved') is not True or permit.get('resource_limits')!=POLICY['resource_limits']):
        raise ValueError('模态任务、批准、源码或资源绑定不一致。')
    records=[]
    for step in plan_checks(worker_task):
        ident=step['variant']+'-'+str(step['wavelength_um']);folder=root/ident
        request=load(root/(ident+'.request.json'))
        if request!={'task':worker_task,'step':step}:raise ValueError('模态数值设置或任务变化。')
        if not (folder/'result.json').exists():continue
        result=load(folder/'result.json')
        if (result['wavelength_um']!=step['wavelength_um'] or result['resolution_pixels_per_um']!=step['resolution']
            or result['domain_um'][:2]!=step['domain_um'] or result.get('requirements')!=task['requirements']):
            raise ValueError('实际模态输出与批准设置不一致。')
        records.append({'variant':step['variant'],'path':str(folder),'result':result})
    recomputed=verify(records,POLICY)
    if any(report.get(k)!=recomputed[k] for k in ('verification_status','checks','mode_inputs')):
        raise ValueError('模态身份/敏感度复核与原报告不一致。')
    inputs=[];receipts={}
    for value in report['mode_inputs']:
        mode={k:value[k] for k in ('wavelength_um','neff','beta_rad_per_um','mode_id','verification_status','neff_sensitivity_estimate')}
        mode.update(source_sha256=source_sha,source=str(root));inputs.append(mode)
        # A bundle contains both wavelengths; receipt catalog keys include identity.
        receipts[source_sha+':'+mode['mode_id']]={**value}
    return inputs,receipts
