import numpy as np
from research.goal_certificate.convergence_research import solve_forms


def test_constrained_stationarity_matches_independent_dense_solution():
    # A tiny synthetic SPD problem tests the projection/complex conjugation,
    # independently of field interpolation or the PDE discretization.
    M=np.diag([2.,3.,4.,1.]);N=np.diag([2.4,4.2,5.2,1.1])
    G=N@np.linalg.solve(M,N)+np.diag([.01,.02,.03,.04])
    anchor=np.array([1.,.2j,.3+.1j,.4]);initial=np.array([.8+.1j,.3j,.2,.1])
    rho=(np.vdot(initial,N@initial)/np.vdot(initial,M@initial)).real
    b=M@anchor/np.sqrt(np.vdot(anchor,M@anchor).real)
    K=G-rho*(N+N.T)+rho*rho*M
    expected=np.linalg.solve(K,b);expected/=np.vdot(b,expected)
    expected/=np.sqrt(np.vdot(expected,M@expected).real)
    actual,history,checkpoints=solve_forms(np.arange(4)[None,:],[a[None,:,:].astype(complex) for a in [M,N,G]],anchor,initial,outer_limit=1,iterations=100)
    assert np.linalg.norm(actual-expected)<1e-10
    assert history[-1]['cg_info']==0
    assert history[-1]['true_linear_relative_residual']<1e-8
    assert history[-1]['overlap_error']<1e-12


def test_real_storage_solver_agrees_with_complex_storage():
    from research.goal_certificate.higher_order_trace import apply_real
    ids=np.arange(4)[None,:];M=np.eye(4);N=np.diag([1.1,1.2,1.3,1.4]);G=N@N+np.eye(4)*.003
    anchor=np.array([.1,.2,1.,.1]);initial=anchor.copy()
    real,hr,_=solve_forms(ids,[a[None,:,:] for a in [M,N,G]],anchor,initial,iterations=100,outer_limit=1,apply_fn=apply_real)
    complex_,hc,_=solve_forms(ids,[a[None,:,:].astype(complex) for a in [M,N,G]],anchor.astype(complex),initial.astype(complex),iterations=100,outer_limit=1)
    assert np.linalg.norm(real-complex_)<1e-12
    assert hr[-1]['cg_info']==hc[-1]['cg_info']==0
