"""Adapter-specific locks, policies and evidence; no implicit approval or execution."""
import importlib
from pathlib import Path
from datetime import datetime,timezone
from ..core import digest

ADAPTERS={'mode-xcut-v1':'mpb_modes','qpm-shg-phase-v1':'qpm_phase'}

def adapter(name):
    if type(name) is not str or name not in ADAPTERS:raise ValueError('适配器未支持；不修改旧任务策略来绕过。')
    return importlib.import_module('.'+ADAPTERS[name],__package__)

def validate_task(task):
    if type(task) is not dict or task.get('schema_version')!=1:raise ValueError('任务需要明确schema_version。')
    module=adapter(task.get('adapter'));module.validate_task(task);return module

def lock_task(task,*,approve=False,confirmation_kind=None):
    module=validate_task(task)
    if approve is not True or confirmation_kind not in ('USER','SIMULATED'):raise ValueError('需要当前明确批准；开发确认必须标SIMULATED。')
    return {'schema_version':1,'adapter':task['adapter'],'adapter_policy_sha256':digest(module.POLICY),
        'task_sha256':digest(task),'confirmation_kind':confirmation_kind,
        'confirmed_at_utc':datetime.now(timezone.utc).isoformat(),'solver_approved':False,'repair_approved':False}

def verify_lock(task,lock):
    module=validate_task(task)
    if type(lock) is not dict or lock.get('task_sha256')!=digest(task) or lock.get('adapter')!=task['adapter'] or lock.get('adapter_policy_sha256')!=digest(module.POLICY) or lock.get('confirmation_kind') not in ('USER','SIMULATED'):
        raise ValueError('任务、适配器或策略已改变；旧锁不适用。')
    return module

def execution_permit(task,lock,*,approve=False):
    from ..approved_gui import source_manifest
    module=verify_lock(task,lock)
    if approve is not True:raise ValueError('求解需要明确的资源与范围批准。')
    source=source_manifest(Path(__file__).resolve().parents[2])
    return {'task_sha256':digest(task),'lock_sha256':digest(lock),'policy_sha256':digest(module.POLICY),
        'source_binding_sha256':digest(source),'source_commit':source['git_commit'],
        'confirmation_kind':lock['confirmation_kind'],'approved':True,'resource_limits':module.POLICY['resource_limits'],
        'automatic_retry':False,'model_requests':0}

def verify_permit(task,lock,permit):
    module=verify_lock(task,lock)
    if permit!=execution_permit(task,lock,approve=True):raise ValueError('执行许可或资源边界已变化。')
    return module
