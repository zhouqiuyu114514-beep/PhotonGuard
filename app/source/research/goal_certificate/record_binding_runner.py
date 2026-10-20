"""One bounded original-record L2 integration after a certified root tube."""
import hashlib,json,resource,signal,subprocess,sys,time
from pathlib import Path
from fractions import Fraction as F


def main():
    out=Path(sys.argv[1]);plan=json.loads((out/'execution-plan.json').read_text())
    stage=json.loads((out/'record-stage-plan.json').read_text());dest=out/'RECORD';dest.mkdir(exist_ok=True)
    if (dest/'STARTED.json').exists():raise ValueError('NO_RECORD_REPLAY')
    source=Path(__file__).resolve().parents[2];head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if head!=stage['source_commit'] or subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip():raise ValueError('FROZEN_CLEAN_SOURCE')
    for entry in {**plan['inputs'],**stage['inputs']}.values():
        with Path(entry['path']).open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        if digest!=entry['sha256']:raise ValueError('INPUT_HASH_BINDING')
    tube=json.loads((out/'CENTER/root-tube.json').read_text())
    if not tube['root_tube_certified'] or not tube['root_uniqueness']:raise ValueError('CERTIFIED_UNIQUE_ROOT_TUBE_REQUIRED')
    cap=2*1024**3;available=int(next(r.split()[1] for r in Path('/proc/meminfo').read_text().splitlines() if r.startswith('MemAvailable:')))*1024
    if cap>available//2:raise ValueError('MEMORY_PREFLIGHT')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(600,600));signal.alarm(600)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**2,8*1024**2))
    def dump(name,value):(dest/name).write_text(json.dumps(value,indent=2)+'\n')
    start=time.monotonic();dump('STARTED.json',{'source_commit':head,'started_epoch':time.time(),'memory_bytes':cap,'wall_seconds':600,'continuous_record_integration_starts':1})
    try:
        import numpy as np
        from .record_field_distance import integrate_record,distance_bound
        with np.load(plan['inputs']['topology']['path'],allow_pickle=False) as z:data={k:z[k] for k in z.files if k!='anchor'}
        with np.load(stage['inputs']['proposal']['path'],allow_pickle=False) as z:coeff=z['coefficients']
        model=json.loads(Path(plan['inputs']['model']['path']).read_text())
        integrals=integrate_record(data,coeff,model,plan['inputs']['selected_field']['path'],logger=lambda row:print(json.dumps(row),flush=True))
        dump('integrals.json',integrals)
        endpoint=json.loads((out/'CENTER/endpoint-0.json').read_text())
        result=distance_bound(integrals,endpoint['integrals']['mass'],F(tube['tube']['eta_upper_exact']))
        result.update(status='ORIGINAL_SELECTED_RECORD_L2_ASSOCIATED' if result['preregistered_quarter_distance_passes'] and result['unique_dominant_rank_one_component'] else 'RETURNED_RECORD_BINDING_UNPROVEN',
            source_original_record=plan['inputs']['record'],source_original_field=plan['inputs']['selected_field'],
            source_trial=stage['inputs']['proposal'],source_commit=head,root_tube_file='CENTER/root-tube.json')
        dump('record-association.json',result)
        dump('FINAL.json',{'status':result['status'],'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'continuous_record_integrations':1,'new_proposals':0,'new_MPB_Meep_API_calls':0,
            'output_bytes_before_receipt':sum(p.stat().st_size for p in dest.iterdir() if p.is_file())})
        print(json.dumps({'status':result['status'],'distance':result['record_to_eigenstate_distance_upper'],'projection_fraction_lower':result['target_projection_mass_fraction_lower']}),flush=True)
    except Exception as exc:
        dump('FAILED.json',{'type':type(exc).__name__,'error':str(exc),'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss});raise


if __name__=='__main__':main()
