"""Fixed-entrypoint bounded numerical worker; request files contain only JSON."""
import json
import os
from pathlib import Path
import sys

def main():
    request_path,out_path=map(Path,sys.argv[1:])
    request=json.loads(request_path.read_text(encoding='utf-8'))
    import resource
    memory=request['memory_mib']*1024*1024
    resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
    resource.setrlimit(resource.RLIMIT_FSIZE,(request['output_mib']*1024*1024,)*2)
    resource.setrlimit(resource.RLIMIT_CPU,(request['seconds'],request['seconds']+1))
    from .registry import evaluate
    result=evaluate(request['domain'],request['parameters'])
    raw=json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    if len(raw)>request['output_mib']*1024*1024:raise ValueError('Worker output exceeded bound')
    with out_path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())

if __name__=='__main__':main()
