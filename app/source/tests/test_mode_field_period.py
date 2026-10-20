"""Synthetic boundary fixtures; no solver runs or changes to stored v1 evidence."""
import numpy as np
import pytest

from photonguard.mode_field_research import pair_metrics,_window_axis_mask


def fields(nx,ny,sx,sy):
    E=np.zeros((nx,ny,1,3),complex);E[...,0]=1.
    H=np.zeros_like(E);H[...,1]=1j
    return {'E':E,'H':H,'electric_energy':np.ones((nx,ny,1)),
        'x_um':(np.arange(nx)/nx-.5)*sx,
        'y_um':(np.arange(ny)/ny-.5)*sy}


@pytest.mark.parametrize('nx,ny,sx,sy',[(320,320,4.,4.),(320,324,4.,4.07),(7,11,4.07,6.13)])
def test_full_period_keeps_both_lower_boundary_rows_without_false_tail(nx,ny,sx,sy):
    first=fields(nx,ny,sx,sy)
    result=pair_metrics(first,first)
    assert result['integration_grid_shape']==[nx,ny]
    for owner in ('first_native_window_and_tail','second_native_window_and_tail'):
        for key in ('E_L2_tail_fraction','H_L2_tail_fraction','electric_energy_tail_fraction'):
            assert result[owner][key]==0.


def test_difference_on_previous_discarded_row_affects_mode_identity_metric():
    first=fields(320,8,4.,4.);second=fields(320,8,4.,4.)
    second['E'][0,:,:,0]=-1.
    result=pair_metrics(first,second)
    expected=((320-2)/320)**2
    assert result['metrics']['E_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(expected,abs=1e-14)
    assert result['metrics']['H_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1.)


def test_lower_boundary_only_energy_is_not_treated_as_zero_field():
    first=fields(320,8,4.,4.)
    for key in ('E','H','electric_energy'):
        first[key][1:]=0
    result=pair_metrics(first,first)
    assert result['integration_grid_shape']==[320,8]
    assert result['metrics']['E_L2_overlap_research']['squared_normalized_overlap']==pytest.approx(1.)
    assert result['first_native_window_and_tail']['electric_energy_tail_fraction']==0.


def test_genuine_larger_domain_tail_remains_and_upper_endpoint_is_excluded():
    result=pair_metrics(fields(32,32,4.1,4.1),fields(48,48,6.15,6.15))
    assert result['integration_grid_shape']==[32,32]
    assert result['second_native_window_and_tail']['E_L2_window_fraction']==pytest.approx(4/9)
    assert result['second_native_window_and_tail']['electric_energy_tail_fraction']==pytest.approx(5/9)


def test_endpoint_roundoff_ties_do_not_absorb_physically_outside_points():
    axis=np.array([-2.-1e-10,-2.,0.,2.-1e-10,2.,2.+1e-10])
    lower=np.nextafter(-2.,np.inf);upper=np.nextafter(2.,np.inf)
    assert _window_axis_mask(axis,[lower,upper]).tolist()==[False,True,True,True,False,False]
