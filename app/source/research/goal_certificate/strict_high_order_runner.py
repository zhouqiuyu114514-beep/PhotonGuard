"""Single-use, source-bound outward integration after the floating gate."""
import hashlib,json,resource,signal,subprocess,sys,time
from pathlib import Path
from fractions import Fraction as F


def main():
    out=Path(sys.argv[1]);stage=sys.argv[2] if len(sys.argv)>2 else 'STRICT'
    if stage not in ('STRICT','STRICT-repair1'):raise ValueError('UNKNOWN_STAGE')
    plan_path=out/('strict-plan.json' if stage=='STRICT' else 'strict-repair1-plan.json')
    plan=json.loads(plan_path.read_text());dest=out/stage;dest.mkdir(exist_ok=True)
    if (dest/'STARTED.json').exists():raise ValueError('NO_STRICT_STAGE_REPLAY')
    source=Path(__file__).resolve().parents[2]
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if head!=plan['source_commit'] or subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip():
        raise ValueError('FROZEN_CLEAN_SOURCE')
    for entry in plan['inputs'].values():
        with Path(entry['path']).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=entry['sha256']:raise ValueError('INPUT_HASH_CHANGED')
    cap=2*1024**3;available=int(next(r.split()[1] for r in Path('/proc/meminfo').read_text().splitlines() if r.startswith('MemAvailable:')))*1024
    if cap>available//2:raise ValueError('MEMORY_PREFLIGHT')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(900,900));signal.alarm(900)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024**2,16*1024**2))
    def dump(name,value):(dest/name).write_text(json.dumps(value,indent=2)+'\n')
    start=time.monotonic()
    dump('STARTED.json',{'source_commit':head,'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        'started_epoch':time.time(),'memory_bytes':cap,'wall_seconds':900,'new_strict_integrations':1})
    try:
        import numpy as np
        from .fixed_s_rank_one import verify
        from .strict_high_order_field import integrate,summarize
        model=json.loads(Path(plan['inputs']['model']['path']).read_text())
        diagnostic=json.loads(Path(plan['inputs']['diagnostic']['path']).read_text())
        rho=F(diagnostic['rayleigh'])
        bindings=json.loads(Path(plan['inputs']['rank_one_bindings']['path']).read_text())
        rank=verify(plan['upstream_root'],bindings,rho);dump('rank-one-replay.json',rank)
        if diagnostic['r_over_g']>float(F(139,1000)):raise ValueError('FLOATING_ENTRY_GATE')
        with np.load(plan['inputs']['topology']['path'],allow_pickle=False) as z:data={k:z[k] for k in z.files if k!='anchor'}
        with np.load(plan['inputs']['proposal']['path'],allow_pickle=False) as z:coeff=z['coefficients']
        sums,geometry=integrate(data,coeff,model,rho,logger=lambda row:print(json.dumps(row),flush=True))
        dump('integrals.json',{k:v.export() for k,v in sums.items()})
        result=summarize(sums,rho,model,geometry)
        result['input_bindings']=plan['inputs'];result['rank_one_replay_file']='rank-one-replay.json'
        dump('certificate.json',result)
        dump('FINAL.json',{'status':result['status'],'seconds':time.monotonic()-start,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'output_bytes_before_receipt':sum(p.stat().st_size for p in dest.iterdir() if p.is_file()),
            'new_strict_integrations':1,'new_proposals':0,'new_MPB_Meep_API_calls':0})
        print(json.dumps({'status':result['status'],'r_upper':result['residual_upper'],'q_upper':result['q_upper']}),flush=True)
    except Exception as exc:
        dump('FAILED.json',{'type':type(exc).__name__,'error':str(exc),'seconds':time.monotonic()-start,
            'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'new_strict_integrations_started':1})
        raise


if __name__=='__main__':main()
