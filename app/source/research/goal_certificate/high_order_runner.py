"""One frozen k2/P3 proposal in the autonomous research window."""
import hashlib,json,resource,signal,subprocess,sys,time
from pathlib import Path


def main():
    out=Path(sys.argv[1]);stage=sys.argv[2] if len(sys.argv)>2 else 'E2';dest=out/stage
    plan=json.loads((out/(stage+'-plan.json')).read_text())
    dest.mkdir(exist_ok=True)
    if (dest/'STARTED.json').exists():raise ValueError('NO_STAGE_REPLAY')
    root=Path(__file__).resolve().parents[2];head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if head!=plan['source_commit'] or subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip():raise ValueError('FROZEN_CLEAN_SOURCE')
    for entry in plan['inputs'].values():
        with Path(entry['path']).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=entry['sha256']:raise ValueError('INPUT_HASH_CHANGED')
    cap=2*1024**3;available=int(next(r.split()[1] for r in Path('/proc/meminfo').read_text().splitlines() if r.startswith('MemAvailable:')))*1024
    if cap>available//2 or plan['estimated_peak_bytes']>cap:raise ValueError('MEMORY_PREFLIGHT')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(900,900));signal.alarm(900)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024**2,128*1024**2))
    def dump(name,data):(dest/name).write_text(json.dumps(data,indent=2)+'\n')
    start=time.monotonic();dump('STARTED.json',{'source_commit':head,'started_epoch':time.time(),'memory_bytes':cap,'wall_seconds':900})
    try:
        import numpy as np
        from fractions import Fraction as F
        from . import higher_order_trace as high
        from .convergence_research import solve_forms,diagnostic_map
        from .shared_trace_proposal import calibrate as material_calibration
        with np.load(plan['inputs']['topology']['path'],allow_pickle=False) as z:data={k:z[k] for k in z.files if k!='anchor'}
        model=json.loads(Path(plan['inputs']['model']['path']).read_text());k=float(F(209,100)/F(.775))
        with np.load(plan['inputs']['initial']['path'],allow_pickle=False) as z:old=z['coefficients']
        if stage=='E2':
            coeff=high.prolong_low(data,old)
        else:
            from .graded_trace import graded_mesh,interpolate_high,field_from_coefficients
            field=field_from_coefficients(data,old);data=graded_mesh(model)
            coeff=interpolate_high(data,field)
        dump('material-and-topology-calibration.json',material_calibration(data,model))
        dump('high-order-calibration.json',high.calibrate(data))
        ids,forms=high.assemble_real_forms(data,k)
        phase=high.global_phase(data);z=coeff/phase
        mz=high.apply_real(forms[0],ids,z.real)+1j*high.apply_real(forms[0],ids,z.imag)
        angle=float(np.angle(np.dot(z,mz))/2);aligned=z*np.exp(-1j*angle);initial=aligned.real
        discarded=np.dot(aligned.imag,high.apply_real(forms[0],ids,aligned.imag))/np.vdot(z,mz).real
        dump('phase-representation.json',{'rotation_radians':angle,'discarded_imaginary_energy_fraction':float(discarded),
            'meaning':'New real trial in a real representation of the same Maxwell operator; not an original-record error certificate'})
        np.savez_compressed(dest/'anchor-and-topology.npz',anchor=phase*initial,**data)
        if stage=='E3':
            from .static_condensation import solve as condensed_solve
            x,history,checkpoints=condensed_solve(ids,forms,initial,initial,iterations=10000,outer_limit=3,seconds=760,
                logger=lambda row:print(json.dumps(row),flush=True))
        else:
            x,history,checkpoints=solve_forms(ids,forms,initial,initial,iterations=6000,outer_limit=3,seconds=760,
                logger=lambda row:print(json.dumps(row),flush=True),apply_fn=high.apply_real)
        rho=float(np.dot(x,high.apply_real(forms[1],ids,x))/np.dot(x,high.apply_real(forms[0],ids,x)))
        coeff=phase*x;np.savez_compressed(dest/'proposal.npz',coefficients=coeff)
        dump('history.json',history);dump('checkpoints.json',checkpoints)
        diagnostic,cells,mass=diagnostic_map(data,k,coeff,model,rho,basis=high.local_basis,topology_fn=high.topology,order=5)
        np.savez_compressed(dest/'residual-map.npz',residual_squared_components=cells,mass=mass);dump('diagnostic.json',diagnostic)
        # Local forms are reproducible optimization scratch, not proof inputs.
        # E3 exhausted a per-file cap while caching these; omit this optional
        # cache so bounded persistence covers the actual evidence directory.
        size=sum(p.stat().st_size for p in dest.iterdir() if p.is_file())
        if size>128*1024**2:raise ValueError('PERSISTENT_OUTPUT_CAP')
        dump('FINAL.json',{'status':'FLOATING_STUDY_FINISHED','seconds':time.monotonic()-start,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'output_bytes':size,
            'space_complex_dofs':len(coeff),'real_coefficient_representation':True,
            'new_proposals':1,'new_optimization_form_passes':1,'new_final_continuous_integrations':1,
            'CG_iterations':sum(r['iterations'] for r in history),'outer_iterations':len(history),
            'new_MPB_Meep_API_calls':0,'field_error_certified':False})
        print(json.dumps(diagnostic),flush=True)
    except Exception as exc:
        dump('FAILED.json',{'type':type(exc).__name__,'error':str(exc),'seconds':time.monotonic()-start})
        raise


if __name__=='__main__':main()
