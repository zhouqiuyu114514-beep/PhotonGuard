"""Synthetic diagnostic/safety fixtures; not scientific mode evidence."""
import numpy as np
import pytest
from photonguard.mpb_metadata import actual_grid,restore_array,energy_audit
from photonguard.mode_field_research import load_fields,pair_metrics,audit_field_file
from photonguard.research_phase_bounds import assess_goal_envelope
from photonguard.mode_precision import classify_precision_evidence

def fields(n=8,period=4):
    axis=(np.arange(n)/n-.5)*period
    e=np.zeros((n,n,1,3),complex);e[...,0]=1
    h=np.zeros_like(e);h[...,1]=1j
    return {'E':e,'H':h,'electric_energy':np.ones((n,n,1)), 'x_um':axis,'y_um':axis.copy()}

def test_actual_optimized_size_wins_over_nominal_round():
    g=actual_grid([320,324],[4,4.07,0],80,optimized=True)
    assert g['shape_xyz']==[320,324,1] and g['nominal_grid_before_optimization']==[320,326,1]
    assert g['spacing_um'][1]==pytest.approx(4.07/324)
    a=restore_array(np.ones((320,324,1,3)),g,vector=True)
    assert a.shape==(320,324,1,3)
    with pytest.raises(ValueError):restore_array(np.ones((320,326,1,3)),g,vector=True)

def test_degenerate_axis_is_restored_by_axis_semantics_not_length():
    g=actual_grid([1024],[0,8,0],128,optimized=True)
    assert g['shape_xyz']==[1,1024,1]
    raw=np.arange(1024*3).reshape(1024,1,1,3)
    assert np.array_equal(restore_array(raw,g,vector=True)[0,:,0,:],raw[:,0,0,:])

@pytest.mark.parametrize('dims,sizes',[([300],[4,4,0]),([320,320,2],[4,4,0]),([0,3],[4,4,0]),([True,3],[4,4,0])])
def test_ambiguous_or_invalid_backend_grid_fails_closed(dims,sizes):
    with pytest.raises(ValueError):actual_grid(dims,sizes,80,optimized=True)

def test_energy_audit_preserves_negative_before_display():
    a=energy_audit(np.array([1.,-.001,-1e-15]))
    assert a['negative_sample_count']==2 and a['minimum']==-.001
    assert a['negative_absolute_sum']>0 and a['audited_before_display_clipping']
    with pytest.raises(ValueError):energy_audit(np.array([np.nan]))

def test_same_field_with_complex_phase_has_separate_E_H_overlaps():
    a=fields();b=fields();phase=np.exp(1j*.73);b['E']*=phase;b['H']*=phase
    r=pair_metrics(a,b,weight=np.ones((8,8,3))*2)
    assert r['metrics']['E_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1)
    assert r['metrics']['H_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1)
    assert r['metrics']['E_L2_overlap_research']['global_phase_alignment_rad']==pytest.approx(.73)
    assert r['H_minus_E_phase_residual_rad']==pytest.approx(0)
    assert r['not_power_or_mode_orthogonality'] and r['not_a_true_beta_error_bound']

def test_different_H_is_detected_even_if_E_is_identical():
    a=fields();b=fields();b['H'][...,1]=0;b['H'][...,2]=1
    r=pair_metrics(a,b)
    assert r['metrics']['E_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1)
    assert r['metrics']['H_L2_overlap_research']['squared_normalized_overlap']==0

def test_large_domain_tail_is_reported_and_not_disappeared_by_cropping():
    r=pair_metrics(fields(),fields(12,6))
    assert r['second_native_window_and_tail']['E_L2_window_fraction']==pytest.approx(4/9)
    assert r['second_native_window_and_tail']['electric_energy_tail_fraction']==pytest.approx(5/9)
    assert r['metrics']['E_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1)

def test_periodic_shift_wrap_and_nonzero_bloch_refusal():
    assert pair_metrics(fields(),fields(),shift_um=(4.1,0))['metrics']['E_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1)
    with pytest.raises(ValueError):pair_metrics(fields(),fields(),transverse_k=(.1,0))

def test_weight_must_be_shared_positive_and_shape_matched():
    for w in (np.zeros((8,8,3)),np.ones((2,2,3)),np.full((8,8,3),np.nan)):
        with pytest.raises(ValueError):pair_metrics(fields(),fields(),weight=w)

def test_negative_dpwr_cannot_be_hidden_in_window_fraction():
    a=fields();a['electric_energy'][0,0,0]=-.1
    r=pair_metrics(a,fields())
    assert r['first_native_window_and_tail']['electric_energy_window_fraction'] is None
    assert r['first_native_window_and_tail']['raw_energy_audit']['minimum']==-.1

def test_old_npz_is_read_without_pickle_and_coordinate_mismatch_is_detected(tmp_path):
    data=fields();p=tmp_path/'band-1-fields.npz';np.savez(p,**data)
    result=audit_field_file(p,{'field_shape':[8,8,1,3]},[4,4,0])
    assert result['finite'] and 'UNAVAILABLE' in result['effective_tensor_component_energy_fraction']
    with pytest.raises(ValueError):audit_field_file(p,{'field_shape':[8,8,1,3]},[6,4,0])
    data['E']=np.array([object()],dtype=object);np.savez(p,**data)
    with pytest.raises(ValueError):load_fields(p)

@pytest.mark.parametrize('interval',[[1.2,1.3],[-1.3,-1.2],[-.1,.1],[0,0]])
def test_conditional_interval_never_accepts_unimplemented_certificate(interval):
    r=assess_goal_envelope(interval,{'certified':True,'sha256':'a'*64},1000,.8)
    assert r['status']=='CONDITIONAL_EXCLUSION_UNPROVEN' and r['design_goal_status']=='NOT_EVALUATED'
    assert not r['continuous_truth_interval_certified']
    if interval[0]<=0<=interval[1]:assert r['conditional_phase_factor_upper']==1
    else:assert r['conditional_phase_factor_upper']<.8

@pytest.mark.parametrize('interval,length,target',[([2,1],1000,.8),([float('nan'),2],1000,.8),([1,2],0,.8),([1,2],1000,0),([1,2],1000,True)])
def test_invalid_interval_cannot_produce_goal_statement(interval,length,target):
    with pytest.raises(ValueError):assess_goal_envelope(interval,{},length,target)

def test_evidence_levels_never_upgrade_mode_PASS_to_continuous_certification():
    r=classify_precision_evidence(record_integrity=True,root_closure=True,mode_identity=True,
        setting_sensitivity=True,phase_status='INCONCLUSIVE',design_goal_status='NOT_EVALUATED')
    assert not r['levels'][-1]['supported'] and r['levels'][-1]['status']=='UNKNOWN'
    assert r['original_phase_status']=='INCONCLUSIVE' and r['original_receipts_and_policy_unchanged']
