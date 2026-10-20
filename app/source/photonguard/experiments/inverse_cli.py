"""Explicit portable rerun of a saved inverse request, without AI or simulation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from ..workflow import atomic_json
from .inverse_models import verify_plan


def main():
    parser=argparse.ArgumentParser();parser.add_argument('request');parser.add_argument('--out',required=True);parser.add_argument('--approve',action='store_true');args=parser.parse_args()
    if not args.approve:parser.error('需要 --approve 明确批准一次新本地计算')
    request_path=Path(args.request)
    if request_path.stat().st_size>16*1024**2:raise ValueError('请求文件超限')
    request=json.loads(request_path.read_text());verify_plan(request['plan'])
    if request['plan']['operation']=='profile':
        from ..core import digest
        if digest(request.get('reference'))!=request['plan']['reference_sha256']:raise ValueError('参考结果改变')
    folder=Path(args.out);folder.mkdir(parents=True,exist_ok=False);atomic_json(folder/'request.json',request)
    from .executor import solver_mutex
    from ..runner import clean_environment
    import os
    env=clean_environment();env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    with solver_mutex(),(folder/'worker.log').open('wb') as log:
        proc=subprocess.run([sys.executable,'-B','-m','photonguard.experiments.inverse_worker',str(folder)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=request['plan']['budget']['seconds']+5)
    if proc.returncode:raise SystemExit('未完整完成；保留日志与进度，未重试')
    print('Saved result:',folder/'result.json')


if __name__=='__main__':main()
