import numpy as np
from research.goal_certificate import higher_order_trace as high
from research.goal_certificate.shared_trace_proposal import (quadrature,interpolate,topology as low_topology,local_basis as low_basis)
from test_shared_trace_proposal import triangle
from research.goal_certificate.conforming_trials import mesh


def test_moment_duality_by_independent_quadrature():
    t,w=np.polynomial.legendre.leggauss(4);t=(t+1)/2;w=w/2
    verts=np.array([[0.,0.],[1.,0.],[0.,1.]]);rows=[]
    for e,(i,j) in enumerate(high.EDGES):
        bary=np.zeros((4,3));bary[:,i]=1-t;bary[:,j]=t
        vec,*_=high.reference(bary);tangent=verts[j]-verts[i]
        val=np.einsum('qci,c->qi',vec,tangent)
        for polynomial in (np.ones(4),2*t-1,6*t*t-6*t+1):rows.append(np.einsum('q,qi->i',w*polynomial,val))
    bary,w=quadrature(4);vec,*_=high.reference(bary)
    for component in (0,1):
        for mon in (np.ones(len(w)),bary[:,1],bary[:,2]):rows.append(np.einsum('q,qi->i',w*mon,vec[:,component,:]))
    assert np.max(abs(np.array(rows)-np.eye(15)))<1e-12


def test_p3_nodal_values_and_analytic_derivatives():
    bary=np.array(high.ALPHAS,float)/3
    _,_,p3,_=high.reference(bary)
    assert np.max(abs(p3-np.eye(10)))<1e-13
    bary,w=quadrature(4);x,y=bary[:,1],bary[:,2]
    values=np.array([a[1]**3+2*a[1]*a[2]**2 for a in np.array(high.ALPHAS,float)/3])
    _,_,p3,grad=high.reference(bary)
    assert np.max(abs(p3@values-(x**3+2*x*y*y)))<1e-13
    assert np.max(abs(np.einsum('qic,i->qc',grad,values)-np.stack((3*x*x+2*y*y,4*x*y),axis=1)))<1e-12


def test_low_field_embedding_preserves_continuous_action():
    data=triangle()
    def field(p):
        x,y=p[...,0],p[...,1]
        return np.stack((1+x-2*y-x*y,2-x+y+x*x,1+x*x+x*y+2*y*y,
                         3+2*x-y*y,4+y+x*y,x+y+x*y),axis=-1).astype(complex)
    old=interpolate(data,field);new=high.prolong_low(data,old);bary,w=quadrature(5)
    oi,os,_=low_topology(data);ni,ns,_=high.topology(data)
    ou,on,_=low_basis(data,0,1,bary,2);nu,nn,_=high.local_basis(data,0,1,bary,2)
    for a,b in [(ou,nu),(on,nn)]:
        assert np.max(abs(np.einsum('bqci,bi->bqc',a,old[oi]*os)-np.einsum('bqci,bi->bqc',b,new[ni]*ns)))<2e-12


def test_real_phase_forms_equal_direct_complex_integrals():
    data=triangle();data['epsilon'][:]=[3,4,5]
    ids,forms=high.assemble_real_forms(data,2);phase=high.global_phase(data)
    rng=np.random.default_rng(42);x=rng.normal(size=50);bary,w=quadrature(5)
    U,N,det=high.local_basis(data,0,1,bary,2);_,sign,_=high.topology(data)
    u=np.einsum('bqci,bi->bqc',U,(x*phase)[ids]*sign)[0]
    nu=np.einsum('bqci,bi->bqc',N,(x*phase)[ids]*sign)[0]
    m=np.array([3,4,5,1,1,1]);expected=[np.sum(w[:,None]*abs(u)**2*m),np.sum(w[:,None]*u.conj()*nu),np.sum(w[:,None]*abs(nu)**2/m)]
    for f,target in zip(forms,expected):
        actual=np.dot(x,high.apply_real(f,ids,x))
        assert abs(actual-target)<1e-10*max(1,abs(target))


def test_high_order_periodic_trace_topology():
    model={'task':{'requirements':{'film_thickness_um':1.,'slab_thickness_um':.5,'ridge_width_um':1.5}},
           'top_epsilon':1.,'bottom_epsilon':2.,'materials':{'0.775':{'laboratory_epsilon':np.diag([4.,5.,5.]).tolist()}}}
    data=mesh(model,2);receipt=high.calibrate(data)
    assert receipt['complex_space_dofs']==3840
    assert receipt['shared_trace_max_float_defect']<1e-8
