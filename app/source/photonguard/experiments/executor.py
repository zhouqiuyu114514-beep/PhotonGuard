"""Sequential, finite-candidate execution with explicit resource and evidence receipts."""
from __future__ import annotations
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from ..core import digest, write_json
from .planner import build_plan
from .goals import assess,rank
_MUTEX_STATE=threading.local()

class SolverBusyError(ValueError):
    """The atomic shared solver lock was not acquired; no worker started."""

@contextmanager
def solver_mutex():
    if getattr(_MUTEX_STATE,'held',False):
        yield
        return
    import fcntl
    path=Path(tempfile.gettempdir())/f'photonguard-{os.getuid()}-solver.lock'
    with path.open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SolverBusyError('本机已有光学求解任务，请等待完成后运行') from None
        _MUTEX_STATE.held=True
        try:yield
        finally:
            _MUTEX_STATE.held=False
            fcntl.flock(f,fcntl.LOCK_UN)

def execute_plan(plan,out_dir):
    expected=build_plan(plan['spec'])
    if expected!=plan:raise ValueError('计划或计算参数与已核对规格不一致')
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=False)
    write_json(out/'plan.json',plan)
    budget=plan['resource_budget'];d=plan['domain'];rows=[];started=time.monotonic()
    usage={'fast_evaluations':0,'actual_fdtd_runs':0,'fdtd_attempts_reserved':0,'cache_hits':0,'output_bytes':0,'model_calls':0}
    with solver_mutex():
        for candidate in plan['candidates']:
            row=copy.deepcopy(candidate);folder=out/candidate['id'];folder.mkdir()
            # Reserve half for the aggregate and 8 MiB for logs/Meep/manifests.
            remaining_mib=int(((budget['output_mib']-8)*1024*1024/2-usage['output_bytes'])//(1024*1024))
            if remaining_mib<1:
                row.update(status='RESOURCE_STOP',error='本批证据空间预留已满');rows.append(row);break
            request={'domain':d,'parameters':candidate['parameters'],'memory_mib':budget['worker_memory_mib'],'output_mib':remaining_mib,'seconds':budget['worker_seconds']}
            write_json(folder/'request.json',request)
            planned_cost=2 if d=='diffraction' else 1
            if usage['fast_evaluations']+planned_cost>budget['max_fast_evaluations']:
                row.update(status='RESOURCE_STOP',error='本批快速计算上限已到');rows.append(row);break
            # Reserve attempts before launch: a failed field calculation is still work.
            usage['fast_evaluations']+=planned_cost
            from ..runner import clean_environment
            env=clean_environment();env['PYTHONDONTWRITEBYTECODE']='1'
            source=Path(__file__).resolve().parents[2]
            env['PYTHONPATH']=str(source)+os.pathsep+str(source/'local-validation/optics-optional-deps')
            try:
                with (folder/'worker.log').open('wb') as log:
                    proc=subprocess.run([sys.executable,'-B','-m','photonguard.experiments.worker',str(folder/'request.json'),str(folder/'result.json')],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=budget['worker_seconds'])
                if proc.returncode:raise ValueError('受限工作进程失败；保留原日志')
                size=(folder/'result.json').stat().st_size
                usage['output_bytes']+=size
                value=json.loads((folder/'result.json').read_text(encoding='utf-8'))
                row.update(value);row.update(status='RUN_COMPLETED',goal=assess(value,plan['goal']),evidence={'path':str(folder/'result.json'),'sha256':hashlib.sha256((folder/'result.json').read_bytes()).hexdigest()})
                if d=='diffraction':
                    # Full diagnostic 2D field remains in the hashed worker file.
                    # The aggregate keeps only the physical paraxial display image.
                    row['data'].pop('intensity_2d',None)
                    row['data']['full_field_evidence']=candidate['id']+'/result.json'
            except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
                row.update(status='RUN_FAILED',error=str(exc),all_checks_passed=False)
                rows.append(row)
                # Retain partial files and stop the batch; failed work is not free.
                break
            rows.append(row)
        ranking=rank(rows,plan['goal'])
        if d=='film' and ranking and budget['max_meep_validations']:
            from .film_verification import verify_film
            for ident in ranking[:budget['max_meep_validations']]:
                row=next(x for x in rows if x['id']==ident)
                usage['fdtd_attempts_reserved']+=8
                try:
                    value=verify_film(row,plan['goal'],out/(ident+'-meep'))
                    row['verification']=value
                    usage['actual_fdtd_runs']+=value.get('resources',{}).get('actual_fdtd_runs',0)
                except (ValueError,OSError,KeyError) as exc:row['verification']={'status':'VERIFICATION_FAILED','error':str(exc)}
    if d=='diffraction':
        vmax=max((r.get('metrics',{}).get('peak_intensity',0) for r in rows),default=1) or 1
        for row in rows:
            image=row.get('data',{}).get('image')
            if image:image.update(vmin=0,vmax=vmax,normalization_label='共同入射强度=1；所有本批候选共用0–'+f'{vmax:.6g}'+'物理光强标尺')
    result={'status':'RUN_COMPLETED' if all(x['status']=='RUN_COMPLETED' for x in rows) and len(rows)==len(plan['candidates']) else 'PARTIAL_OR_FAILED',
            'plan_sha256':plan['sha256'],'candidates':rows,'ranking':ranking,'winner_id':ranking[0] if ranking else None,
            'summary':f'实际计算{len(rows)}个候选；通过数值检查{len(ranking)}个。有限候选中的最佳值不等于全局最优。',
            'resources':usage,'elapsed_seconds':time.monotonic()-started,
            'limitations':plan['assumptions']+['同理论公式或不同软件实现的校准不等于独立科学证书。','薄膜快速目标值来自TMM；仅带Meep复核回执的候选具有另一路数值检查。']}
    result['resources']['output_limit_bytes']=budget['output_mib']*1024*1024
    result['resources']['output_bytes_scope']='ENTIRE_EXECUTION_DIRECTORY_INCLUDING_MANIFEST'
    # Hash lengths are fixed; size accounting converges after its decimal digits
    # stabilize. Include the final result and manifest rather than undercounting.
    for _ in range(6):
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf-8')
        files={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p!=out/'manifest.json'}
        write_json(out/'manifest.json',{'schema_version':1,'plan_sha256':plan['sha256'],'files':files})
        actual_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        if actual_bytes>budget['output_mib']*1024*1024 and result['status']!='OUTPUT_LIMIT_EXCEEDED':
            result['status']='OUTPUT_LIMIT_EXCEEDED';result['winner_id']=None;result['ranking']=[]
            result['limitations'].append('实际证据超出本批输出预算；此批不作为成功实验，需缩小后另建版本。')
        elif result['resources']['output_bytes']==actual_bytes:return result
        result['resources']['output_bytes']=actual_bytes
    raise ValueError('Evidence size accounting did not stabilize')
