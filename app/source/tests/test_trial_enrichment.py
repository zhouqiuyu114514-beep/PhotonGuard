from math import factorial
import numpy as np
from research.goal_certificate.trial_enrichment_preflight import quadrature

def test_duffy_rule_matches_all_degree_six_barycentric_moments():
    bary,w=quadrature()
    for i in range(7):
        for j in range(7-i):
            for k in range(7-i-j):
                exact=factorial(i)*factorial(j)*factorial(k)/factorial(i+j+k+2)
                actual=np.sum(w*bary[:,0]**i*bary[:,1]**j*bary[:,2]**k)
                assert abs(actual-exact)<2e-15

def test_cubic_bubble_preserves_every_edge_trace():
    t=np.array([0.,.13,.5,.91,1.])
    for edge in range(3):
        bary=np.zeros((len(t),3));bary[:,(edge+1)%3]=t;bary[:,(edge+2)%3]=1-t
        assert np.all(np.prod(bary,axis=1)==0)
