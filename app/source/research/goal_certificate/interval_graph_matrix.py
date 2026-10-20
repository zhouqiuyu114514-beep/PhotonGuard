"""Exact-polynomial continuous first-order graph forms with outward arithmetic."""
import numpy as np
from fractions import Fraction as F
from .interval_arithmetic import R,C,rational,stack_r,stack_c,gershgorin
from .pump_slab_envelope import pi_interval
from .conforming_trials import EDGES,audit

def local_fields(data,start,stop):
    ti=data['triangles'][start:stop];v=R(data['vertices'][ti]);num=[]
    det=(v[:,1,0]-v[:,0,0])*(v[:,2,1]-v[:,0,1])-(v[:,1,1]-v[:,0,1])*(v[:,2,0]-v[:,0,0])
    assert np.all(det.lo>0)
    for i,j,k in ((0,1,2),(1,2,0),(2,0,1)):
        num.append(stack_r([v[:,j,1]-v[:,k,1],v[:,k,0]-v[:,j,0]],axis=1)/det[:,None])
    grad=stack_r(num,axis=1)
    edges=C.point(data['edge_dofs'][data['edge_ids'][start:stop]])*data['edge_signs'][start:stop,:,None,None]
    nodes=C.point(data['node_z_dofs'][data['periodic_node_ids'][ti]])
    values=[];derivatives=[]
    for kind in (0,1):
        transverse=[]
        for component in (0,1):
            vertex=[]
            for l in range(3):
                value=C(0)
                for e,(i,j) in enumerate(EDGES):
                    coefficient=int(l==i)*grad[:,j,component]-int(l==j)*grad[:,i,component]
                    value=value+edges[:,e,kind,:]*coefficient[:,None]
                vertex.append(value)
            transverse.append(stack_c(vertex,axis=1))
        values.append(transverse+[nodes[:,:,kind,:]])
        dz=[]
        for a in (0,1):
            out=C(0)
            for j in range(3):out=out+nodes[:,j,kind,:]*grad[:,j,a,None]
            dz.append(out)
        cz=C(0)
        for e,(i,j) in enumerate(EDGES):
            cross=2*(grad[:,i,0]*grad[:,j,1]-grad[:,i,1]*grad[:,j,0])
            cz=cz+edges[:,e,kind,:]*cross[:,None]
        derivatives.append(dz+[cz])
    return values,derivatives,det/2

def action(values,derivatives,k,inverse_two_pi):
    E,H=values;dE,dH=derivatives
    def expand(a):return a[:,None,:]*np.ones((1,3,1))
    NE=[expand(dH[1]*inverse_two_pi).times_i()+H[1]*k,
        -H[0]*k-expand(dH[0]*inverse_two_pi).times_i(),
        expand(dH[2]*inverse_two_pi).times_i()]
    NH=[-expand(dE[1]*inverse_two_pi).times_i()-E[1]*k,
        E[0]*k+expand(dE[0]*inverse_two_pi).times_i(),
        -expand(dE[2]*inverse_two_pi).times_i()]
    return NE+NH

def integrate(a,b,area,weight):
    # Integral of two affine polynomials on a triangle: area/12 times
    # (sum of same-vertex products + product of the sums of vertex values).
    diagonal=(a.conj()[:,:,:,None]*b[:,:,None,:]).sum(axis=1)
    total=a.sum(axis=1).conj()[:,:,None]*b.sum(axis=1)[:,None,:]
    return ((diagonal+total)*(area*weight/12)[:,None,None]).sum(axis=0)

def assemble(data,wavelength,s,tau=F(1,20),target=None,batch=512):
    conformity=audit(data);wave=F(wavelength);parameter=F(s);target=1/wave if target is None else F(target)
    assert 0<tau<target
    c=1/(target-tau);pl,ph=pi_interval();pi=R(rational(pl).lo,rational(ph).hi);inv_pi=1/(2*pi)
    k=rational(parameter/wave);k1=rational(1/wave);dim=data['edge_dofs'].shape[-1]
    zero=lambda:C(np.zeros((dim,dim)),np.zeros((dim,dim)))
    mass=zero();nform=zero();graph=zero();g2=zero()
    for first in range(0,len(data['triangles']),batch):
        stop=min(first+batch,len(data['triangles']));values,derivatives,area=local_fields(data,first,stop)
        fields=values[0]+values[1];NU=action(values,derivatives,k,inv_pi)
        E,H=values
        N1=[H[1]*k1,-H[0]*k1,H[2]*0,-E[1]*k1,E[0]*k1,E[2]*0]
        eps=R(data['epsilon'][first:stop])
        for comp in range(6):
            weight=eps[:,comp] if comp<3 else R(np.ones(stop-first))
            mass=mass+integrate(fields[comp],fields[comp],area,weight)
            nform=nform+integrate(fields[comp],NU[comp],area,R(np.ones(stop-first)))
            graph=graph+integrate(NU[comp],NU[comp],area,1/weight)
            g2=g2+integrate(N1[comp],N1[comp],area,1/weight)
    Rform=nform*rational(1+2*c*tau)-graph*rational(c)-mass*rational(tau+c*tau*tau)
    positive=gershgorin(Rform)
    return {'status':'POSITIVE_COUNT_ENDPOINT_VERIFIED' if positive['positive_definite'] else 'WITNESS_INSUFFICIENT',
        'parameter_s_exact':str(parameter),'wavelength_exact':str(wave),'tau_exact':str(tau),'target_frequency_exact':str(target),'c_exact':str(c),
        'trial_dimension':dim,'mass':mass.export(),'N':nform.export(),'continuous_graph':graph.export(),
        'R':Rform.export(),'G2':g2.export(),'positive_definiteness':positive,'conformity':conformity,
        'parameter_concavity':'R2=-c*Gram_M_inverse(N1 V); PSD of Gram follows positive piecewise epsilon, common exact DOFs and common domain',
        'arithmetic':'Exact stored binary64 DOFs/coordinates/epsilon; outward each real/complex operation, exact affine polynomial formula, pairwise sums',
        'physical_eigensolves':0,'new_API_calls':0},(mass,nform,graph)
