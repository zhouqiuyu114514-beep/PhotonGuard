"""Explicit bounded re-run of an exported observation request."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from ..workflow import atomic_json
from .inference import plan
from .executor import solver_mutex


def main():
    p=argparse.ArgumentParser();p.add_argument('request');p.add_argument('--out',required=True);p.add_argument('--approve',action='store_true');a=p.parse_args()
    if not a.approve:p.error('Explicit --approve is required for new computation')
    request=json.loads(Path(a.request).read_text());expected=plan(request['dataset'],request['plan']['settings'])
    if expected!=request['plan']:p.error('Request/plan mismatch')
    from ..core import digest
    dataset=request['dataset']
    if digest({k:v for k,v in dataset.items() if k!='sha256'})!=dataset['sha256']:p.error('Dataset mismatch')
    out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=False);atomic_json(out/'request.json',request)
    from ..runner import clean_environment
    env=clean_environment();env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONPATH=str(Path(__file__).resolve().parents[2])+os.pathsep+str(Path(__file__).resolve().parents[2]/'local-validation/optics-optional-deps'))
    with solver_mutex(),(out/'worker.log').open('wb') as log:
        result=subprocess.run([sys.executable,'-B','-m','photonguard.experiments.inference_worker',str(out)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=request['plan']['settings']['budget']['seconds'])
    if result.returncode:raise SystemExit('Fit stopped; retained progress and log')
    print(json.dumps({'status':'SAVED','output':str(out/'result.json'),'model_calls':0}))

if __name__=='__main__':main()
