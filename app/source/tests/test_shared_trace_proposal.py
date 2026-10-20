import numpy as np
from research.goal_certificate.shared_trace_proposal import (
    reference, interpolate, topology, local_basis, quadrature, COEFFICIENTS, mesh, calibrate)


def triangle():
    return dict(vertices=np.array([[0.,0.],[1.,0.],[0.,1.]]),triangles=np.array([[0,1,2]]),
                periodic_node_ids=np.arange(3),edge_ids=np.array([[0,1,2]]),
                edge_signs=np.array([[1,1,-1]]),global_edge_nodes=np.array([[0,1],[1,2],[0,2]]),
                epsilon=np.ones((1,3)))


def test_exact_polynomial_interpolation_and_curl():
    data=triangle()
    def field(p):
        x,y=p[...,0],p[...,1]
        return np.stack((1+x-2*y-x*y,2-x+y+x*x,1+x*x+x*y+2*y*y,
                         3+2*x-y*y,4+y+x*y,x+y+x*y),axis=-1).astype(complex)
    coeff=interpolate(data,field);ids,sign,nd=topology(data);bary,w=quadrature(4)
    U,N,det=local_basis(data,0,1,bary,2.)
    value=np.einsum('bqci,bi->bqc',U,coeff[ids]*sign)[0]
    assert np.max(abs(value-field(bary[:,1:])))<1e-12
    nu=np.einsum('bqci,bi->bqc',N,coeff[ids]*sign)[0]
    x,y=bary[:,1],bary[:,2];f=field(bary[:,1:]);t=1/(2*np.pi)
    direct=np.stack((1j*(1+x)*t+2*f[:,4],-2*f[:,3]-1j*(1+y)*t,1j*3*y*t,
        -1j*(x+4*y)*t-2*f[:,1],2*f[:,0]+1j*(2*x+y)*t,-1j*(1+3*x)*t),axis=1)
    assert np.max(abs(nu-direct))<1e-12


def test_oriented_edge_reversal_preserves_linear_tangential_trace():
    # Moment zero reverses sign, first Legendre moment does not.
    bary=np.array([[.8,.2,0],[.4,.6,0],[.1,.9,0]])
    vec,*_=reference(bary)
    dofs=np.array([.3,.7,0,0,0,0,0,0]);trace=vec[:,0,:]@dofs
    reverse_dofs=np.array([-.3,.7,0,0,0,0,0,0])
    reverse_vec,*_=reference(bary[:,[1,0,2]])
    assert np.max(abs(trace+reverse_vec[:,0,:]@reverse_dofs))<1e-12


def test_uniform_plane_wave():
    data=triangle();data['epsilon'][:]=4
    def field(p):return np.broadcast_to(np.array([1,0,0,0,2,0],complex),p.shape[:-1]+(6,))
    coeff=interpolate(data,field);ids,sign,nd=topology(data);bary,w=quadrature(4)
    U,N,_=local_basis(data,0,1,bary,2.)
    u=np.einsum('bqci,bi->bqc',U,coeff[ids]*sign)
    nu=np.einsum('bqci,bi->bqc',N,coeff[ids]*sign)
    assert np.max(abs(nu-u*np.array([4,4,4,1,1,1])))<1e-12


def test_periodic_shared_traces_and_material_interfaces():
    model={'task':{'requirements':{'film_thickness_um':1.,'slab_thickness_um':.5,'ridge_width_um':1.5}},
           'top_epsilon':1.,'bottom_epsilon':2.,'materials':{'0.775':{'laboratory_epsilon':np.diag([4.,5.,5.]).tolist()}}}
    data=mesh(model,2);receipt=calibrate(data,model)
    assert receipt['complex_dofs']==1792
    assert receipt['material_interfaces_fitted']
    assert receipt['trace_max_float_defect']<1e-9
