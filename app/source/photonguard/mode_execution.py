"""Separate numerical candidates from locked device goals; bounded owned MPB only."""
import copy, math
from pathlib import Path
from .core import digest

POLICY = {'version': 'mode-numerical-repair-v1', 'maximum_repairs_per_task': 1,
    'maximum_changes_per_card': 1, 'max_candidate_resolution': 80,
    'max_output_estimate_bytes': 768 * 1024**2, 'max_band_file_estimate_bytes': 31 * 1024**2,
    'candidate_fields': ['numerics.resolution', 'numerics.domain_um'],
    'immutable_device_requirements': True, 'immutable_qpm_goal': True,
    'immutable_independent_verifier': True, 'additional_model_requests_after_approval': 0}

def initial_candidate(task):
    return {'schema_version': 1, 'adapter': 'mode-xcut-numerics-v1',
            'task_sha256': digest(task), 'numerics': copy.deepcopy(task['numerics'])}

def execution_task(task, candidate):
    from .adapters.mpb_modes import validate_task
    validate_task(task)
    if (type(candidate) is not dict or set(candidate) != {'schema_version','adapter','task_sha256','numerics'}
            or candidate['schema_version'] != 1 or candidate['adapter'] != 'mode-xcut-numerics-v1'
            or candidate['task_sha256'] != digest(task)):
        raise ValueError('MODE_CANDIDATE_TASK_BINDING')
    result = copy.deepcopy(task); result['numerics'] = copy.deepcopy(candidate['numerics'])
    validate_task(result)
    if (result['numerics']['resolution'] < task['numerics']['resolution']
            or any(a < b for a,b in zip(result['numerics']['domain_um'],task['numerics']['domain_um']))):
        raise ValueError('MODE_CANDIDATE_CANNOT_COARSEN')
    return result

def output_estimate(task, candidate):
    from .adapters.mpb_modes import plan_checks
    # Complex E/H (6 components), real energy, plus safe array/metadata allowance.
    sizes = [math.ceil(s['resolution']*s['domain_um'][0]) * math.ceil(s['resolution']*s['domain_um'][1]) * 112
             for s in plan_checks(execution_task(task,candidate))]
    return {'estimated_total_output_bytes': sum(sizes)*4 + 8*1024**2,
            'estimated_max_band_file_bytes': max(sizes) + 1024**2}

def validate_repair_candidate(task, candidate):
    execution_task(task,candidate)
    if candidate['numerics']['resolution'] > POLICY['max_candidate_resolution']:
        raise ValueError('MODE_REPAIR_RESOLUTION_RESOURCE_LIMIT')
    return validate_output_size(task,candidate)

def validate_output_size(task,candidate):
    execution_task(task,candidate)
    size = output_estimate(task,candidate)
    if (size['estimated_total_output_bytes'] > POLICY['max_output_estimate_bytes']
            or size['estimated_max_band_file_bytes'] > POLICY['max_band_file_estimate_bytes']):
        raise ValueError('MODE_REPAIR_OUTPUT_RESOURCE_LIMIT')
    return size

def eligible_changes(task, candidate):
    """Resource eligibility, not diagnostic recommendations or a rule answer."""
    execution_task(task,candidate); result=[]
    for value in (48,64,80):
        if value <= candidate['numerics']['resolution']: continue
        trial=copy.deepcopy(candidate);trial['numerics']['resolution']=value
        try: size=validate_repair_candidate(task,trial)
        except ValueError: continue
        result.append({'path':['numerics','resolution'],'new':value,**size})
    domain=[d*1.5 for d in candidate['numerics']['domain_um']]
    trial=copy.deepcopy(candidate);trial['numerics']['domain_um']=domain
    try: size=validate_repair_candidate(task,trial)
    except ValueError: pass
    else: result.append({'path':['numerics','domain_um'],'new':domain,**size})
    return result

def apply_change(task, candidate, change):
    if (type(change) is not dict or set(change) != {'path','new'}
            or not any(change['path']==e['path'] and change['new']==e['new'] for e in eligible_changes(task,candidate))):
        raise ValueError('MODE_PATCH_OUTSIDE_ELIGIBLE_NUMERICS')
    result=copy.deepcopy(candidate); result['numerics'][change['path'][1]]=copy.deepcopy(change['new'])
    validate_repair_candidate(task,result);return result

def permit(task, lock, candidate, *, approve=False, phase='initial', card_sha256=None):
    from .adapters import registry,mpb_modes
    from .approved_gui import source_manifest
    registry.verify_lock(task,lock); execution_task(task,candidate)
    if approve is not True or phase not in ('initial','repair'):
        raise ValueError('MODE_EXECUTION_REQUIRES_CURRENT_APPROVAL')
    if phase=='repair':
        validate_repair_candidate(task,candidate)
        if type(card_sha256) is not str or len(card_sha256)!=64:
            raise ValueError('MODE_REPAIR_REQUIRES_CARD')
    elif candidate != initial_candidate(task):
        raise ValueError('MODE_INITIAL_CANDIDATE_NOT_TASK_SEED')
    else:
        validate_output_size(task,candidate)
    source=source_manifest(Path(__file__).resolve().parents[1])
    return {'schema_version':1,'execution_policy_sha256':digest(POLICY),
            'task_sha256':digest(task),'lock_sha256':digest(lock),'candidate_sha256':digest(candidate),
            'source_binding_sha256':digest(source),'source_commit':source['git_commit'],
            'phase':phase,'card_sha256':card_sha256,'confirmation_kind':lock['confirmation_kind'],
            'approved':True,'resource_limits':copy.deepcopy(mpb_modes.POLICY['resource_limits']),
            'additional_model_requests':0,'automatic_retry':False}

def verify_permit(task, lock, candidate, value):
    if type(value) is not dict or value != permit(task,lock,candidate,approve=True,
                                                phase=value.get('phase'),card_sha256=value.get('card_sha256')):
        raise ValueError('MODE_NUMERICAL_EXECUTION_BINDING')
