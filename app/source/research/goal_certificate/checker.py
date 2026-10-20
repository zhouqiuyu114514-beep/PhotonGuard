"""Local standalone certificate reproduction. No credentials or network.

Prefer the bounded_checker entry point for additional wall-time limits.
The B command performs two local assemblies with a 1GiB/600s hard limit.
"""
import argparse,hashlib,io,json,resource,sys,os
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'

def file_digest(data):return hashlib.sha256(data).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--pump',action='store_true')
    p.add_argument('--trials',type=Path);p.add_argument('--reassemble',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.pump and (a.reassemble or a.trials):p.error('Choose exactly one certificate operation')
    if not a.pump and not (a.reassemble and a.trials):p.error('Choose --pump or --trials PATH --reassemble')
    if a.output and a.output.exists():raise FileExistsError('OUTPUT_ALREADY_EXISTS: no certificate computation started')
    maximum=256*1024**2 if a.pump else 1024**3;seconds=60 if a.pump else 600
    resource.setrlimit(resource.RLIMIT_AS,(maximum,maximum));resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))
    if a.model.stat().st_size>1024**2:raise ValueError('MODEL_SIZE')
    model_bytes=a.model.read_bytes();model=json.loads(model_bytes)
    inputs={'model_file_sha256':file_digest(model_bytes),'trial_file_sha256':None}
    sources={path.name:file_digest(path.read_bytes()) for path in sorted(Path(__file__).parent.glob('*.py'))}
    if a.pump:
        from .pump_slab_envelope import check
        result=check(model)
    else:
        if a.trials.stat().st_size>32*1024**2:raise ValueError('TRIAL_ARCHIVE_SIZE')
        # Hash and load the same immutable byte buffer, avoiding hash/load races.
        trial_bytes=a.trials.read_bytes();inputs['trial_file_sha256']=file_digest(trial_bytes)
        import zipfile
        with zipfile.ZipFile(io.BytesIO(trial_bytes)) as z:
            if sum(e.file_size for e in z.infolist())>64*1024**2:raise ValueError('EXPANDED_TRIAL_SIZE')
        import numpy as np
        from .positive_count_checker import verify
        with np.load(io.BytesIO(trial_bytes),allow_pickle=False) as z:data={key:z[key] for key in z.files}
        result=verify(model,data)
    after={path.name:file_digest(path.read_bytes()) for path in sorted(Path(__file__).parent.glob('*.py'))}
    if after!=sources:raise RuntimeError('CHECKER_SOURCE_CHANGED_DURING_EXECUTION')
    result['execution_binding']={'schema':'certificate-execution-binding-v1',**inputs,
        'implementation_files_sha256':sources,'proof_note_sha256':file_digest(Path(__file__).with_name('PROOF_ZH.md').read_bytes()),
        'python_version':sys.version,'optimization_level':sys.flags.optimize,'debug_checks_enabled':__debug__,
        'numpy_version':None if a.pump else np.__version__,
        'scope':'Input file bytes actually loaded and local checker source; not external provenance attestation or target-mode rank certification'}
    encoded=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.output:
        with a.output.open('x',encoding='utf-8') as f:f.write(encoded)
    else:print(encoded)
    return 0 if result['status'].endswith('_VERIFIED') else 2

if __name__=='__main__':raise SystemExit(main())
