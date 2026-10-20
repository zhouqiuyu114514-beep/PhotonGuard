"""Frozen E1 continuation; subsequent proposals need their own stage receipt."""
import json,hashlib,os,resource,signal,subprocess,sys,time
from pathlib import Path


def main():
    out=Path(sys.argv[1]);plan=json.loads((out/'execution-plan.json').read_text());dest=out/'E1'
    dest.mkdir(exist_ok=True)
    if (dest/'STARTED.json').exists():raise ValueError('NO_REPLAY_OR_RESET')
    root=Path(__file__).resolve().parents[2]
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if head!=plan['source_commit'] or subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True).strip():raise ValueError('FROZEN_SOURCE')
    for entry in plan['inputs'].values():
        with Path(entry['path']).open('rb') as s:digest=hashlib.file_digest(s,'sha256').hexdigest()
        if digest!=entry['sha256']:raise ValueError('INPUT_BINDING')
    cap=2*1024**3;avail=int(next(r.split()[1] for r in Path('/proc/meminfo').read_text().splitlines() if r.startswith('MemAvailable:')))*1024
    if cap>avail//2:raise ValueError('MEMORY_CAP_PREFLIGHT')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(900,900))
    resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024**2,128*1024**2));resource.setrlimit(resource.RLIMIT_CORE,(0,0));signal.alarm(900)
    def dump(name,value):(dest/name).write_text(json.dumps(value,indent=2)+'\n')
    start=time.monotonic();dump('STARTED.json',{'source_commit':head,'started_epoch':time.time(),'max_seconds':900,'memory_bytes':cap})
    try:
        import numpy as np
        from fractions import Fraction as F
        from .shared_trace_proposal import assemble_local_forms,apply_local
        from .convergence_research import solve_forms,diagnostic_map
        with np.load(plan['inputs']['topology']['path'],allow_pickle=False) as z:data={k:z[k] for k in z.files if k!='anchor'}
        with np.load(plan['inputs']['anchor']['path'],allow_pickle=False) as z:anchor=z['anchor']
        with np.load(plan['inputs']['initial']['path'],allow_pickle=False) as z:initial=z['coefficients']
        model=json.loads(Path(plan['inputs']['model']['path']).read_text());k=float(F(209,100)/F(.775))
        ids,forms=assemble_local_forms(data,k)
        print(json.dumps({'event':'forms_assembled','seconds':time.monotonic()-start}),flush=True)
        x,history,checkpoints=solve_forms(ids,forms,anchor,initial,iterations=6000,outer_limit=3,seconds=780,
                                         logger=lambda row:print(json.dumps(row),flush=True))
        rho=float((np.vdot(x,apply_local(forms[1],ids,x))/np.vdot(x,apply_local(forms[0],ids,x))).real)
        np.savez_compressed(dest/'proposal.npz',coefficients=x)
        dump('history.json',history);dump('checkpoints.json',checkpoints)
        diagnostic,residual_cells,mass_cells=diagnostic_map(data,k,x,model,rho)
        np.savez_compressed(dest/'residual-map.npz',residual_squared_components=residual_cells,mass=mass_cells)
        dump('diagnostic.json',diagnostic)
        # Cache one assembled form set once; archive size is checked before any
        # future stage can reuse it. This is evidence, never an interval form.
        np.savez_compressed(dest/'floating-local-forms.npz',ids=ids,M=forms[0],N=forms[1],G=forms[2])
        size=sum(p.stat().st_size for p in dest.iterdir() if p.is_file())
        if size>128*1024**2:raise ValueError('PERSISTENT_OUTPUT_CAP')
        dump('FINAL.json',{'status':'FLOATING_STUDY_FINISHED','seconds':time.monotonic()-start,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'output_bytes':size,
            'new_proposals':1,'new_optimization_form_passes':1,'new_final_continuous_integrations':1,
            'outer_iterations':len(history),'CG_iterations':sum(r['iterations'] for r in history),
            'new_MPB_Meep_API_calls':0,'field_error_certified':False})
        print(json.dumps(diagnostic),flush=True)
    except Exception as exc:
        dump('FAILED.json',{'error':str(exc),'type':type(exc).__name__,'seconds':time.monotonic()-start})
        raise


if __name__=='__main__':main()
