"""Bounded standalone upper-count reproduction; no physical solver or API."""
import argparse,hashlib,json,os,resource,signal,sys,ctypes
from pathlib import Path
from fractions import Fraction as F
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--s',required=True);p.add_argument('--f-cut',required=True);p.add_argument('--upper-cap',type=int,required=True);p.add_argument('--M',type=int,default=8);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('OUTPUT_EXISTS_NO_BLOCK_STARTED')
    cap=1024**3;available=int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:')))*1024
    if cap>available//2:raise RuntimeError('AVAILABLE_MEMORY_CAP')
    resource.setrlimit(resource.RLIMIT_AS,(cap,cap));resource.setrlimit(resource.RLIMIT_CPU,(300,300));resource.setrlimit(resource.RLIMIT_FSIZE,(128*1024**2,)*2);resource.setrlimit(resource.RLIMIT_CORE,(0,0));signal.alarm(300)
    if a.M not in (8,12):raise ValueError('ONLY_PREREGISTERED_M8_OR_M12')
    if a.model.stat().st_size>1024**2:raise ValueError('MODEL_SIZE')
    data=a.model.read_bytes();model=json.loads(data)
    import numpy as np
    from .spectral_count_upper import verify_upper_count,require
    require(ctypes.CDLL(None).fegetround()==0,'ROUND_TO_NEAREST')
    require((np.array([[np.nextafter(0.,1.)]])@np.ones((1,1))).item()>0,'GRADUAL_UNDERFLOW')
    source={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in Path(__file__).parent.glob('*.py')}
    a.out.mkdir(parents=True,exist_ok=False)
    try:
        value,artifacts=verify_upper_count(model,a.M,F(a.s),F(a.f_cut),a.upper_cap)
        artifact=a.out/'matrices.npz';np.savez_compressed(artifact,**artifacts)
        after={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in Path(__file__).parent.glob('*.py')};require(source==after,'SOURCE_CHANGED')
        value['execution_binding']={'model_file_sha256':hashlib.sha256(data).hexdigest(),'implementation_sha256':source,'matrix_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'optimization':sys.flags.optimize,'numpy':np.__version__}
        (a.out/'result.json').write_text(json.dumps(value,indent=2));print(json.dumps({'status':value['status'],'upper_count':value['upper_count']}))
        return 0 if value['upper_count'] is not None else 2
    except BaseException as e:
        (a.out/'STOPPED.json').write_text(json.dumps({'status':'STOPPED_NO_RETRY','reason':str(e)}));raise
if __name__=='__main__':raise SystemExit(main())
