import numpy as np
from research.goal_certificate.graded_trace import graded_mesh,interpolate_high,field_from_coefficients
from research.goal_certificate import higher_order_trace as high
from research.goal_certificate.shared_trace_proposal import calibrate as material_calibration,quadrature
from research.goal_certificate.conforming_trials import mesh


def model():
    return {'task':{'requirements':{'film_thickness_um':.6,'slab_thickness_um':.3,'ridge_width_um':1.4}},
           'top_epsilon':1.,'bottom_epsilon':2.0736,'materials':{'0.775':{'laboratory_epsilon':np.diag([4.,5.,5.]).tolist()}}}


def test_graded_mesh_keeps_interfaces_topology_and_positive_cells():
    data=graded_mesh(model());receipt=material_calibration(data,model())
    assert receipt['material_interfaces_fitted']
    assert receipt['triangles']==12800
    x=data['vertices'].reshape(81,81,2)[:,0,0]
    assert np.diff(x).min()<.005
    assert {-.7,.7}.issubset(set(x))


def test_interpolation_and_reconstruction_of_periodic_constant():
    data=mesh(model(),2)
    constant=np.array([1.,2.,.5j,3.,4.,.75j])
    coeff=interpolate_high(data,lambda p:np.broadcast_to(constant,p.shape[:-1]+(6,)))
    field=field_from_coefficients(data,coeff)
    points=np.random.default_rng(17).uniform(-6,6,(20,2))
    assert np.max(abs(field(points)-constant))<1e-12


def test_same_mesh_polynomial_reconstruction_interpolation():
    data=mesh(model(),2);ids,sign,nd=high.topology(data)
    coeff=np.random.default_rng(19).normal(size=nd)
    # Interior moments and shared traces of a conforming polynomial reproduce
    # on the same mesh, including periodic seam and P3 edge permutations.
    reconstructed=interpolate_high(data,field_from_coefficients(data,coeff))
    assert np.max(abs(reconstructed-coeff))<2e-10
