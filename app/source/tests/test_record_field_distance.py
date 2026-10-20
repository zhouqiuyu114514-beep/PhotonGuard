from fractions import Fraction as F
import numpy as np
from research.goal_certificate.record_field_distance import axis_partition,intersections,polygon_moments,distance_bound,POWERS
from research.goal_certificate.strict_high_order_field import polygon_moment


def test_periodic_record_cells_cover_domain_with_wrapped_center():
    bounds,index=axis_partition([-1.8,-.1,.7,1.9])
    assert bounds[0]==-2 and bounds[-1]==2
    assert index[0]==3 and index[-1]==3


def test_exact_cross_partition_and_interval_moments():
    xb,xi=axis_partition([-1.5,-.5,.5,1.5]);yb,yi=axis_partition([-1.4,-.2,.8,1.7])
    triangle=np.array([[-1.1,-.9],[1.3,-.9],[1.3,1.2]])
    pieces=intersections(triangle,xb,yb,xi,yi);polygons=[p for p,i,j in pieces];mom=polygon_moments(polygons)
    for k,p in enumerate(polygons):
        for j,(a,b) in enumerate(POWERS):
            exact=polygon_moment(p,a,b)
            assert F(mom.lo[k,j])<=exact<=F(mom.hi[k,j])
    assert sum(polygon_moment(p,0,0) for p in polygons)==F(1,2)


def test_distance_is_global_phase_invariant_and_uses_both_norms():
    data={'record_mass':[4,4],'cross_record_trial':{'real':[0,0],'imag':[2,2]}}
    result=distance_bound(data,[1,1],F(1,10))
    assert result['record_to_trial_distance_upper']==0
    assert result['preregistered_quarter_distance_passes']
    assert result['unique_dominant_rank_one_component']


def test_near_orthogonal_record_is_not_associated():
    data={'record_mass':[1,1],'cross_record_trial':{'real':[0,0],'imag':[0,0]}}
    result=distance_bound(data,[1,1],0)
    assert not result['preregistered_quarter_distance_passes']
    assert not result['unique_dominant_rank_one_component']
