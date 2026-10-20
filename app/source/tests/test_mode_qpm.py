"""Physics/unit and stop-boundary tests; no paid calls and no fabricated solver PASS."""
import copy,math
from pathlib import Path
import numpy as np
import pytest
from scipy.integrate import quad
from photonguard.core import load,digest,POLICY_HASH
from photonguard.materials.ln_sellmeier import refractive_index,dielectric_tensor,XCUT_ROTATION
from photonguard.adapters import registry,mpb_modes,qpm_phase
from photonguard.mode_verification import verify,overlap_squared

def mode_task():return load('examples/mode_qpm/ridge.task.json')

def qpm_task(length=10,period=20):
    modes=[{'wavelength_um':w,'neff':n,'beta_rad_per_um':qpm_phase.beta(w,n),'mode_id':f'test-{w}',
        'source_sha256':'a'*64,'source':'public-development-evidence','verification_status':'PASS','neff_sensitivity_estimate':1e-6}
        for w,n in ((1.55,1.906),(.775,2.101))]
    return {'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':'synthetic-qpm',
        'requirements':{'process':'SHG','pump_wavelength_um':1.55,'length_um':length,'poling_period_um':period,'qpm_order':1,'target_phase_factor_min':.8},
        'modes':modes,'provenance':{'reference':'independent synthetic task, not a manufactured device'}}

def receipts(task):return {m['source_sha256']+':'+m['mode_id']:copy.deepcopy(m) for m in task['modes']}

def test_sellmeier_reference_values_and_fixed_conditions():
    assert refractive_index(1.55,'extraordinary')==pytest.approx(2.1375596498,abs=1e-9)
    assert refractive_index(1.55,'ordinary')>refractive_index(1.55,'extraordinary')
    assert np.linalg.det(XCUT_ROTATION)==1
    data=dielectric_tensor(.775);assert np.diag(data['laboratory_epsilon'])==pytest.approx([data['n_e']**2,data['n_o']**2,data['n_o']**2])
    assert data['material_frozen_at_this_wavelength'] and not data['native_dispersive_eigenproblem']

@pytest.mark.parametrize('wave,conditions',[(.399,{}),(5.01,{}),(True,{}),(float('nan'),{}),(1.55,{'temperature_c':22}),(1.55,{'composition':'MgO'}),(1.55,{'temperature_c':True})])
def test_material_unknown_or_outside_source_range_stops(wave,conditions):
    with pytest.raises(ValueError):dielectric_tensor(wave,**conditions)

def test_coordinate_rotation_and_invalid_tensor_axes():
    rot=np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])
    first=dielectric_tensor(1.55);turned=dielectric_tensor(1.55,rot@XCUT_ROTATION)
    assert np.asarray(turned['laboratory_epsilon'])==pytest.approx(rot@np.asarray(first['laboratory_epsilon'])@rot.T)
    assert turned['coordinates']!=first['coordinates']
    with pytest.raises(ValueError):dielectric_tensor(1.55,np.diag([1,1,-1]))
    with pytest.raises(ValueError):dielectric_tensor(1.55,np.diag([1.000001,1,1]))

@pytest.mark.parametrize('delta',[0,.013,-.013,.17])
def test_sinc_matches_complex_integration_and_is_even(delta):
    length=70
    integral=complex(quad(lambda z:math.cos(delta*z),0,length)[0],quad(lambda z:math.sin(delta*z),0,length)[0])/length
    assert qpm_phase.phase_factor(delta,length)==pytest.approx(abs(integral)**2,abs=1e-12)
    assert qpm_phase.phase_factor(delta,length)==qpm_phase.phase_factor(-delta,length)

def test_phase_units_zero_match_and_length_bandwidth_scaling():
    assert qpm_phase.phase_factor(0,1000)==1
    assert qpm_phase.phase_factor(.2,10)==pytest.approx(qpm_phase.phase_factor(.2e6,10e-6))
    assert qpm_phase.phase_factor(.01,100)==pytest.approx(qpm_phase.phase_factor(.02,50))
    period=qpm_phase.qpm_period(1.55,1.906,2.101)
    task=qpm_task(period=period);result=qpm_phase.evaluate(task,verified_mode_sources=receipts(task))
    assert result['verification_status']=='PASS' and result['design_goal_status']=='MET'
    assert result['phase_factor_NOT_efficiency']==pytest.approx(1)
    assert not result['absolute_efficiency_calculated']

def test_correct_arithmetic_can_fail_design_without_repairing_manufactured_period():
    task=qpm_task();before=digest(task);result=qpm_phase.evaluate(task,verified_mode_sources=receipts(task))
    assert result['verification_status']=='PASS' and result['design_goal_status']=='NOT_MET'
    assert digest(task)==before and result['actual_nonlinear_solver_runs']==0

def test_long_device_sensitivity_stops_without_changing_length_or_threshold():
    task=qpm_task(length=10000);before=digest(task)
    result=qpm_phase.evaluate(task,verified_mode_sources=receipts(task))
    assert result['verification_status']=='INCONCLUSIVE' and result['design_goal_status']=='NOT_EVALUATED'
    assert result['phase_sensitivity_estimate_rad']>.1 and digest(task)==before

def test_typed_pass_without_verified_mode_evidence_is_not_trusted():
    result=qpm_phase.evaluate(qpm_task())
    assert result['arithmetic_verification_status']=='PASS'
    assert result['verification_status']=='INCONCLUSIVE' and not result['mode_provenance_verified']

@pytest.mark.parametrize('mutation',['missing_2pi','swap_wavelengths','unknown_sensitivity','unsupported_process','efficiency_goal','unknown_geometry','unhashable_wave','temperature','unknown_axis'])
def test_invalid_physics_or_missing_information_is_controlled_rejection(mutation):
    task=qpm_task() if mutation in ('missing_2pi','swap_wavelengths','unknown_sensitivity','unsupported_process','efficiency_goal') else mode_task()
    if mutation=='missing_2pi':task['modes'][0]['beta_rad_per_um']/=2*math.pi
    if mutation=='swap_wavelengths':task['modes'].reverse()
    if mutation=='unknown_sensitivity':task['modes'][0]['neff_sensitivity_estimate']=None
    if mutation=='unsupported_process':task['requirements']['process']='SFG'
    if mutation=='efficiency_goal':task['requirements']['target_absolute_efficiency']=.8
    if mutation=='unknown_geometry':task['requirements']['ridge_width_um']=None
    if mutation=='unhashable_wave':task['requirements']['wavelengths_um']=[[1.55]]
    if mutation=='temperature':task['requirements']['temperature_c']=25
    if mutation=='unknown_axis':task['requirements']['orientation']=None
    with pytest.raises(ValueError):registry.validate_task(task)

def test_task_policy_and_execution_source_are_independently_bound(monkeypatch):
    source={'git_commit':'f'*40,'files':{'owned.py':'b'*64}}
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:copy.deepcopy(source))
    task=mode_task();lock=registry.lock_task(task,approve=True,confirmation_kind='SIMULATED')
    assert not lock['solver_approved'] and not lock['repair_approved']
    with pytest.raises(ValueError):registry.execution_permit(task,lock)
    permit=registry.execution_permit(task,lock,approve=True);registry.verify_permit(task,lock,permit)
    changed=copy.deepcopy(task);changed['requirements']['ridge_width_um']=1.5
    with pytest.raises(ValueError):registry.verify_lock(changed,lock)
    source['git_commit']='e'*40
    with pytest.raises(ValueError):registry.verify_permit(task,lock,permit)
    assert POLICY_HASH=='289c883ef4f0c1a2fac02ab54c92e1c76d445bcdaca9706774c167c005be9fde'

def field_record(root,variant,band=1,*,same_field=True,neff=1.9):
    folder=root/variant;folder.mkdir();axis=np.linspace(-2,2,8);x,y=np.meshgrid(axis,axis,indexing='ij')
    first=np.zeros((8,8,1,3),dtype=complex);first[:,:,0,0]=np.exp(-2*(x*x+y*y));other=first.copy()
    if not same_field:other[:]=0;other[:,:,0,1]=np.exp(-2*(x*x+y*y))
    modes=[]
    for num,field in ((band,first),(band+1,other)):
        np.savez_compressed(folder/f'band-{num}-fields.npz',E=field,x_um=axis,y_um=axis)
        modes.append({'band':num,'neff':neff,'k_cycles_per_um':neff/1.55,'beta_rad_per_um':2*math.pi*neff/1.55,
            'frequency_cycles_per_um':1/1.55,'outer_cell_energy_fraction':1e-6,'fields_npz':f'band-{num}-fields.npz'})
    return {'variant':variant,'path':str(folder),'result':{'wavelength_um':1.55,'selected_mode':modes[0],'all_modes':modes}}

def test_empty_or_missing_checks_never_pass():
    assert verify([],mpb_modes.POLICY)['verification_status']=='INCONCLUSIVE'

def test_mode_band_change_is_allowed_when_field_identity_is_unique(tmp_path):
    records=[field_record(tmp_path,v,i,same_field=False) for v,i in (('base',1),('grid',3),('domain',2))]
    result=verify(records,mpb_modes.POLICY)
    assert result['verification_status']=='PASS' and result['checks'][0]['selected_bands']==[1,3,2]

def test_ambiguous_mode_identity_stops_even_when_neff_is_equal(tmp_path):
    records=[field_record(tmp_path,v,same_field=True) for v in ('base','grid','domain')]
    result=verify(records,mpb_modes.POLICY)
    assert result['verification_status']=='INCONCLUSIVE' and result['checks'][0]['identity_margins']==pytest.approx([0,0])

def test_wrong_mpb_k_to_beta_units_fail(tmp_path):
    records=[field_record(tmp_path,v,same_field=False) for v in ('base','grid','domain')]
    records[0]['result']['selected_mode']['beta_rad_per_um']/=2*math.pi
    assert verify(records,mpb_modes.POLICY)['verification_status']=='FAIL'

def test_mode_grid_change_is_measured_and_not_called_root_tolerance(tmp_path):
    records=[field_record(tmp_path,v,same_field=False,neff=1.91 if v=='grid' else 1.9) for v in ('base','grid','domain')]
    result=verify(records,mpb_modes.POLICY)
    assert result['verification_status']=='FAIL' and result['checks'][1]['grid_neff_change']==pytest.approx(.01)
