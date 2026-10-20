"""Explicit synthetic-development calibration and MPB→QPM verification. No model API."""
from pathlib import Path
import argparse,copy,hashlib,json,math,subprocess,sys,time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from photonguard.core import load,digest
from photonguard.approved_gui import source_manifest
from photonguard.runner import clean_environment,verify_evidence
from photonguard.adapters import registry,mpb_modes,qpm_phase

def write(path,value):
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)

def analytic_te0(wavelength,film=.6,cladding=1.44):
    from scipy.optimize import brentq
    from photonguard.materials.ln_sellmeier import refractive_index
    core=refractive_index(wavelength,'extraordinary');v=math.pi*film/wavelength*math.sqrt(core**2-cladding**2)
    u=brentq(lambda u:u*math.tan(u)-math.sqrt(max(0,v*v-u*u)),1e-10,min(v,math.pi/2)-1e-10,xtol=1e-14)
    return math.sqrt(core**2-(u*wavelength/(math.pi*film))**2)

def calibration_job(spec_file,out):
    """Private trusted helper branch; the product worker does not expose these options."""
    from photonguard.adapters.mpb_worker import solve
    value=load(spec_file);out=Path(out);out.mkdir(exist_ok=False)
    solve(value['wavelength_um'],value['resolution'],value['domain_um'],out,value['requirements'],
        calibration_slab=value['kind']=='slab',quarter_turn=value['kind']=='rotation')

def run_calibration(spec,out):
    ident=spec['kind']+'-'+str(spec['wavelength_um'])+'-'+str(spec['resolution'])+'-'+str(spec['domain_um'][1])
    spec_file=out/(ident+'.json');write(spec_file,spec);folder=out/ident
    with (out/(ident+'.stdout.log')).open('x') as stream,(out/(ident+'.stderr.log')).open('x') as errors:
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--calibration-job',str(spec_file),'--out',str(folder)],
            env=clean_environment(),stdout=stream,stderr=errors,timeout=300,preexec_fn=mpb_modes.process_limits)
    if result.returncode!=0:raise ValueError('Calibration worker failed; retained logs; no automatic retry.')
    record=load(folder/'result.json')
    if record['selected_mode'] is None:raise ValueError('Calibration has no eligible mode; no fabricated PASS.')
    return record

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--simulated-confirmations',action='store_true');parser.add_argument('--calibration-job',type=Path)
    args=parser.parse_args()
    if args.calibration_job:calibration_job(args.calibration_job,args.out);return
    if not args.simulated_confirmations:parser.error('Development actions require --simulated-confirmations; not a real user approval.')
    binding=source_manifest(ROOT);out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    write(out/'source-binding.json',binding);task=load(ROOT/'examples/mode_qpm/ridge.task.json')
    plan=[{'kind':'slab','wavelength_um':wave,'resolution':res,'domain_um':[0,domain],'requirements':task['requirements']}
        for res,domain in ((128,8),(256,8),(256,10)) for wave in task['requirements']['wavelengths_um']]
    write(out/'calibration-plan.json',{'criteria':{'max_slab_neff_error':2e-5,'max_slab_domain_change':1e-7,'max_coordinate_neff_change':1e-6},'jobs':plan})
    rows=[]
    for spec in plan:
        actual=run_calibration(spec,out);reference=analytic_te0(spec['wavelength_um']);selected=actual['selected_mode']
        rows.append({'spec':spec,'analytic_neff':reference,'mpb_neff':selected['neff'],'absolute_error':abs(reference-selected['neff']),
            'cycles_to_radians_verified':math.isclose(selected['beta_rad_per_um'],2*math.pi*selected['k_cycles_per_um'],rel_tol=1e-12),
            'selected_band':selected['band'],'wall_seconds':actual['wall_seconds'],'solver_counts':actual['solver_counts']})
    domain_changes=[abs(next(r['mpb_neff'] for r in rows if r['spec']['wavelength_um']==w and r['spec']['resolution']==256 and r['spec']['domain_um'][1]==8)
        -next(r['mpb_neff'] for r in rows if r['spec']['wavelength_um']==w and r['spec']['domain_um'][1]==10)) for w in task['requirements']['wavelengths_um']]
    calibration={'slab_rows':rows,'domain_changes':domain_changes,
        'verification_status':'PASS' if max(r['absolute_error'] for r in rows)<2e-5 and max(domain_changes)<1e-7 and all(r['cycles_to_radians_verified'] for r in rows) else 'FAIL',
        'not_a_claim_of_monotonic_convergence':True,'independent_reference':'Scalar principal-axis symmetric TE0 slab dispersion equation, brentq'}
    write(out/'slab-calibration.json',calibration)
    if calibration['verification_status']!='PASS':raise ValueError('Independent slab calibration failed; no ridge acceptance.')
    lock=registry.lock_task(task,approve=True,confirmation_kind='SIMULATED');permit=registry.execution_permit(task,lock,approve=True)
    report,bundle=mpb_modes.run(task,lock,permit,out/'mode-evidence')
    rotation_rows=[]
    for wave in task['requirements']['wavelengths_um']:
        spec={'kind':'rotation','wavelength_um':wave,'resolution':task['numerics']['resolution'],'domain_um':list(reversed(task['numerics']['domain_um'])),'requirements':task['requirements']}
        actual=run_calibration(spec,out);base=load(bundle/('base-'+str(wave))/'result.json')['selected_mode'];turned=actual['selected_mode']
        rotation_rows.append({'wavelength_um':wave,'base_neff':base['neff'],'rotated_neff':turned['neff'],'absolute_difference':abs(base['neff']-turned['neff']),
            'base_band':base['band'],'rotated_band':turned['band'],'rotated_dominant_component':'Ey','geometry_and_tensor_rotated_together':True,
            'solver_counts':actual['solver_counts']})
    rotation_status='PASS' if max(r['absolute_difference'] for r in rotation_rows)<1e-6 else 'FAIL'
    write(out/'coordinate-rotation.json',{'verification_status':rotation_status,'rows':rotation_rows})
    modes,receipts=mpb_modes.qpm_sources(bundle)
    qpm={'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':'SYNTHETIC-SHG-SHORT-FIXED-PERIOD',
        'requirements':{'process':'SHG','pump_wavelength_um':1.55,'length_um':10,'poling_period_um':20,'qpm_order':1,'target_phase_factor_min':.8},
        'modes':modes,'provenance':{'reference':'独立合成开发任务：事先规定长度10 um、制造周期20 um、F≥0.8；不改成最优周期来制造通过',
            'synthetic':True,'mode_task_sha256':digest(task)}}
    qlock=registry.lock_task(qpm,approve=True,confirmation_kind='SIMULATED');qpermit=registry.execution_permit(qpm,qlock,approve=True)
    registry.verify_permit(qpm,qlock,qpermit);result=qpm_phase.evaluate(qpm,verified_mode_sources=receipts)
    for name,value in [('qpm-task.json',qpm),('qpm-lock.json',qlock),('qpm-permit.json',qpermit),('qpm-report.json',result)]:write(out/name,value)
    long=copy.deepcopy(qpm);long['task_id']+='-LONG-INDEPENDENT-DEVELOPMENT-TASK';long['requirements']['length_um']=1000
    long_result=qpm_phase.evaluate(long,verified_mode_sources=receipts)
    write(out/'qpm-long-sensitivity-stop.json',{'task':long,'result':long_result,'original_short_task_unmodified':True})
    counts=[r['solver_counts'] for r in rows+rotation_rows]+[report['solver_counts']]
    summary={'confirmation_kind':'SIMULATED','source_commit':binding['git_commit'],'slab_calibration':calibration['verification_status'],
        'coordinate_rotation':rotation_status,'mode_verification':report['verification_status'],'mode_evidence':str(bundle),
        'qpm_verification':result['verification_status'],'qpm_design_goal':result['design_goal_status'],
        'qpm_long_sensitivity_stop':long_result['verification_status'],'phase_factor_NOT_efficiency':result['phase_factor_NOT_efficiency'],
        'new_paid_model_requests':0,'actual_solver_counts':{key:sum(r[key] for r in counts) for key in ('find_k_invocations','eigenproblem_solves','fdtd_runs')},
        'all_results_preserved':True,'mode_evidence_manifest_verified':verify_evidence(bundle)}
    write(out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
