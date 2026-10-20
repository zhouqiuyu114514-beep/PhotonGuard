"""Standard-library-only package verifier. Does not run AI or optical tools."""
import hashlib,json,sys
from pathlib import Path

def verify(root):
    root=Path(root).resolve();manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError('Invalid package path')
        if path.stat().st_size!=expected['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=expected['sha256']:raise ValueError('Mismatch: '+name)
    return {'status':'PASS','files':len(manifest['files']),'source_commit':manifest['source_commit'],'new_model_calls':0,'new_solver_calls':0}

if __name__=='__main__':print(json.dumps(verify(sys.argv[1]),ensure_ascii=False))
