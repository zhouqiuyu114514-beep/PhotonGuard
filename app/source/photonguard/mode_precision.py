"""Offline phase-sensitivity accounting and a separately approved development study.

Signed cancellation is reported, never substituted for the unchanged verifier.
No model transport or product repair approval is imported by this module.
"""
import copy, math
from .core import digest
from . import mode_execution
from .adapters import mpb_modes,qpm_phase

STUDY_POLICY={'version':'mode-precision-study-v1','base_resolutions':[64,80],
    'maximum_worker_processes':12,'maximum_total_wall_seconds':3600,
    'maximum_output_estimate_bytes':1024**3,'minimum_free_disk_margin':1.2,
    'confirmation_kind':'SIMULATED','additional_model_requests':0,
    'automatic_retry':False,'stop_on_identity_or_mode_failure':True,
    'stop_when_fixed_precision_check_passes':True,
    'product_repair_count_or_policy_changed':False}

def sensitivity_accounting(records,goal):
    """Compute signed and conservative phase changes from actual selected modes.

    Caller independently verifies fields/provenance before using this accounting.
    Pure arithmetic also accepts explicitly synthetic unit-test records.
    """
    pump=goal['pump_wavelength_um'];length=goal['length_um']
    if not all(qpm_phase.finite(v) and v>0 for v in (pump,length)):
        raise ValueError('MODE_STUDY_WAVELENGTH_OR_LENGTH')
    group={}
    for record in records:
        wave=record['wavelength_um'];variant=record['variant'];value=record['neff']
        if wave not in (pump,pump/2) or variant not in ('base','grid','domain') or not qpm_phase.finite(value) or not 1<value<5:
            raise ValueError('MODE_STUDY_RECORD_RANGE')
        if (wave,variant) in group:raise ValueError('MODE_STUDY_DUPLICATE_SETTING')
        group[wave,variant]=value
    if len(group)!=6:raise ValueError('MODE_STUDY_REQUIRED_SETTINGS')
    coefficient=4*math.pi*length/pump;rows=[]
    for wave,sign in ((pump,-1),(pump/2,1)):
        grid=group[wave,'grid']-group[wave,'base'];domain=group[wave,'domain']-group[wave,'base']
        rows.append({'wavelength_um':wave,'base_neff':group[wave,'base'],
            'grid_neff_signed_change':grid,'domain_neff_signed_change':domain,
            'grid_phase_signed_change_rad':sign*coefficient*grid,
            'domain_phase_signed_change_rad':sign*coefficient*domain,
            'grid_phase_absolute_contribution_rad':coefficient*abs(grid),
            'domain_phase_absolute_contribution_rad':coefficient*abs(domain),
            'verifier_phase_contribution_rad':coefficient*max(abs(grid),abs(domain))})
    estimate=sum(row['verifier_phase_contribution_rad'] for row in rows)
    return {'schema_version':1,'pump_wavelength_um':pump,'length_um':length,
        'phase_coefficient_rad_per_neff':coefficient,'rows':rows,
        'grid_phase_signed_total_rad':sum(r['grid_phase_signed_change_rad'] for r in rows),
        'domain_phase_signed_total_rad':sum(r['domain_phase_signed_change_rad'] for r in rows),
        'grid_phase_absolute_sum_rad':sum(r['grid_phase_absolute_contribution_rad'] for r in rows),
        'domain_phase_absolute_sum_rad':sum(r['domain_phase_absolute_contribution_rad'] for r in rows),
        'unchanged_verifier_phase_estimate_rad':estimate,
        'fixed_limit_rad':qpm_phase.POLICY['max_phase_sensitivity_rad'],
        'signed_cancellation_used_for_acceptance':False,'rigorous_true_error_bound':False}

def build_study_plan(parent_task,goal,baseline_references,source_binding):
    mpb_modes.validate_task(parent_task)
    if parent_task['provenance'].get('synthetic') is not True:
        raise ValueError('MODE_STUDY_PUBLIC_SYNTHETIC_ONLY')
    # Validate the entire independent goal using sourced placeholder modes solely
    # for schema checks. These placeholders are never evaluated or executed.
    pump=goal.get('pump_wavelength_um');schema_modes=[]
    if not qpm_phase.finite(pump):raise ValueError('MODE_STUDY_GOAL_SCHEMA')
    for wave in (pump,pump/2):
        schema_modes.append({'wavelength_um':wave,'neff':2,'beta_rad_per_um':qpm_phase.beta(wave,2),
            'mode_id':'SCHEMA_CHECK_ONLY','source_sha256':'0'*64,'source':'SCHEMA_CHECK_NOT_EVIDENCE',
            'verification_status':'IMPORTED_NOT_VERIFIED','neff_sensitivity_estimate':0})
    qpm_phase.validate_task({'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':'SCHEMA_CHECK_ONLY',
        'requirements':goal,'modes':schema_modes,'provenance':{'reference':'SCHEMA_CHECK_NOT_EVIDENCE'}})
    if parent_task['requirements']['wavelengths_um']!=[pump,pump/2]:raise ValueError('MODE_STUDY_PROCESS_WAVELENGTH_BINDING')
    if type(baseline_references) is not list or not baseline_references:raise ValueError('MODE_STUDY_BASELINE_REQUIRED')
    tasks=[];total=0
    for resolution in STUDY_POLICY['base_resolutions']:
        task=copy.deepcopy(parent_task);task['task_id']+='-PRECISION-'+str(resolution)
        task['numerics']['resolution']=resolution
        task['provenance']['reference']+='; separate bounded numerical precision study; base '+str(resolution)
        task['provenance']['parent_task_sha256']=digest(parent_task)
        candidate=mode_execution.initial_candidate(task)
        size=mode_execution.validate_repair_candidate(task,candidate)
        total+=size['estimated_total_output_bytes'];tasks.append({'mode_task':task,'candidate':candidate,
            'physical_requirements_sha256':digest(task['requirements']),'qpm_goal_sha256':digest(goal),
            'output_estimate':size,'plan_checks':mpb_modes.plan_checks(task)})
    if total>STUDY_POLICY['maximum_output_estimate_bytes']:raise ValueError('MODE_STUDY_TOTAL_OUTPUT_LIMIT')
    return {'schema_version':1,'kind':'SEPARATE_PUBLIC_SYNTHETIC_PRECISION_STUDY',
        'policy_sha256':digest(STUDY_POLICY),'policy':copy.deepcopy(STUDY_POLICY),
        'parent_task':copy.deepcopy(parent_task),'parent_task_sha256':digest(parent_task),
        'physical_requirements_sha256':digest(parent_task['requirements']),
        'qpm_goal':copy.deepcopy(goal),'qpm_goal_sha256':digest(goal),
        'baseline_references':copy.deepcopy(baseline_references),'source_binding':copy.deepcopy(source_binding),
        'source_binding_sha256':digest(source_binding),'tasks':tasks,
        'estimated_total_output_bytes':total,
        'original_task_and_product_approval_not_modified':True,'confirmation_kind':'SIMULATED',
        'additional_model_requests':0,'no_success_or_convergence_guarantee':True}

def verify_study_plan(plan):
    if type(plan) is not dict:raise ValueError('MODE_STUDY_PLAN_SCHEMA')
    expected=build_study_plan(plan['parent_task'],plan['qpm_goal'],plan['baseline_references'],plan['source_binding'])
    if plan!=expected:raise ValueError('MODE_STUDY_PLAN_BINDING')

def verify_study_origin(plan,parent_task,goal):
    verify_study_plan(plan)
    if plan['parent_task']!=parent_task or plan['qpm_goal']!=goal:
        raise ValueError('MODE_STUDY_ORIGINAL_GOAL_OR_TASK_CHANGED')

def audit_raw_worker_series(bundles,goal):
    """Read raw scalar evidence only; does not certify absent full fields."""
    import re
    from pathlib import Path
    from .core import load
    rows=[];series=[];unique=set()
    for seed,bundle in bundles:
        root=Path(bundle);records=[]
        for path in sorted(root.glob('*/result.json')):
            raw=load(path);variant=path.parent.name.split('-')[0];wave=raw['wavelength_um']
            request=load(root/(path.parent.name+'.request.json'));selected=raw['selected_mode']
            if selected is None:raise ValueError('MODE_RESEARCH_SELECTED_MODE_MISSING')
            grids={tuple(map(int,m)) for m in re.findall(r'Grid size is (\d+) x (\d+) x (\d+)\.',
                (root/(path.parent.name+'.stdout.log')).read_text())}
            if len(grids)!=1:raise ValueError('MODE_RESEARCH_ACTUAL_FFT_GRID_AMBIGUOUS')
            grid=list(next(iter(grids)))
            if grid!=selected['field_shape'][:3] or request['step']['resolution']!=raw['resolution_pixels_per_um']:
                raise ValueError('MODE_RESEARCH_FFT_OUTPUT_MISMATCH')
            key=(raw['resolution_pixels_per_um'],tuple(raw['domain_um']),wave);unique.add(key)
            rows.append({'seed_resolution':seed,'variant':variant,'wavelength_um':wave,
                'actual_resolution_request':key[0],'actual_fft_grid':grid,'domain_um':raw['domain_um'],
                'neff':selected['neff'],'selected_band':selected['band'],
                'root_frequency_closure_cycles_per_um':abs(selected['frequency_cycles_per_um']-1/wave),
                'record_source':str(path),'not_a_true_error_bound':True})
            records.append({'wavelength_um':wave,'variant':variant,'neff':selected['neff']})
        series.append({'seed_resolution':seed,**sensitivity_accounting(records,goal)})
    return {'rows':rows,'series':series,'actual_worker_records':len(rows),
        'unique_setting_wavelength_combinations':len(unique),'duplicates_not_independent_device_cases':True,
        'not_a_true_error_bound':True,'full_fields_not_verified_by_scalar_audit':True}

def classify_precision_evidence(*,record_integrity,root_closure,mode_identity,setting_sensitivity,
                                phase_status,design_goal_status):
    """Versioned explanation layer; never rewrites any old receipt or status."""
    flags=(record_integrity,root_closure,mode_identity,setting_sensitivity)
    if any(type(v) is not bool for v in flags):raise ValueError('MODE_EVIDENCE_CLASSIFICATION_FLAGS')
    return {'explanation_version':'mode-evidence-levels-v2','levels':[
        {'kind':'record_integrity','supported':record_integrity},
        {'kind':'root_closure_same_discrete_problem','supported':root_closure},
        {'kind':'mode_shape_identity_within_computed_candidates','supported':mode_identity},
        {'kind':'tested_setting_sensitivity','supported':setting_sensitivity,'not_a_true_error_bound':True},
        {'kind':'continuous_solution_error_certification','supported':False,'status':'UNKNOWN'}],
        'original_phase_status':phase_status,'original_design_goal_status':design_goal_status,
        'mode_PASS_label':'该模式检查通过；不等于长器件相位精度通过',
        'original_receipts_and_policy_unchanged':True}
