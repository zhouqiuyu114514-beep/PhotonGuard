"""Fixed numerical entrypoint under OS limits; never executes uploaded code."""
import json
import os
from pathlib import Path
import sys


def main():
    folder=Path(sys.argv[1]);request=json.loads((folder/'request.json').read_text())
    budget=request['plan']['settings']['budget']
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(budget['memory_mib']*1024**2,)*2)
    resource.setrlimit(resource.RLIMIT_FSIZE,(budget['output_mib']*1024**2//2,)*2)
    resource.setrlimit(resource.RLIMIT_CPU,(budget['seconds'],budget['seconds']+1))
    from ..workflow import atomic_json
    from .inference import fit
    result=fit(request['dataset'],request['plan'],lambda value:atomic_json(folder/'progress.json',value))
    raw=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
    if len(raw)>budget['output_mib']*1024**2//2:raise ValueError('Fit output limit exceeded')
    with (folder/'result.json').open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())


if __name__=='__main__':main()
