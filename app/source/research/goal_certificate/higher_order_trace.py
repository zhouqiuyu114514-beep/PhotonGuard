"""Nedelec first-kind k=2 / P3, exact reference moments and shared traces.

Reference polynomials are rational; assembled forms here remain FLOATING
proposals. A fixed unitary longitudinal phase makes the real-coefficient
Maxwell operator real, reducing storage without changing the trial space.
"""
from fractions import Fraction as F
from math import factorial,comb
import numpy as np
from .conforming_trials import EDGES
from .shared_trace_proposal import geometry,quadrature,topology as low_topology,reference as low_reference,COEFFICIENTS as LOW_DUAL


def powers(n):return [(degree-b,b) for degree in range(n+1) for b in range(degree+1)]


def raw_polynomials(k):
    result=[]
    for component in (0,1):
        for a,b in powers(k):result.append({(component,a,b):F(1)})
    for a,b in [(k-b,b) for b in range(k+1)]:
        result.append({(0,a,b+1):F(-1),(1,a+1,b):F(1)})
    return result


LEGENDRE=[[F(1)],[F(-1),F(2)],[F(1),F(-6),F(6)]]


def edge_moment(poly,edge,moment):
    vertices=[(0,0),(1,0),(0,1)];i,j=EDGES[edge];x,y=vertices[i];dx=vertices[j][0]-x;dy=vertices[j][1]-y
    value=F(0)
    for (component,a,b),coefficient in poly.items():
        tangent=(dx,dy)[component]
        for aa in range(a+1):
            for bb in range(b+1):
                mon=F(comb(a,aa)*comb(b,bb)*x**(a-aa)*y**(b-bb)*dx**aa*dy**bb)*coefficient*tangent
                for order,c in enumerate(LEGENDRE[moment]):value+=mon*c/F(aa+bb+order+1)
    return value


def cell_moment(poly,component,a,b):
    return sum(c*F(factorial(i+a)*factorial(j+b),factorial(i+j+a+b+2))
               for (d,i,j),c in poly.items() if d==component)


def dof_matrix(polys,k):
    rows=[[edge_moment(p,e,j) for p in polys] for e in range(3) for j in range(k+1)]
    rows += [[cell_moment(p,d,a,b) for p in polys] for d in (0,1) for a,b in powers(k-1)]
    return rows


def invert_exact(matrix):
    n=len(matrix);aug=[list(row)+[F(i==j) for j in range(n)] for i,row in enumerate(matrix)]
    for j in range(n):
        pivot=next(i for i in range(j,n) if aug[i][j]);aug[j],aug[pivot]=aug[pivot],aug[j]
        v=aug[j][j];aug[j]=[a/v for a in aug[j]]
        for i in range(n):
            if i!=j:
                c=aug[i][j];aug[i]=[a-c*b for a,b in zip(aug[i],aug[j])]
    return [row[n:] for row in aug]


RAW=raw_polynomials(2);DUAL_EXACT=invert_exact(dof_matrix(RAW,2));DUAL=np.array(DUAL_EXACT,dtype=float)
if any(F(float(x))!=x for row in DUAL_EXACT for x in row):
    raise ValueError('REFERENCE_DUAL_NOT_BINARY_EXACT')
ALPHAS=[(3,0,0),(0,3,0),(0,0,3),(2,1,0),(1,2,0),(0,2,1),(0,1,2),(1,0,2),(2,0,1),(1,1,1)]


def reference(bary):
    x,y=bary[:,1],bary[:,2];raw=np.zeros((len(bary),2,15));curl=np.zeros((len(bary),15))
    for j,poly in enumerate(RAW):
        for (d,a,b),c in poly.items():
            raw[:,d,j]+=float(c)*x**a*y**b
            if d==1 and a:curl[:,j]+=float(c*a)*x**(a-1)*y**b
            if d==0 and b:curl[:,j]-=float(c*b)*x**a*y**(b-1)
    values=raw@DUAL;curl=curl@DUAL
    scalar=np.ones((len(bary),10));grad=np.zeros((len(bary),10,2));gl=np.array([[-1,-1],[1,0],[0,1]])
    for j,alpha in enumerate(ALPHAS):
        factors=[(3*bary[:,i]-s)/(s+1) for i,count in enumerate(alpha) for s in range(count)]
        directions=[3*gl[i]/(s+1) for i,count in enumerate(alpha) for s in range(count)]
        scalar[:,j]=np.prod(factors,axis=0)
        for k,direction in enumerate(directions):
            grad[:,j,:]+=np.prod([v for l,v in enumerate(factors) if l!=k],axis=0)[:,None]*direction
    return values,curl,scalar,grad


def topology(data):
    edges=data['edge_ids'];nt=len(edges);ne=len(data['global_edge_nodes']);nn=int(data['periodic_node_ids'].max())+1
    nodes=data['periodic_node_ids'][data['triangles']];trans=3*ne+6*nt
    edge_nodes=np.where(data['edge_signs'][:,:,None]>0,np.array([0,1]),np.array([1,0]))
    ids=np.concatenate(((3*edges[:,:,None]+np.arange(3)).reshape(nt,9),
        3*ne+6*np.arange(nt)[:,None]+np.arange(6),trans+nodes,
        (trans+nn+2*edges[:,:,None]+edge_nodes).reshape(nt,6),
        (trans+nn+2*ne+np.arange(nt))[:,None]),axis=1)
    sign=np.ones((nt,25));sign[:,:9]=np.stack((data['edge_signs'],np.ones_like(edges),data['edge_signs']),axis=-1).reshape(nt,9)
    nd=trans+nn+2*ne+nt
    return np.concatenate((ids,ids+nd),axis=1),np.tile(sign,(1,2)),2*nd


def global_phase(data):
    nt=len(data['triangles']);ne=len(data['global_edge_nodes']);nn=int(data['periodic_node_ids'].max())+1
    trans=3*ne+6*nt;nd=trans+nn+2*ne+nt
    phase=np.ones(2*nd,complex);phase[trans:nd]=1j;phase[nd+trans:]=1j
    return phase


def local_basis(data,start,stop,bary,k):
    _,jac,inv,det=geometry(data,start,stop);vec,curl,scalar,grad=reference(bary)
    transverse=np.einsum('qci,bcd->bqdi',vec,inv);dz=np.einsum('qid,bdc->bqci',grad,inv)
    n=stop-start;q=len(bary);U=np.zeros((n,q,6,50),complex);N=np.zeros_like(U)
    U[:,:,:2,:15]=transverse;U[:,:,2,15:25]=scalar
    U[:,:,3:5,25:40]=transverse;U[:,:,5,40:50]=scalar;t=1/(2*np.pi)
    N[:,:,0,:]=k*U[:,:,4,:];N[:,:,1,:]=-k*U[:,:,3,:];N[:,:,3,:]=-k*U[:,:,1,:];N[:,:,4,:]=k*U[:,:,0,:]
    N[:,:,0,40:50]+=1j*t*dz[:,:,1,:];N[:,:,1,40:50]-=1j*t*dz[:,:,0,:];N[:,:,2,25:40]=1j*t*curl[None,:,:]/det[:,None,None]
    N[:,:,3,15:25]-=1j*t*dz[:,:,1,:];N[:,:,4,15:25]+=1j*t*dz[:,:,0,:];N[:,:,5,:15]=-1j*t*curl[None,:,:]/det[:,None,None]
    return U,N,det


def prolong_low(data,coeff):
    oldids,oldsign,_=low_topology(data);ids,sign,nd=topology(data)
    # Exact functional evaluation on the old vector polynomial space.
    transfer=np.array(dof_matrix(raw_polynomials(1),2),float)@LOW_DUAL
    _,_,p2,_=low_reference(np.array(ALPHAS,float)/3)
    scalar=p2
    localold=coeff[oldids]*oldsign;local=np.zeros((len(ids),50),complex)
    for kind in (0,1):
        local[:,25*kind:25*kind+15]=localold[:,14*kind:14*kind+8]@transfer.T
        local[:,25*kind+15:25*kind+25]=localold[:,14*kind+8:14*kind+14]@scalar.T
    values=local*sign;count=np.bincount(ids.ravel(),minlength=nd)
    return (np.bincount(ids.ravel(),weights=values.real.ravel(),minlength=nd)+1j*np.bincount(ids.ravel(),weights=values.imag.ravel(),minlength=nd))/count


def assemble_real_forms(data,k):
    ids,sign,nd=topology(data);nt=len(ids);bary,w=quadrature(4);phase=global_phase(data)
    forms=[np.empty((nt,50,50),float) for _ in range(3)]
    for start in range(0,nt,32):
        stop=min(nt,start+32);U,N,det=local_basis(data,start,stop,bary,k)
        transform=sign[start:stop]*phase[ids[start:stop]];U*=transform[:,None,None,:];N*=transform[:,None,None,:]
        material=np.concatenate((data['epsilon'][start:stop],np.ones((stop-start,3))),axis=1);weight=det[:,None]*w
        local=[np.einsum('bqci,bqcj,bqc->bij',U.conj(),U,weight[:,:,None]*material[:,None,:],optimize=True),
               np.einsum('bqci,bqcj,bq->bij',U.conj(),N,weight,optimize=True),
               np.einsum('bqci,bqcj,bqc->bij',N.conj(),N,weight[:,:,None]/material[:,None,:],optimize=True)]
        for target,value in zip(forms,local):
            if np.any(value.imag!=0):raise ValueError('PHASE_TRANSFORM_NOT_REAL')
            target[start:stop]=value.real
    return ids,forms


def apply_real(matrix,ids,x):
    if np.iscomplexobj(x):raise ValueError('REAL_REPRESENTATION_REQUIRED')
    v=np.einsum('bij,bj->bi',matrix,x[ids],optimize=False)
    return np.bincount(ids.ravel(),weights=v.ravel(),minlength=len(x))


def calibrate(data):
    ids,sign,nd=topology(data);nt=len(ids);ne=len(data['global_edge_nodes'])
    if np.any(np.bincount(data['edge_ids'].ravel())!=2):raise ValueError('PERIODIC_EDGE_INCIDENCE')
    rng=np.random.default_rng(20261010);coeff=rng.standard_normal(nd)
    vertices=data['vertices'][data['triangles']];traces=np.empty((nt,3,4,4),complex)
    for edge,(i,j) in enumerate(EDGES):
        t=np.array([.125,.375,.625,.875]);bary=np.zeros((4,3));bary[:,i]=1-t;bary[:,j]=t
        for start in range(0,nt,64):
            stop=min(nt,start+64);U,N,det=local_basis(data,start,stop,bary,0)
            u=np.einsum('bqci,bi->bqc',U,coeff[ids[start:stop]]*sign[start:stop])
            tangent=(vertices[start:stop,j]-vertices[start:stop,i])*data['edge_signs'][start:stop,edge,None]
            values=np.stack((np.einsum('bqc,bc->bq',u[:,:,:2],tangent),u[:,:,2],
                             np.einsum('bqc,bc->bq',u[:,:,3:5],tangent),u[:,:,5]),axis=-1)
            reverse=data['edge_signs'][start:stop,edge]<0;values[reverse]=values[reverse,::-1]
            traces[start:stop,edge]=values
    order=np.argsort(data['edge_ids'].ravel(),kind='stable').reshape(ne,2)
    pairs=traces.reshape(-1,4,4)[order];defect=float(np.max(abs(pairs[:,0]-pairs[:,1])))
    if defect>1e-8:raise ValueError('SHARED_HIGH_ORDER_TRACE')
    return {'status':'PASS','complex_space_dofs':nd,'triangles':nt,'shared_trace_max_float_defect':defect,
        'polynomial_family':'Nedelec first-kind k2 / P3','reference_dual_exact_binary_coefficients':True,
        'edge_moment_orientation':'(-1)^(moment+1) for reversal','P3_edge_node_orientation':'swap two nodes when reversed',
        'phase_transform':'unitary i on longitudinal components, makes real diagonal-epsilon Maxwell forms real'}
