"""Source/data/mode identity, computed before reuse of a local listener."""
from pathlib import Path
import subprocess
from .core import digest
import hashlib

def identity(root,data,*,mode,mode_qpm=False,simulation=None):
 root=Path(root).resolve()
 files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ('photonguard','tools') for p in sorted((root/folder).rglob('*')) if p.is_file() and p.suffix in ('.py','.js','.css','.html')}
 try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
 except (OSError,subprocess.CalledProcessError):commit='EXPORTED_SOURCE'
 return {'schema_version':1,'source_root':str(root),'source_commit':commit,'code_sha256':digest(files),
         'data_root':str(Path(data).resolve()),'mode':mode,'mode_qpm':bool(mode_qpm),'simulation':simulation}

def require_match(expected,bootstrap):
 if bootstrap.get('service_identity')!=expected:
  raise ValueError('端口已有服务，但源码、数据目录或运行模式不同；请使用其他端口。没有终止已有服务。')
