import numpy as np
from research.goal_certificate.static_condensation import condense,reconstruct


def test_constraint_and_interior_elimination_match_full_independent_solve():
    rng=np.random.default_rng(2323);blocks=rng.normal(size=(2,3,3))
    K=blocks.transpose(0,2,1)@blocks+np.eye(3)*.2
    ids=np.array([[0,1,2],[1,3,4]]);b=rng.normal(size=5)
    full=np.zeros((5,5))
    for local,index in zip(K,ids):full[np.ix_(index,index)]+=local
    expected=np.linalg.solve(full,b);expected/=np.dot(b,expected)
    c=condense(K,ids,b,interior=np.array([2]));S=np.zeros((3,3))
    for local,index in zip(c['S'],c['trace_ids']):S[np.ix_(index,index)]+=local
    y=np.linalg.solve(S,c['rhs']);actual,alpha=reconstruct(c,y,5)
    assert np.linalg.norm(actual-expected)<1e-12
    assert abs(np.dot(b,actual)-1)<1e-12
    assert np.linalg.norm(full@actual-alpha*b)<1e-12
