"""Explicit synthetic arithmetic/safety fixtures, not new scientific evidence."""
import copy,math
import pytest
from photonguard.core import load,digest
from photonguard.mode_precision import sensitivity_accounting,build_study_plan,verify_study_plan,verify_study_origin

def records(grid=(.0001,.0001),domain=(.00001,.00002)):
    return [{'wavelength_um':wave,'variant':variant,'neff':2+delta}
        for wave,g,d in zip((1.55,.775),grid,domain)
        for variant,delta in (('base',0),('grid',g),('domain',d))]

def goal():return {'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':20,
    'qpm_order':1,'target_phase_factor_min':.8}

def test_signed_cancellation_cannot_pass_conservative_precision():
    result=sensitivity_accounting(records(),goal())
    assert result['grid_phase_signed_total_rad']==pytest.approx(0)
    assert result['unchanged_verifier_phase_estimate_rad']>1 and not result['signed_cancellation_used_for_acceptance']

def test_different_dominant_settings_are_combined_per_wavelength():
    result=sensitivity_accounting(records(grid=(.0001,0),domain=(0,.0002)),goal())
    assert result['unchanged_verifier_phase_estimate_rad']==pytest.approx(4*math.pi*1000/1.55*.0003)
    assert result['unchanged_verifier_phase_estimate_rad']>max(result['grid_phase_absolute_sum_rad'],result['domain_phase_absolute_sum_rad'])

@pytest.mark.parametrize('change',[lambda r:r.pop(),lambda r:r.append(r[0]),
    lambda r:r[0].update(neff=float('nan')),lambda r:r[0].update(wavelength_um=.7)])
def test_invalid_evidence_arithmetic_refuses_missing_duplicate_nonfinite_or_wrong_wave(change):
    values=records();change(values)
    with pytest.raises(ValueError):sensitivity_accounting(values,goal())

def plan():
    task=load('examples/mode_qpm/ridge.task.json')
    return build_study_plan(task,goal(),[{'kind':'SYNTHETIC_UNIT_FIXTURE','manifest_sha256':'a'*64}],{'git_commit':'SYNTHETIC_UNIT_FIXTURE'})

def test_study_is_separate_and_preserves_geometry_goal_and_product_policy():
    original=load('examples/mode_qpm/ridge.task.json');value=plan();verify_study_plan(value)
    assert value['parent_task']==original and value['confirmation_kind']=='SIMULATED'
    assert [t['mode_task']['numerics']['resolution'] for t in value['tasks']]==[64,80]
    assert all(t['physical_requirements_sha256']==digest(original['requirements']) for t in value['tasks'])
    assert all(t['qpm_goal_sha256']==digest(goal()) for t in value['tasks'])
    assert not value['policy']['product_repair_count_or_policy_changed'] and value['additional_model_requests']==0
    assert sum(len(t['plan_checks']) for t in value['tasks'])==12

@pytest.mark.parametrize('change',[lambda p:p['qpm_goal'].update(length_um=10),
    lambda p:p['tasks'][0]['mode_task']['requirements'].update(ridge_width_um=1.5),
    lambda p:p['policy'].update(maximum_total_wall_seconds=10000),
    lambda p:p['tasks'][0]['candidate']['numerics'].update(resolution=128)])
def test_plan_mutation_is_refused(change):
    value=plan();change(value)
    with pytest.raises(ValueError):verify_study_plan(value)

def test_non_synthetic_or_output_oversized_study_is_not_implicitly_approved():
    value=plan();task=copy.deepcopy(value['parent_task']);task['provenance']['synthetic']=False
    with pytest.raises(ValueError):build_study_plan(task,goal(),value['baseline_references'],value['source_binding'])
    task=copy.deepcopy(value['parent_task']);task['numerics']['domain_um']=[8,8]
    with pytest.raises(ValueError):build_study_plan(task,goal(),value['baseline_references'],value['source_binding'])

def test_even_consistently_rebuilt_plan_cannot_change_the_original_goal():
    value=plan();changed=goal();changed['length_um']=10
    rebuilt=build_study_plan(value['parent_task'],changed,value['baseline_references'],value['source_binding'])
    verify_study_plan(rebuilt)
    with pytest.raises(ValueError):verify_study_origin(rebuilt,value['parent_task'],goal())
    verify_study_origin(value,value['parent_task'],goal())
