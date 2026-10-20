from fractions import Fraction as F
from math import factorial
import numpy as np
import pytest
from research.independent_checker_v1.dyadic import Q,Z,S,pi_bounds
from research.independent_checker_v1.reference import P,ALPHA,MOMENT,DUAL,SCALAR,GRAM,BERN,powers,triangle_moments
from research.independent_checker_v1.geometry import box,area,axis_partition
from research.independent_checker_v1.propagation import compare

def contains(q,x):
    lo,hi=map(F,q.export());assert lo<=x<=hi

def test_integer_outward_operations_against_exact_fractions():
    values=[F(-11,7),F(-1,3),F(0),F(1,10),F(17,9),F(2)**-140]
    for a in values:
        for b in values:
            contains(Q(a)+Q(b),a+b);contains(Q(a)-Q(b),a-b);contains(Q(a)*Q(b),a*b)
            if abs(b)>F(1,S):contains(Q(a)/Q(b),a/b)
    with pytest.raises(ValueError,match='ZERO'):Q(1)/Q(-1,1)
    with pytest.raises(ValueError,match='REVERSED'):Q(2,1)

def test_independent_moment_dual_and_nodal_interpolation():
    assert all(sum(MOMENT[i][k]*DUAL[k][j] for k in range(15))==(i==j) for i in range(15) for j in range(15))
    assert all(sum(F(a[1],3)**x*F(a[2],3)**y*SCALAR[k][j] for k,(x,y) in enumerate(P))==(i==j) for i,a in enumerate(ALPHA) for j in range(10))
    # Swapping even/odd moments destroys the defining interpolation equations.
    wrong=[list(row) for row in DUAL]
    for row in wrong:row[0],row[1]=row[1],row[0]
    assert any(sum(MOMENT[i][k]*wrong[k][j] for k in range(15))!=(i==j) for i in range(15) for j in range(15))

def test_bernstein_gram_equals_analytic_monomial_integral():
    for i,(a,b) in enumerate(P):
        for j,(c,d) in enumerate(P):
            actual=sum(BERN[k][i]*GRAM[k][l]*BERN[l][j] for k in range(10) for l in range(10))
            assert actual==F(factorial(a+c)*factorial(b+d),factorial(a+b+c+d+2))

def test_retriangulated_barycentric_moments_through_degree_six():
    half=F(1,2);tri=[[(0,0),(1,0),(half,half)],[(0,0),(half,half),(0,1)]]
    moments=triangle_moments(tri,6).sum(axis=0)
    for k,(a,b) in enumerate(powers(6)):contains(moments[k],F(factorial(a)*factorial(b),factorial(a+b+2)))
    pieces=box([(0,0),(1,0),(0,1)],F(0),half,F(0),half)
    assert sum(map(area,pieces))==F(1,4)
    contains(triangle_moments(pieces,3).sum(axis=0)[P.index((1,1))],F(1,64))

def test_coordinate_shift_and_disjoint_reference_refused():
    a=(np.arange(320)/320-.5)*4
    boundaries,_=axis_partition(a);assert boundaries[0]==-2 and boundaries[-1]==2
    with pytest.raises(ValueError,match='COORDINATES'):axis_partition(a+.00625)
    with pytest.raises(ValueError,match='DISJOINT'):compare([1,2],[3,4],'mass')

def test_joint_phase_not_independent_E_H_rotation():
    # Maxwell cross energy is phase-covariant only when both fields share phase.
    e,h=Z.point(1+2j),Z.point(2-1j)
    a=(e.conj()*h).export();b=((e*Z.point(1j)).conj()*(h*Z.point(1j))).export()
    assert a==b
    assert a!=(e.conj()*(h*Z.point(1j))).export()

def test_machin_enclosure():
    lo,hi=pi_bounds();assert F('3.14159265358979323846264338327950288419716939937510')<lo<hi<F('3.14159265358979323846264338327950288419716939937511')

def test_analytic_constant_maxwell_field_assembly():
    from research.independent_checker_v1.assembly import endpoints
    data={'vertices':np.array([[0.,0.],[1.,0.],[0.,1.]]),'triangles':np.array([[0,1,2]]),'epsilon':np.ones((1,3))}
    coeff=np.zeros(50,complex);coeff[15:25]=1;coeff[40:50]=2
    result=endpoints(data,coeff,np.arange(50).reshape(1,50),np.ones((1,50)),np.ones(1,bool),[0],[F(0)],[F(1)])[0]['integrals']
    for key,value in [('mass',F(5,2)),('electric',F(1,2)),('N',F(0)),('residual2',F(5,2)),('outer',F(0))]:
        lo,hi=map(F,result[key]);assert lo<=value<=hi,key
