"""Fixed analysis subprocess; request contains data, never executable code."""
import json
import os
from pathlib import Path
import sys


def main():
    folder=Path(sys.argv[1]);request=json.loads((folder/'request.json').read_text());p=request['plan']
    from .inverse_models import verify_plan
    verify_plan(p)
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,)*2)
    resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024**2,)*2)
    resource.setrlimit(resource.RLIMIT_CPU,(p['budget']['seconds'],p['budget']['seconds']+1))
    from ..workflow import atomic_json
    from .inverse_profiles import run
    result=run(p,lambda v:atomic_json(folder/'progress.json',v),request.get('reference'))
    raw=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>16*1024**2:raise ValueError('结果超限')
    with (folder/'result.json').open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())


if __name__=='__main__':main()
