from fractions import Fraction as F
import numpy as np
from research.goal_certificate.strict_high_order_field import (
    polygon_moment,clip,inner,rational_array,GRAM,VECTOR,SCALAR,POWERS,combine,inside_box_gram)
from research.goal_certificate.interval_arithmetic import R,C
from research.goal_certificate import higher_order_trace as high


def test_exact_polygon_clipping_known_area_and_moment():
    triangle=[(F(0),F(0)),(F(1),F(0)),(F(0),F(1))]
    cut=clip(triangle,F(1),F(0),F(1,2))
    assert polygon_moment(cut,0,0)==F(3,8)
    assert polygon_moment(cut,1,0)==F(1,12)
    assert polygon_moment(triangle,2,3)==F(1,420)
    assert clip(triangle,F(-1),0,F(-2))==[]


def test_outward_polynomial_cancellation_encloses_exact_norm():
    coefficients=np.zeros((1,10),complex);coefficients[0,1]=1;coefficients[0,2]=-1
    poly=C.point(coefficients);value=inner(poly,poly,rational_array(GRAM),R(np.ones(1)))
    assert F(value.lo[0])<=F(1,12)<=F(value.hi[0])
    assert value.hi[0]-value.lo[0]<1e-13


def test_rational_polynomial_representation_matches_nodal_evaluation():
    bary=np.array([[.2,.3,.5],[.4,.1,.5],[.1,.8,.1]])
    powers=np.array([[x**a*y**b for a,b in POWERS] for _,x,y in bary])
    vector,curl,scalar,grad=high.reference(bary)
    for component in (0,1):assert np.max(abs(powers@np.array(VECTOR[component],float)-vector[:,component,:]))<1e-12
    assert np.max(abs(powers@np.array(SCALAR,float)-scalar))<1e-13


def test_clipped_region_gram_encloses_known_moment():
    # Reference triangle mapped to x=2*xi, y=eta. A central box of halfwidth1
    # clips exactly xi<=1/2; the Gram excludes the geometric determinant.
    vertices=np.array([[[0.,0.],[2.,0.],[0.,1.]]])
    gram,cuts=inside_box_gram(vertices,F(1))
    assert cuts==1
    assert F(gram.lo[0,0,0])<=F(3,8)<=F(gram.hi[0,0,0])
    assert F(gram.lo[0,0,1])<=F(1,12)<=F(gram.hi[0,0,1])
def test_vector_zero_monomials_keep_batched_complex_shapes():
    from research.goal_certificate.strict_high_order_field import combine,derivative,VECTOR
    from research.goal_certificate.interval_arithmetic import C
    import numpy as np
    dofs=C.point(np.ones((3,15),complex))
    for matrix in VECTOR:
        poly=combine(dofs,matrix)
        assert poly.re.lo.shape==poly.im.lo.shape==(3,10)
        for axis in (0,1):
            grad=derivative(poly,axis)
            assert grad.re.lo.shape==grad.im.lo.shape==(3,10)
