"""Zero-solver exact arithmetic and model-boundary regression checks."""
import copy,json
from pathlib import Path
from fractions import Fraction as F
import numpy as np
import pytest
from research.goal_certificate.pump_slab_envelope import check
from research.goal_certificate.interval_arithmetic import R,C,gershgorin
from research.goal_certificate.conforming_trials import mesh,propose_analytic,audit
from research.goal_certificate.interval_graph_matrix import local_fields,integrate
from research.goal_certificate.target_binding import assess
from research.goal_certificate.positive_count_checker import validate_trials

def model():
    return {'numeric_semantics':'binary64-inputs-exact-rational-geometry-v1',
      'task':{'adapter':'mode-xcut-v1','requirements':{'length_unit':'um','wavelengths_um':[1.55,.775],
        'orientation':'xcut-yprop-v1','material_model':'zelmon1997-congruent-21C-v1','temperature_c':21,'composition':'undoped-congruent',
        'film_thickness_um':.6,'slab_thickness_um':.3,'ridge_width_um':1.4,'top_index':1.,'bottom_index':1.44},'numerics':{'domain_um':[4,4]}},
      'materials':{'1.55':{'wavelength_um':1.55,'laboratory_epsilon':np.diag([4.57,4.889,4.889]).tolist()},
                   '0.775':{'wavelength_um':.775,'laboratory_epsilon':np.diag([4.8,5.1,5.1]).tolist()}},
      'boundary':'periodic','transverse_bloch_k':[0,0],'relative_permeability':1,'top_epsilon':1.,'bottom_epsilon':1.44**2}

def test_pump_two_implementations_and_outward_index_bound():
    r=check(model());assert r['status']=='MODEL_PUMP_UPPER_VERIFIED'
    assert F(r['neff_upper_outward_binary64'])>=F(41,20)
    assert r['second_implementation']['scalar_review_passed'] and not r['SH_or_target_rank_certified']

@pytest.mark.parametrize('change', ['material','film','boundary','wavelength','mu','cladding'])
def test_pump_changed_physics_cannot_inherit_certificate(change):
    m=model()
    if change=='material':m['materials']['1.55']['laboratory_epsilon'][1][1]=5
    if change=='film':m['task']['requirements']['film_thickness_um']=.6000000001
    if change=='boundary':m['boundary']='PEC'
    if change=='wavelength':m['task']['requirements']['wavelengths_um'][0]=1.5501
    if change=='mu':m['relative_permeability']=1.01
    if change=='cladding':m['bottom_epsilon']=3
    assert check(m)['status']=='NOT_APPLICABLE_OR_UNVERIFIED'

def test_interval_polynomial_integral_contains_exact_fraction():
    a=np.array([[[complex(.1,.2)],[complex(.3,-.7)],[complex(.9,.4)]]])
    b=np.array([[[complex(.8,-.1)],[complex(.6,.5)],[complex(.2,-.9)]]])
    out=integrate(C.point(a),C.point(b),R([.13]),R([1.7]))
    def product(x,y):return F(x.real)*F(y.real)+F(x.imag)*F(y.imag),F(x.real)*F(y.imag)-F(x.imag)*F(y.real)
    real=F(0);imag=F(0)
    for i in range(3):
        for j in range(3):
            z=product(a[0,i,0],b[0,j,0]);factor=F(.13)*F(1.7)*F(2 if i==j else 1,12)
            real+=factor*z[0];imag+=factor*z[1]
    assert F(out.re.lo[0,0])<=real<=F(out.re.hi[0,0])
    assert F(out.im.lo[0,0])<=imag<=F(out.im.hi[0,0])

def test_gershgorin_rejects_uncertain_or_nonpositive_matrices():
    assert gershgorin(C.point(np.diag([1.,2.,3.]).astype(complex)))['positive_definite']
    assert not gershgorin(C(R(np.diag([-.1,2.,3.]),np.diag([.1,2.,3.])),np.zeros((3,3))))['positive_definite']
    assert not gershgorin(C.point(np.array([[1.,2.],[2.,1.]],complex)))['positive_definite']

def test_periodic_shared_traces_are_constraints_not_tolerance_tests():
    m=model();d=mesh(m,r=2)
    def field(p):return np.ones((len(p),2,3,1),complex)
    propose_analytic(d,field,1);assert audit(d)['status']=='PASS'
    d['edge_signs'][0,0]*=-1
    with pytest.raises(AssertionError):audit(d)

def test_lowest_order_polynomial_reconstruction_and_curl():
    m=model();m['task']['requirements'].update(film_thickness_um=1.,slab_thickness_um=.5,ridge_width_um=1.)
    d=mesh(m,r=2)
    def field(p):
        x,y=p.T;v=np.stack([1+2*y,3-2*x,4+x+3*y],axis=1)
        return np.repeat(v[:,None,:,None],2,axis=1).astype(complex)
    propose_analytic(d,field,1)
    # Cell (2,2) has no periodic-boundary representatives and dyadic coordinates.
    start=2*8+2;vals,der,area=local_fields(d,start,start+1)
    expected=field(d['vertices'][d['triangles'][start]])[:,0,:,0]
    for k in range(3):
        assert np.all(vals[0][k].re.lo[0,:,0]<=expected[:,k]) and np.all(expected[:,k]<=vals[0][k].re.hi[0,:,0])
    for k,value in enumerate((1,3,-4)):
        assert der[0][k].re.lo[0,0]<=value<=der[0][k].re.hi[0,0]

@pytest.mark.parametrize('claim',[{'certified':True},{'band':3},{'continuous_rank':3,'sha256':'a'*64},{'overlap':1.0}])
def test_discrete_rank_or_caller_flag_cannot_unlock_design_exclusion(claim):
    goal={'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':20,'qpm_order':1,'target_phase_factor_min':.8}
    value=assess(model(),{'status':'MODEL_PUMP_UPPER_VERIFIED'},{'status':'CONTINUOUS_LOW_SPECTRAL_COUNT_VERIFIED'},claim,goal=goal)
    assert value['status']=='TARGET_MODE_RANK_UNBOUND' and not value['goal_excluded_for_original_target']
    assert value['conditional_algebra']['conditional_phase_factor_upper']<.039

def test_low_count_does_not_identify_a_target_selected_by_field_features():
    # A self-adjoint diagonal family: first three branches are always below 1,
    # yet the only branch satisfying an unrelated polarization filter crosses 1.
    for s in (.5,1,2.09):
        spectrum=np.array([.2,.3,.4,.9+.1*(s-1)])
        assert np.count_nonzero((spectrum>.05)&(spectrum<1))>=3
    assert .9+.1*(2-1)==1
    # This counterexample invalidates using count>=3 alone as target-rank proof.

def test_offdiagonal_material_cannot_be_silently_discarded():
    m=model();m['materials']['0.775']['laboratory_epsilon'][0][1]=.01
    with pytest.raises(ValueError,match='SH_POSITIVE_DIAGONAL_MATERIAL'):validate_trials(m,{})

def test_trial_geometry_cannot_redefine_the_bound_model():
    m=model();d=mesh(m,40);d['vertices'][10,0]+=.001
    with pytest.raises(ValueError,match='MODEL_MESH_MATERIAL_BINDING:vertices'):validate_trials(m,d)

def test_changed_design_period_does_not_reuse_conditional_goal():
    goal={'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':21,'qpm_order':1,'target_phase_factor_min':.8}
    with pytest.raises(ValueError,match='LOCKED_GOAL_BINDING'):assess(model(),{}, {},goal=goal)
