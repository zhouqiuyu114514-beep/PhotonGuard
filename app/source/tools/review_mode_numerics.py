"""Prepare and execute an exact, owner-delegated numerical research window.

No model calls, old repair replay, old evidence editing, or product PASS receipts.
"""
from pathlib import Path
from datetime import datetime,timezone
from multiprocessing import shared_memory
import argparse,copy,hashlib,json,math,os,resource,shutil,subprocess,sys,time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photonguard.core import digest,load
from photonguard.approved_gui import source_manifest
from photonguard.mode_numerical_review import POLICY,make_plan,verify_plan,select_C2,select_C3,continuous_geometry_tensor
from photonguard.materials.ln_sellmeier import dielectric_tensor

ROOT=Path(__file__).resolve().parents[1]
MAIN=Path('/home/zhou/projects/PhotonGuard-development')
LEDGER=MAIN/'local-validation/development-phase-20cny/development-budget.ledger.json'
STUDY=ROOT/'local-validation/mode-precision-study-20261007'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return h.hexdigest()
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def size(folder):return sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
def limits(seconds):
    available=int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))*1024
    bound=min(POLICY['address_space_max_bytes'],available//2)
    resource.setrlimit(resource.RLIMIT_AS,(bound,bound));resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))
    # Stricter than the 8 MiB research envelope: three output files fit a 4 MiB reservation.
    resource.setrlimit(resource.RLIMIT_FSIZE,(1024**2,1024**2))

def input_context():
    old=load(STUDY/'analysis.json');new=load(STUDY/'summary.json');base=[]
    for r,entry in zip((32,48),old['records']):
        base.append({'resolution':r,'folder':entry['source_bundle'],'manifest_sha256':entry['manifest_sha256']})
    for entry in new['results']:
        base.append({'resolution':entry['base_resolution'],'folder':entry['mode_bundle'],
            'manifest_sha256':entry['mode_bundle_manifest_sha256']})
    task=load(STUDY/'plan.json')['parent_task'];goal=load(STUDY/'comparison/comparison.json')['qpm_goal']
    return task,goal,base

def geometry_proof(requirements):
    film=requirements['film_thickness_um'];slab=requirements['slab_thickness_um'];width=requirements['ridge_width_um']
    # Deterministic corners/interfaces and nearby values plus random interior/exterior samples.
    xs=np.r_[-width/2,width/2,-width/2-1e-10,-width/2+1e-10,width/2-1e-10,width/2+1e-10,0,1.9]
    ys=np.r_[-film/2,-film/2+slab,film/2,-film/2-1e-10,-film/2+1e-10,
             -film/2+slab-1e-10,-film/2+slab+1e-10,film/2-1e-10,film/2+1e-10]
    X,Y=np.meshgrid(xs,ys);points=np.r_[np.c_[X.ravel(),Y.ravel()],np.random.default_rng(20261007).uniform(-2,2,(4096,2))]
    results=[]
    for wave in requirements['wavelengths_um']:
        material=dielectric_tensor(wave)
        original=continuous_geometry_tensor(points,requirements,material)
        cap=continuous_geometry_tensor(points,requirements,material,representation='equivalent_cap')
        delta=float(np.max(abs(original-cap)));assert delta==0
        shift=.00625;translated=continuous_geometry_tensor(points+np.array([shift,0]),requirements,material,shift_x=shift)
        # Boundary floating arithmetic can differ at exact equality; compare shifted nonboundary random points.
        translation_delta=float(np.max(abs(original[-4096:]-translated[-4096:])));assert translation_delta==0
        results.append({'wavelength_um':wave,'original_vs_cap_tensor_max_difference':delta,
            'translation_random_point_max_difference':translation_delta})
    return {'analytic_set_identity':'slab [-film/2,-film/2+slab] union ridge [-film/2,film/2] = slab union cap [-film/2+slab,film/2]',
        'boundary_and_corner_points_checked':len(xs)*len(ys),'random_points_checked':4096,'rows':results,
        'physical_requirements_changed':False,'not_a_discrete_operator_equivalence_claim':True}

def tensor_comparison(first,second,requirements):
    diff=abs(second-first);nx,ny=first.shape[-2:];hx=4/nx;hy=4/ny
    x=(np.arange(nx)/nx-.5)*4;y=(np.arange(ny)/ny-.5)*4;X,Y=np.meshgrid(x,y,indexing='ij')
    w=requirements['ridge_width_um'];film=requirements['film_thickness_um'];slab=requirements['slab_thickness_um']
    corner=(abs(abs(X)-w/2)<=2*hx)&((abs(Y+film/2-slab)<=2*hy)|(abs(abs(Y)-film/2)<=2*hy))
    seam=abs(Y)>2-2*hy
    interface=((abs(Y+film/2)<=2*hy)|(abs(Y-film/2)<=2*hy)|(abs(Y+film/2-slab)<=2*hy)|
        ((abs(abs(X)-w/2)<=2*hx)&(abs(Y)<=film/2+2*hy)))
    masks={'corner_or_shoulder':corner,'periodic_y_seam':seam,'flat_interface':interface&~corner&~seam,
           'remaining_interior':~interface&~seam}
    regions={k:{'points':int(m.sum()),'max_abs_difference':float(diff[...,m].max()) if m.any() else 0.,
        'changed_points':int(np.any(diff>1e-12,axis=(0,1,2))[m].sum())} for k,m in masks.items()}
    spatial=diff.max(axis=(0,1,2));changed=np.argwhere(spatial>1e-12)
    locations=[]
    for i,j in sorted(changed.tolist(),key=lambda p:spatial[p[0],p[1]],reverse=True)[:32]:
        locations.append({'grid_index':[i,j],'coordinate_um':[float(x[i]),float(y[j])],
            'max_abs_difference':float(spatial[i,j]),'original_tensors':first[:,:,:,i,j].tolist(),
            'compared_tensors':second[:,:,:,i,j].tolist()})
    # Block maxima retain isolated differences that a stride-only image can miss.
    pooled=spatial.reshape(nx//10,10,ny//10,10).max(axis=(1,3))
    return {'max_abs_difference':float(diff.max()),'component_L1_integral_um2':(diff.sum(axis=(-2,-1))*hx*hy).tolist(),
        'changed_spatial_points':int(np.any(diff>1e-12,axis=(0,1,2)).sum()),'regions':regions,
        'criterion_is_diagnostic_noise_filter_not_neff_acceptance':True,
        'low_resolution_difference_slice':pooled.tolist(),'low_resolution_reduction':'10x10 block maximum, not interpolation',
        'largest_changed_cell_locations':locations,'location_list_truncated':len(changed)>32}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--execute',action='store_true')
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--owner-delegated-plan-sha256')
    parser.add_argument('--recover-from',type=Path)
    args=parser.parse_args();out=args.out.resolve()
    assert out.is_relative_to(ROOT/'local-validation') and args.prepare!=args.execute
    task,goal,baseline=input_context();binding=source_manifest(ROOT)
    if args.prepare:
        assert not out.exists();out.mkdir()
        recovery=None
        if args.recover_from:
            previous=args.recover_from.resolve();assert previous.is_relative_to(ROOT/'local-validation')
            failed=load(previous/'HALTED.json');attempts=failed['attempts']
            assert len(attempts)==1 and attempts[0]['kind']=='initialize' and attempts[0]['returncode']!=0
            oldplan=load(previous/'plan.json');started=load(previous/'execution-started.json')
            original_time=datetime.fromisoformat(started['at_utc']).timestamp()
            recovery={'failed_plan_sha256':digest(oldplan),'failed_source_commit':oldplan['source_binding']['git_commit'],
                'failed_window_directory':str(previous),'failure_record_sha256':sha(previous/'HALTED.json'),
                'carried_initialization_attempts':1,'carried_find_k_attempts':0,
                'reserved_wall_seconds':60,'reserved_output_bytes':4*1024**2,'scope':'I0_I2_C1_ONLY',
                'original_deadline_utc':datetime.fromtimestamp(original_time+3600,timezone.utc).isoformat(),
                'reason':'Explicit new-source recovery after native curfield-buffer precondition fix; failed window remains halted',
                'no_old_source_replay_or_counter_reset':True}
        plan=make_plan(task,goal,baseline,binding,'361bf2a5ecd1add7b92efbc776932e1c99dc5afe48ede2922fddfda58775db13',recovery)
        save(out/'plan.json',plan);save(out/'continuous-geometry-equivalence.json',geometry_proof(task['requirements']))
        print(json.dumps({'plan_sha256':digest(plan),'source_commit':binding['git_commit'],'approval':'NOT_EXECUTED; exact delegated review required'},indent=2));return
    plan=load(out/'plan.json');verify_plan(plan,task,goal,binding)
    assert args.owner_delegated_plan_sha256==digest(plan),'Wrong exact plan review'
    assert not (out/'execution-started.json').exists(),'No automatic retry/resume'
    ledger_sha=sha(LEDGER);state_sha=sha(MAIN/'local-validation/CURRENT_STATE.json')
    main_before={str(p.relative_to(MAIN/'workspace-data')):sha(p) for p in (MAIN/'workspace-data').rglob('*') if p.is_file()}
    assert load(LEDGER)['pending'] is None
    for b in baseline:
        folder=Path(b['folder']);assert sha(folder/'manifest.json')==b['manifest_sha256']
        assert all(sha(folder/p)==value for p,value in load(folder/'manifest.json')['files'].items())
    save(out/'OWNER_DELEGATED_EXACT_PLAN_REVIEW.json',{'confirmation_kind':'SIMULATED','actor':'Codex',
        'authority':'Owner delegation for ordinary local development and bounded revalidation; latest request adopts Pro plan',
        'latest_user_instruction':'按pro意见继续推进',
        'prior_user_instruction':'你直接推进就行，不用找我审批',
        'not_a_claim_of_human_UI_click':True,'plan_sha256':digest(plan),'source_binding_sha256':digest(binding),
        'source_commit':binding['git_commit'],'policy_sha256':digest(POLICY),
        'new_separate_window':True,'old_12_worker_plan_not_extended':True,'additional_API_requests':0,
        'existing_memory_and_workspace_hard_caps_not_increased':True})
    save(out/'execution-started.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'plan_sha256':digest(plan),
        'ledger_sha256':ledger_sha,'canonical_state_sha256':state_sha})
    start=time.monotonic();attempts=[];base_tensors={};tensor_results=[];eigen_results=[]
    recovery=plan.get('recovery')
    if recovery:
        previous=Path(recovery['failed_window_directory'])
        assert sha(previous/'HALTED.json')==recovery['failure_record_sha256']
        assert digest(load(previous/'plan.json'))==recovery['failed_plan_sha256']
        save(out/'EXPLICIT_RECOVERY_MIGRATION.json',recovery)
    env={'PATH':str(Path(sys.executable).parent)+':/usr/bin:/bin','PYTHONNOUSERSITE':'1',
         'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    worker=ROOT/'photonguard/adapters/mpb_research_worker.py'
    def run(kind,setting,*,shm=None,comparison=None):
        assert source_manifest(ROOT)==binding and sha(LEDGER)==ledger_sha
        seconds=POLICY['initialization_seconds_each'] if kind=='initialize' else POLICY['worker_seconds_each']
        held_seconds=recovery['reserved_wall_seconds'] if recovery else 0
        assert time.monotonic()-start+seconds+held_seconds<=POLICY['total_wall_seconds']
        if recovery:assert time.time()+seconds<=datetime.fromisoformat(recovery['original_deadline_utc']).timestamp()
        reserve=4*1024**2
        held_output=recovery['reserved_output_bytes'] if recovery else 0
        assert size(out)+reserve+held_output<=POLICY['persistent_output_max_bytes']
        carried_init=recovery['carried_initialization_attempts'] if recovery else 0
        assert sum(a['kind']=='initialize' for a in attempts)+int(kind=='initialize')+carried_init<=6
        assert sum(a['kind']=='find_k' for a in attempts)+int(kind=='find_k')<=8
        assert size(MAIN/'workspace-data')+POLICY['persistent_output_max_bytes']<=POLICY['existing_workspace_guard_bytes']
        assert shutil.disk_usage(out).free>=POLICY['persistent_output_max_bytes']*1.2
        identifier=setting['id']+'-'+str(setting['wavelength_um']);request={'kind':kind,'plan':plan,'setting':setting}
        if shm is not None:request['shared_memory_name']=shm.name
        if comparison is not None:request['baseline']=comparison
        save(out/(identifier+'.request.json'),request)
        # Reservation is persisted before process creation, never silently released on failure.
        save(out/(identifier+'.reservation.json'),{'kind':kind,'wall_seconds_reserved':seconds,
            'output_bytes_reserved':reserve,'actual_process_started':True,'automatic_retry':False})
        t=time.monotonic()
        with (out/(identifier+'.stdout.log')).open('x') as stdout,(out/(identifier+'.stderr.log')).open('x') as stderr:
            try:
                result=subprocess.run([sys.executable,'-B',str(worker),str(out/(identifier+'.request.json')),str(out/identifier)],
                    cwd=ROOT,env=env,stdout=stdout,stderr=stderr,timeout=seconds,preexec_fn=lambda:limits(seconds))
                code=result.returncode
            except subprocess.TimeoutExpired:code='TIMEOUT'
        attempt={'id':identifier,'kind':kind,'returncode':code,'wall_seconds':time.monotonic()-t,
            'automatic_retry':False,'source_commit':binding['git_commit']};attempts.append(attempt)
        save(out/(identifier+'.attempt.json'),attempt);print(json.dumps(attempt),flush=True)
        assert code==0,'Bounded research failure retained; no automatic retry'
        data=load(out/identifier/'result.json')
        assert data['physical_requirements_sha256']==plan['physical_requirements_sha256'] and data['qpm_goal_sha256']==plan['qpm_goal_sha256']
        return data
    try:
        for setting in plan['initializations']:
            shm=shared_memory.SharedMemory(create=True,size=2*3*3*320*320*8)
            try:
                data=run('initialize',setting,shm=shm)
                arrays=np.ndarray((2,3,3,320,320),dtype=np.float64,buffer=shm.buf).copy()
                if not np.all(np.isfinite(arrays)):raise ValueError('REVIEW_TENSOR_NONFINITE')
                product=np.einsum('ijxy,jkxy->ikxy',arrays[0],arrays[1])
                inverse_error=float(np.max(abs(product-np.eye(3)[:,:,None,None])))
                assert inverse_error<1e-10
                wave=setting['wavelength_um']
                if setting['id']=='I0':base_tensors[wave]=arrays
                else:
                    delta=tensor_comparison(base_tensors[wave],arrays,task['requirements'])
                    tensor_results.append({'id':setting['id'],'wavelength_um':wave,'inverse_product_error':inverse_error,**delta})
            finally:shm.close();shm.unlink()
        save(out/'tensor-comparison.json',{'results':tensor_results,'continuous_equivalence_proof_sha256':sha(out/'continuous-geometry-equivalence.json'),
            'full_tensors_compared_in_RAM_only':True,'no_visualization_scalar_used_as_epsilon_xx':True})
        max_cap=max(r['max_abs_difference'] for r in tensor_results if r['id']=='I2')
        mesh_results=[r['max_abs_difference'] for r in tensor_results if r['id']=='I1']
        max_mesh=max(mesh_results) if mesh_results else None
        c2=select_C2(max_cap,max_mesh) if max_mesh is not None else 'NOT_SELECTED: MESH15_UNTESTED_IN_REDUCED_RECOVERY'
        C=4*math.pi*goal['length_um']/goal['pump_wavelength_um']
        def pair(stage,variant='original',resolution=80,domain=(4,4),shift=False,tight=False,mesh=7):
            result=[]
            for wave in task['requirements']['wavelengths_um']:
                base=next(b for b in baseline if b['resolution']==80)
                original=Path(base['folder'])/(('grid-' if resolution==120 else 'base-')+str(wave))
                setting={'id':stage,'wavelength_um':wave,'resolution':resolution,'domain_um':list(domain),
                    'mesh_size':mesh,'geometry':variant,'shift_x_um':.5/resolution if shift else 0.,
                    'eigen_tolerance':1e-11 if tight else 1e-9,'root_tolerance':1e-11 if tight else 1e-9}
                data=run('find_k',setting,comparison={'folder':str(original)})
                assert data['identity_clear_within_four_bands'],'Unclear mode identity; stop'
                dn=data['selected_mode']['neff']-data['old_selected_mode']['neff']
                item={'stage':stage,'wavelength_um':wave,'delta_neff':dn,'absolute_phase_contribution_rad':C*abs(dn),
                    'signed_phase_contribution_rad':C*dn*(-1 if wave==goal['pump_wavelength_um'] else 1),
                    'identity':data['selected_identity'],'solver_counts':data['solver_counts'],
                    'selected_neff':data['selected_mode']['neff'],'peak_rss_kib':data['peak_rss_kib'],
                    'new_full_field_posthoc_replay_not_available':True}
                eigen_results.append(item);result.append(item)
            return result
        c1=pair('C1',shift=True)
        significant=any(r['absolute_phase_contribution_rad']>POLICY['per_wave_diagnostic_phase_budget_rad'] for r in c1)
        if significant:
            stop='EARLY_STOP: PHYSICAL_TRANSLATION_EQUIVALENCE_BUT_DISCRETE_MODE_PHASE_SENSITIVITY_CONFIRMED'
            unused=['C2','C3','C4']
        elif recovery:
            stop='REDUCED_RECOVERY_COMPLETE: NO_SIGNIFICANT_SHIFT; OTHER_METHODS_NOT_TESTED'
            unused=['I1','C2','C3','C4']
        else:
            c2results=pair('C2',variant='equivalent_cap' if c2=='equivalent_cap' else 'original',mesh=15 if c2=='mesh15' else 7,tight=c2=='tight_tolerance')
            if any(r['absolute_phase_contribution_rad']>.01 for r in c2results):
                stop='EARLY_STOP: PREREGISTERED_OPERATOR_OR_ITERATION_BRANCH_SIGNIFICANT';unused=['C3','C4']
            else:
                c3=select_C3(False,True,c2,max_cap>1e-12,max_mesh>1e-12)
                if c3:pair('C3',variant='equivalent_cap' if c3=='equivalent_cap' else 'original',mesh=15 if c3=='mesh15' else 7,tight=c3=='tight_tolerance')
                pair('C4',domain=(4,6));stop='APPROVED_MENU_COMPLETE_NO_UNIQUE_CAUSE_CERTIFIED';unused=[]
        assert sha(LEDGER)==ledger_sha and sha(MAIN/'local-validation/CURRENT_STATE.json')==state_sha
        assert all(sha(MAIN/'workspace-data'/p)==value for p,value in main_before.items())
        carried_init=recovery['carried_initialization_attempts'] if recovery else 0
        assert sum(a['kind']=='initialize' for a in attempts)+carried_init<=6 and sum(a['kind']=='find_k' for a in attempts)<=8
        summary={'source_commit':binding['git_commit'],'plan_sha256':digest(plan),'policy_sha256':digest(POLICY),
            'physical_requirements_sha256':plan['physical_requirements_sha256'],'qpm_goal_sha256':plan['qpm_goal_sha256'],
            'stop_reason':stop,'unused_stages':unused,'tensor_comparisons':tensor_results,'preselected_C2':c2,
            'eigen_results':eigen_results,'attempts':attempts,'total_wall_seconds':time.monotonic()-start,
            'initialization_processes':sum(a['kind']=='initialize' for a in attempts),
            'find_k_invocations':sum(r['solver_counts']['find_k_invocations'] for r in eigen_results),
            'eigenproblem_solves':sum(r['solver_counts']['eigenproblem_solves'] for r in eigen_results),
            'fdtd_runs':0,'model_requests':0,'full_new_field_arrays_saved':False,
            'research_metric_not_product_receipt':True,'old_QPM_status':'INCONCLUSIVE','old_goal_status':'NOT_EVALUATED',
            'old_workspace_ledger_and_canonical_state_unchanged':True,'stored_bytes_before_summary':size(out)}
        if recovery:
            summary.update(recovery=recovery,cumulative_initialization_attempts=carried_init+summary['initialization_processes'],
                failed_attempts_carried=1,failed_wall_and_output_reservations_retained=True,
                incomplete_B_matrix_mesh15_not_tested=True,
                original_failed_window_still_halted=True)
        save(out/'summary.json',summary)
        print(json.dumps({k:v for k,v in summary.items() if k not in ('eigen_results','attempts','tensor_comparisons')},indent=2))
    except BaseException as error:
        save(out/'HALTED.json',{'reason_type':type(error).__name__,'attempts':attempts,
            'automatic_retry_or_resume':False,'failed_reservations_retained':True,'old_records_not_modified':True})
        raise
if __name__=='__main__':main()
