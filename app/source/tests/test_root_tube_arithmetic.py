from fractions import Fraction as F
import pytest
from research.goal_certificate.root_tube_arithmetic import recombine_forms,endpoint_temple,tube_bounds


def forms(s):
    def matrix(v):
        a=[[str(v if i==j else 0) for j in range(3)] for i in range(3)];z=[['0']*3 for _ in range(3)]
        return {'real':[a,a],'imag':[z,z]}
    return {'parameter_s_exact':str(s),'wavelength_exact':'31/40','mass':matrix(1),'N':matrix(2+3*s),
        'continuous_graph':matrix((2+3*s)**2),'G2':matrix(9)}


@pytest.mark.parametrize('s',[F(1,2),F(3,2),F(5,2)])
def test_exact_quadratic_recombination_including_extrapolation(s):
    out=recombine_forms(forms(F(0)),forms(F(2)),s)
    assert F(out['N']['real'][0][0][0])==2+3*s
    assert F(out['continuous_graph']['real'][1][1][1])==(2+3*s)**2


def test_temple_contains_direct_symmetric_matrix_eigenvalue():
    # diag(1,2,4), normalized u=(0,sqrt(.99),sqrt(.01)).
    rho=F(202,100);variance=F(396,10000)
    lo,hi=endpoint_temple([rho,rho],variance,F(3,2),F(7,2))
    assert lo<2<hi
    with pytest.raises(ValueError):endpoint_temple([F(1),F(1)],variance,F(3,2),F(7,2))


def test_affine_common_trial_tube_has_unique_crossing():
    f=1/F(.775);sc=F(21,10);h=F(1,1000)
    endpoints=[{'true_rayleigh_interval':[f-h,f-h],'true_rayleigh_residual2_upper':0},
        {'true_rayleigh_interval':[f+h,f+h],'true_rayleigh_residual2_upper':0}]
    result=tube_bounds(endpoints,sc,h,F(1283,1000),F(1299,1000),F(13,10))
    assert result['root_uniqueness_if_bound_inputs']
    assert F(result['eigenvalue_derivative_lower_exact'])==1


def test_tube_refuses_missing_true_rayleigh():
    with pytest.raises(KeyError):tube_bounds([{'arbitrary_shift':1}]*2,F(21,10),F(1,1000),1,2,1)
