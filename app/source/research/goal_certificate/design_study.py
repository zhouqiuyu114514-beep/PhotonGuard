"""A separate, frozen synthetic study; never reopens the production window."""
import copy, hashlib, json, os, signal, subprocess, sys, time
from pathlib import Path
from .pump_slab_envelope import check as pump_check
from photonguard.adapters.mpb_modes import validate_task, plan_checks, process_limits
from photonguard.runner import clean_environment

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
    with Path(p).open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2);f.write('\n')
def read(p):return json.loads(Path(p).read_text())
def receipt(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}

def classify(rows):
    usable=[r for r in rows if r.get('d') is not None]
    near=[r['id'] for r in usable if abs(r['d']-.03875)<.001]
    # A bracket is meaningful only along a preregistered one-factor path and
    # with E/H branch identity evidence. The three unrelated axes are not one.
    return {'near_target_candidates':near,'bracket_confirmed':False,
            'status':'LOCAL_PROPOSAL_GATE_OPEN' if near else 'NO_FEASIBLE_CANDIDATE_OBSERVED_IN_THIS_WINDOW'}

def run(out,baseline,model_path):
    out=Path(out);out.mkdir(exist_ok=False)
    source=Path(__file__).resolve().parents[2];base=read(Path(baseline)/'task.json')
    model=read(model_path);tasks=[]
    for ident,key,value in [('G-W','ridge_width_um',2.2),('G-S','slab_thickness_um',.45),('G-H','film_thickness_um',.9)]:
        task=copy.deepcopy(base);task['task_id']='SYNTHETIC-DESIGN-20261010-'+ident
        task['requirements'][key]=value
        task['provenance']={'reference':'20261010 adopted bounded three-design study; '+ident,'synthetic':True,'baseline_task_sha256':sha(Path(baseline)/'task.json')}
        validate_task(task);tasks.append((ident,task))
    sources={str(p.relative_to(source)):sha(p) for p in (source/'photonguard').rglob('*.py')}
    sources[str(Path(__file__).relative_to(source))]=sha(Path(__file__))
    plan={'schema_version':1,'window':'SYNTHETIC-DESIGN-20261010','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
        'implementation_sha256':sources,'baseline_task':receipt(Path(baseline)/'task.json'),'original_model':receipt(Path(model_path)),
        'tasks':dict(tasks),'goal':{'length_um':1000,'period_um':20,'order':1,'phase_factor_target':.8,'phase_budget_rad':.1},
        'initial_workers':6,'conditional_total_cap':16,'total_seconds':4800,'per_worker_seconds':300,
        'memory_bytes':'min(2GiB,MemAvailable/2)','output_bytes':768*1024**2,'file_bytes':32*1024**2,
        'paid_model_calls':0,'FDTD':0,'retry':False,'followup_requires_separate_frozen_plan_and_branch_gate':True}
    save(out/'execution-plan.json',plan)
    save(out/'STARTED.json',{'plan_sha256':sha(out/'execution-plan.json'),'pid':os.getpid(),'time':time.time()})
    start=time.monotonic();attempts=[];rows=[]
    for ident,task in tasks:
        root=out/ident;root.mkdir();save(root/'task.json',task)
        newmodel=copy.deepcopy(model);newmodel['task']=task
        # The new model has no inherited selected result or task hash.
        newmodel['task_file_sha256']=sha(root/'task.json');newmodel['material_result_hashes']={}
        newmodel['design_study_id']=task['task_id'];save(root/'model.json',newmodel)
        save(root/'pump-applicability.json',pump_check(newmodel));results=[]
        for step in plan_checks(task)[:2]:
            if time.monotonic()-start>=4800:raise TimeoutError('STUDY_WALL_CAP')
            if any(sha(source/p)!=digest for p,digest in sources.items()):raise ValueError('FROZEN_IMPLEMENTATION_CHANGED')
            used=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
            if used+6*32*1024**2>plan['output_bytes']:raise ValueError('OUTPUT_RESERVATION_CAP')
            key='base-'+str(step['wavelength_um']);request=root/(key+'.request.json');dest=root/key
            save(request,{'task':task,'step':step});attempt={'id':ident,'step':step,'start_time':time.time()}
            save(root/(key+'.STARTED.json'),attempt);t=time.monotonic()
            with (root/(key+'.stdout.log')).open('x') as log,(root/(key+'.stderr.log')).open('x') as err:
                proc=subprocess.Popen([sys.executable,'-B',str(source/'photonguard/adapters/mpb_worker.py'),str(request),str(dest)],
                    cwd=out,env=clean_environment(),stdout=log,stderr=err,preexec_fn=process_limits,start_new_session=True)
                try:code=proc.wait(timeout=min(300,4800-(time.monotonic()-start)))
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait();code='TIMEOUT'
            attempt.update(returncode=code,seconds=time.monotonic()-t,automatic_retry=False);attempts.append(attempt)
            save(root/(key+'.FINISHED.json'),attempt)
            if code==0 and (dest/'result.json').is_file():results.append(read(dest/'result.json'))
            print(json.dumps(attempt),flush=True)
            if any(p.stat().st_size>32*1024**2 for p in out.rglob('*') if p.is_file()):raise ValueError('FILE_CAP')
            if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>plan['output_bytes']:raise ValueError('AGGREGATE_CAP')
        selected={r['wavelength_um']:r['selected_mode'] for r in results}
        d=selected[.775]['neff']-selected[1.55]['neff'] if all(selected.get(w) for w in (1.55,.775)) else None
        rows.append({'id':ident,'task_id':task['task_id'],'model_sha256':sha(root/'model.json'),'d':d,
            'residual':None if d is None else d-.03875,'selected':selected,'eligible_both':d is not None,
            'strict_certificate':'NOT_STARTED','numerical_policy':'NOT_EVALUATED_BASE_ONLY'})
    gate=classify(rows)
    old=[read(Path(baseline)/('base-'+str(w))/'result.json') for w in (1.55,.775)]
    baseline_d=old[1]['selected_mode']['neff']-old[0]['selected_mode']['neff']
    # These one-factor samples can bracket the baseline only if their residual
    # has opposite sign. Any such case needs field tracking before continuation.
    possible=[r['id'] for r in rows if r['d'] is not None and (r['d']-.03875)*(baseline_d-.03875)<0]
    if possible:gate.update(status='BRANCH_TRACKING_REQUIRED',possible_brackets=possible)
    result={'status':gate['status'],'candidates':rows,'gate':gate,'baseline_d':baseline_d,
        'baseline_results':[receipt(Path(baseline)/('base-'+str(w))/'result.json') for w in (1.55,.775)],
        'attempts':attempts,'actual_workers':len(attempts),'seconds':time.monotonic()-start,
        'paid_API_calls':0,'FDTD':0,'all_geometry_impossible_claimed':False,'phase_factor_is_efficiency':False}
    save(out/'result.json',result)
    save(out/'MANIFEST.json',{'files':{str(p.relative_to(out)):receipt(p) for p in out.rglob('*') if p.is_file()}})
    return result

if __name__=='__main__':
    run(*sys.argv[1:])
