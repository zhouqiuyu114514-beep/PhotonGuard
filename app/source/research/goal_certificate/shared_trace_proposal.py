"""Floating Nedelec first-kind k=1 / longitudinal P2, periodic trial proposal.

This is NOT an eigenpair/continuous-field certificate. Local continuous graph
forms drive a matrix-free projected Krylov minimization with a fixed nonzero
anchor. No projected-operator square, global dense normal matrix or sparse LU.
"""
from fractions import Fraction as F
import math
import time
import numpy as np
from scipy.sparse.linalg import LinearOperator, cg
from .conforming_trials import EDGES, mesh


def raw_basis(x, y):
    one, zero = x*0+1, x*0
    return np.array([(one,zero),(x,zero),(y,zero),(zero,one),(zero,x),(zero,y),
                     (-x*y,x*x),(-y*y,x*y)]).transpose(2,1,0)


def reference_coefficients():
    """Exact eight moment dual; all resulting coefficients are integers."""
    verts=[(F(0),F(0)),(F(1),F(0)),(F(0),F(1))];D=[]
    def raw(x,y):
        return [(1,0),(x,0),(y,0),(0,1),(0,x),(0,y),(-x*y,x*x),(-y*y,x*y)]
    for i,j in EDGES:
        a,b=verts[i],verts[j];tangent=[b[d]-a[d] for d in (0,1)]
        for moment in (0,1):
            row=[F(0)]*8
            for t,w in [(F(0),F(1,6)),(F(1,2),F(2,3)),(F(1),F(1,6))]:
                values=raw(a[0]+t*tangent[0],a[1]+t*tangent[1])
                for k,v in enumerate(values):
                    row[k]+=w*(1 if moment==0 else 2*t-1)*sum(v[d]*tangent[d] for d in (0,1))
            D.append(row)
    for d in (0,1):
        D.append([sum(F(1,6)*raw(x,y)[k][d] for x,y in [(F(1,6),F(1,6)),(F(2,3),F(1,6)),(F(1,6),F(2,3))]) for k in range(8)])
    aug=[row+[F(i==j) for j in range(8)] for i,row in enumerate(D)]
    for j in range(8):
        pivot=next(i for i in range(j,8) if aug[i][j])
        aug[j],aug[pivot]=aug[pivot],aug[j];v=aug[j][j];aug[j]=[a/v for a in aug[j]]
        for i in range(8):
            if i!=j:
                a=aug[i][j];aug[i]=[x-a*y for x,y in zip(aug[i],aug[j])]
    inverse=[row[8:] for row in aug]
    if any(x.denominator!=1 for row in inverse for x in row):
        raise ValueError('REFERENCE_COEFFICIENT_NOT_EXACT_INTEGER')
    return np.array(inverse,dtype=float)


COEFFICIENTS=reference_coefficients()


def quadrature(order=3):
    x,w=np.polynomial.legendre.leggauss(order);x=(x+1)/2;w=w/2
    u,v=np.meshgrid(x,x,indexing='ij');wu,wv=np.meshgrid(w,w,indexing='ij')
    u=u.ravel();v=v.ravel()
    return np.stack(((1-u)*(1-v),u,(1-u)*v),axis=1),(wu*wv).ravel()*(1-u)


def reference(bary):
    x,y=bary[:,1],bary[:,2]
    vec=raw_basis(x,y)@COEFFICIENTS
    zero=x*0
    curl=np.stack((zero,zero,-zero-1,zero,zero+1,zero,3*x,3*y),axis=1)@COEFFICIENTS
    p2=np.concatenate((bary*(2*bary-1),np.stack([4*bary[:,i]*bary[:,j] for i,j in EDGES],axis=1)),axis=1)
    gradlam=np.array([[-1,-1],[1,0],[0,1]])
    grad=np.concatenate(((4*bary-1)[:,:,None]*gradlam[None,:,:],
            np.stack([4*(bary[:,i,None]*gradlam[j]+bary[:,j,None]*gradlam[i]) for i,j in EDGES],axis=1)),axis=1)
    return vec,curl,p2,grad


def topology(data):
    edge=data['edge_ids'];ne=len(data['global_edge_nodes']);nt=len(edge)
    nodes=data['periodic_node_ids'][data['triangles']];nn=int(data['periodic_node_ids'].max())+1
    ids=np.concatenate(((2*edge[:,:,None]+np.arange(2)).reshape(nt,6),
        2*ne+2*np.arange(nt)[:,None]+np.arange(2),2*ne+2*nt+nodes,
        2*ne+2*nt+nn+edge),axis=1)
    sign=np.ones((nt,14));sign[:,:6:2]=data['edge_signs']
    nd=2*ne+2*nt+nn+ne
    return np.concatenate((ids,ids+nd),axis=1),np.tile(sign,(1,2)),2*nd


def geometry(data,start,stop):
    vertices=data['vertices'][data['triangles'][start:stop]]
    jac=np.stack((vertices[:,1]-vertices[:,0],vertices[:,2]-vertices[:,0]),axis=2)
    det=np.linalg.det(jac)
    if not np.all(det>0):raise ValueError('TRIANGLE_ORIENTATION')
    return vertices,jac,np.linalg.inv(jac),det


def local_basis(data,start,stop,bary,k):
    _,jac,inv,det=geometry(data,start,stop);vec,curl,p2,grad=reference(bary)
    # Covariant Piola: row vector b_phys = b_ref J^{-1}.
    transverse=np.einsum('qci,bcd->bqdi',vec,inv)
    dz=np.einsum('qid,bdc->bqci',grad,inv)
    n=stop-start;q=len(bary);U=np.zeros((n,q,6,28),complex);N=np.zeros_like(U)
    U[:,:,:2,:8]=transverse;U[:,:,2,8:14]=p2
    U[:,:,3:5,14:22]=transverse;U[:,:,5,22:28]=p2
    t=1/(2*np.pi)
    N[:,:,0,:]=k*U[:,:,4,:];N[:,:,1,:]=-k*U[:,:,3,:]
    N[:,:,3,:]=-k*U[:,:,1,:];N[:,:,4,:]=k*U[:,:,0,:]
    N[:,:,0,22:28]+=1j*t*dz[:,:,1,:];N[:,:,1,22:28]-=1j*t*dz[:,:,0,:]
    N[:,:,2,14:22]=1j*t*curl[None,:,:]/det[:,None,None]
    N[:,:,3,8:14]-=1j*t*dz[:,:,1,:];N[:,:,4,8:14]+=1j*t*dz[:,:,0,:]
    N[:,:,5,:8]=-1j*t*curl[None,:,:]/det[:,None,None]
    return U,N,det


def interpolate(data, field):
    """Physical field(points)[...,6]; bilinear original arrays use frozen coords."""
    ids,sign,nd=topology(data);nt=len(ids);local=np.zeros((nt,28),complex)
    bary,w=quadrature(3);t,ew=np.polynomial.legendre.leggauss(3);t=(t+1)/2;ew=ew/2
    for start in range(0,nt,128):
        stop=min(nt,start+128);v,jac,inv,det=geometry(data,start,stop)
        for edge,(i,j) in enumerate(EDGES):
            vec=v[:,j]-v[:,i];p=v[:,i,None,:]+t[None,:,None]*vec[:,None,:]
            values=field(p)
            for kind in (0,1):
                tangent=np.einsum('bqc,bc->bq',values[:,:,kind*3:kind*3+2],vec)
                for moment in (0,1):
                    local[start:stop,kind*14+2*edge+moment]=np.sum(tangent*ew*(1 if moment==0 else 2*t-1),axis=1)
        pts=np.einsum('qi,bic->bqc',bary,v);value=field(pts)
        for kind in (0,1):
            pullback=np.einsum('bqc,bcd->bqd',value[:,:,3*kind:3*kind+2],jac)
            local[start:stop,14*kind+6:14*kind+8]=np.einsum('q,bqc->bc',w,pullback)
        pnodes=np.concatenate((v,np.stack([(v[:,i]+v[:,j])/2 for i,j in EDGES],axis=1)),axis=1)
        value=field(pnodes)
        local[start:stop,8:14]=value[:,:,2];local[start:stop,22:28]=value[:,:,5]
    shared=local*sign;flat=ids.ravel();cnt=np.bincount(flat,minlength=nd)
    coeff=(np.bincount(flat,weights=shared.real.ravel(),minlength=nd)
           +1j*np.bincount(flat,weights=shared.imag.ravel(),minlength=nd))/cnt
    return coeff


def raw_field_interpolator(path):
    with np.load(path,allow_pickle=False) as z:
        x=z['x_um'].copy();y=z['y_um'].copy()
        fields=np.concatenate((z['E'][:,:,0,:],z['H'][:,:,0,:]),axis=2)
    for axis in (x,y):
        if len(axis)<2 or not np.allclose(np.diff(axis),4/len(axis),rtol=0,atol=2e-14):
            raise ValueError('RAW_COORDINATES_NOT_UNIFORM_PERIODIC')
    def evaluate(points):
        u=np.mod((points-np.array([x[0],y[0]]))/np.array([4/len(x),4/len(y)]),np.array([len(x),len(y)]))
        ij=np.floor(u).astype(int);f=u-ij;i,j=ij[...,0],ij[...,1];a,b=f[...,0,None],f[...,1,None]
        return (1-a)*(1-b)*fields[i,j]+a*(1-b)*fields[(i+1)%len(x),j]+(1-a)*b*fields[i,(j+1)%len(y)]+a*b*fields[(i+1)%len(x),(j+1)%len(y)]
    return evaluate,{'x_first':float(x[0]),'y_first':float(y[0]),'shape':list(fields.shape),
                    'mapping':'periodic bilinear of stored coordinates, raw E/H common phase; moments then shared topology'}


def assemble_local_forms(data,k):
    ids,sign,nd=topology(data);nt=len(ids);bary,w=quadrature(3)
    forms=[np.empty((nt,28,28),complex) for _ in range(3)]
    for start in range(0,nt,64):
        stop=min(nt,start+64);U,N,det=local_basis(data,start,stop,bary,k)
        U*=sign[start:stop,None,None,:];N*=sign[start:stop,None,None,:]
        material=np.concatenate((data['epsilon'][start:stop],np.ones((stop-start,3))),axis=1)
        weight=det[:,None]*w
        forms[0][start:stop]=np.einsum('bqci,bqcj,bqc->bij',U.conj(),U,weight[:,:,None]*material[:,None,:],optimize=True)
        forms[1][start:stop]=np.einsum('bqci,bqcj,bq->bij',U.conj(),N,weight,optimize=True)
        forms[2][start:stop]=np.einsum('bqci,bqcj,bqc->bij',N.conj(),N,weight[:,:,None]/material[:,None,:],optimize=True)
    return ids,forms


def apply_local(matrix,ids,x):
    v=np.einsum('bij,bj->bi',matrix,x[ids],optimize=False)
    return np.bincount(ids.ravel(),weights=v.real.ravel(),minlength=len(x))+1j*np.bincount(ids.ravel(),weights=v.imag.ravel(),minlength=len(x))


def minimize(data,k,anchor,*,max_outer=3,max_iterations=600,seconds=760,logger=None):
    start=time.monotonic();ids,(M,N,G)=assemble_local_forms(data,k)
    norm=np.vdot(anchor,apply_local(M,ids,anchor)).real
    if not np.isfinite(norm) or norm<=0:raise ValueError('NONZERO_FINITE_ANCHOR_REQUIRED')
    anchor=anchor/np.sqrt(norm)
    b=apply_local(M,ids,anchor);x=anchor.copy();history=[]
    class TimeLimit(Exception):pass
    for outer in range(max_outer):
        mass=np.vdot(x,apply_local(M,ids,x)).real
        rho=(np.vdot(x,apply_local(N,ids,x))/mass).real
        K=G-rho*(N+N.conj().transpose(0,2,1))+rho*rho*M
        diag=np.bincount(ids.ravel(),weights=np.diagonal(K,axis1=1,axis2=2).real.ravel(),minlength=len(x))
        if np.min(diag)<=0:raise ValueError('NONPOSITIVE_NORMAL_DIAGONAL')
        scale=1/np.sqrt(diag);bt=scale*b;bt2=np.vdot(bt,bt).real
        def project(z):return z-bt*(np.vdot(bt,z)/bt2)
        def matvec(z):
            return project(scale*apply_local(K,ids,scale*project(z)))+bt*(np.vdot(bt,z)/bt2)
        x=x/np.vdot(b,x);y0=x/scale
        rhs=-project(scale*apply_local(K,ids,x));last=[np.zeros_like(x)];iterations=[0]
        outer_start=time.monotonic()
        def callback(y):
            last[0]=y.copy();iterations[0]+=1
            if iterations[0]%100==0 and logger:logger({'outer':outer+1,'iteration':iterations[0],'seconds':time.monotonic()-start})
            if time.monotonic()-start>seconds:raise TimeLimit()
        stopped=False
        try:
            y,info=cg(LinearOperator((len(x),len(x)),matvec=matvec,dtype=complex),rhs,
                      rtol=1e-9,atol=0,maxiter=max_iterations,callback=callback)
        except TimeLimit:
            y,info=last[0],max_iterations;stopped=True
        x=scale*(y0+project(y));x=x/np.vdot(b,x)
        mass=np.vdot(x,apply_local(M,ids,x)).real
        rayleigh=np.vdot(x,apply_local(N,ids,x))/mass
        normal=np.vdot(x,apply_local(K,ids,x)).real/mass
        history.append({'outer':outer+1,'shift':float(rho),'updated_rayleigh':float(rayleigh.real),
                        'rayleigh_imaginary':float(rayleigh.imag),'iterations':iterations[0],'cg_info':int(info),
                        'seconds':time.monotonic()-outer_start,'optimization_objective_at_shift':float(normal),
                        'anchor_overlap_error':float(abs(np.vdot(b,x)-1)), 'time_stop':stopped})
        if logger:logger(history[-1])
        del K
        if stopped:break
    x/=np.sqrt(np.vdot(x,apply_local(M,ids,x)).real)
    return x,history,anchor


def calibrate(data,model):
    """No spectral solve. Check actual topology, traces, fitted interfaces."""
    ids,sign,nd=topology(data);nt=len(ids);ne=len(data['global_edge_nodes'])
    if np.any(np.bincount(data['edge_ids'].ravel())!=2):raise ValueError('PERIODIC_EDGE_INCIDENCE')
    if np.any(np.bincount(data['edge_ids'].ravel(),weights=data['edge_signs'].ravel())!=0):
        raise ValueError('EDGE_ORIENTATION')
    v=data['vertices'][data['triangles']]
    req=model['task']['requirements'];a=F(req['film_thickness_um'])/2;w=F(req['ridge_width_um'])/2
    split=-a+F(req['slab_thickness_um'])
    for axis,interfaces in ((0,[-w,w]),(1,[-a,split,a])):
        for cut in interfaces:
            c=float(cut)
            if F(c)!=cut or np.any((v[:,:,axis].min(axis=1)<c)&(v[:,:,axis].max(axis=1)>c)):
                raise ValueError('MATERIAL_INTERFACE_NOT_FITTED')
    rng=np.random.default_rng(20261010);x=rng.standard_normal(nd)+1j*rng.standard_normal(nd)
    errors=[]
    # Evaluate every oriented edge from its two incident cells. Translate the
    # coordinate representative at the periodic seam; tangent vectors coincide.
    trace=np.empty((nt,3,3,4),complex)
    for edge,(i,j) in enumerate(EDGES):
        ts=np.array([.25,.5,.75]);bary=np.zeros((3,3));bary[:,i]=1-ts;bary[:,j]=ts
        for start in range(0,nt,128):
            stop=min(nt,start+128);U,_,_=local_basis(data,start,stop,bary,0)
            u=np.einsum('bqci,bi->bqc',U,x[ids[start:stop]]*sign[start:stop])
            vector=v[start:stop,j]-v[start:stop,i]
            signed=vector*data['edge_signs'][start:stop,edge,None]
            values=np.stack((np.einsum('bqc,bc->bq',u[:,:,:2],signed),u[:,:,2],
                             np.einsum('bqc,bc->bq',u[:,:,3:5],signed),u[:,:,5]),axis=-1)
            reverse=data['edge_signs'][start:stop,edge]<0
            values[reverse]=values[reverse,::-1]
            trace[start:stop,edge]=values
    order=np.argsort(data['edge_ids'].ravel(),kind='stable').reshape(ne,2)
    values=trace.reshape(-1,3,4)[order]
    defect=float(np.max(abs(values[:,0]-values[:,1])))
    if defect>1e-9:raise ValueError('SHARED_TANGENTIAL_OR_LONGITUDINAL_TRACE')
    return {'status':'PASS','triangles':nt,'complex_dofs':nd,'global_edges':ne,
            'periodic_vertices':int(data['periodic_node_ids'].max())+1,
            'moments_per_edge_per_transverse_field':2,'cell_moments_per_transverse_field':2,
            'polynomial_family':'Nedelec first kind k=1 (superdegree 2) / longitudinal P2',
            'trace_max_float_defect':defect,'exact_shared_trace_basis':'integer reference dual; common even/odd moment orientation; covariant Piola',
            'material_interfaces_fitted':True,'physical_eigensolves':0}


def diagnose(data,k,x,model):
    """One independent 4x4 Duffy integration of the final continuous residual.

    Region masks are diagnostic only. Certification must split region cuts
    exactly and use outward arithmetic in a separate strict-integration stage.
    """
    ids,sign,nd=topology(data);bary,w=quadrature(4);tot=np.zeros(8);samples=[]
    for start in range(0,len(ids),128):
        stop=min(len(ids),start+128);U,N,det=local_basis(data,start,stop,bary,k)
        coeff=x[ids[start:stop]]*sign[start:stop]
        u=np.einsum('bqci,bi->bqc',U,coeff);nu=np.einsum('bqci,bi->bqc',N,coeff)
        m=np.concatenate((data['epsilon'][start:stop],np.ones((stop-start,3))),axis=1);weight=det[:,None]*w
        pts=np.einsum('qi,bic->bqc',bary,data['vertices'][data['triangles'][start:stop]])
        req=model['task']['requirements'];core=(abs(pts[:,:,0])<=req['ridge_width_um']/2)&(abs(pts[:,:,1])<=req['film_thickness_um']/2)
        outer=(abs(pts[:,:,0])>1.8)|(abs(pts[:,:,1])>1.8)
        electric=np.sum(abs(u[:,:,:3])**2*m[:,None,:3],axis=2)
        tot+=np.array([np.sum(weight*np.sum(abs(u)**2*m[:,None,:],axis=2)),
          np.sum(weight*np.sum(u.conj()*nu,axis=2).real),np.sum(weight*np.sum(abs(nu)**2/m[:,None,:],axis=2)),
          np.sum(weight*electric),np.sum(weight*abs(u[:,:,0])**2),np.sum(weight*np.sum(abs(u[:,:,:3])**2,axis=2)),
          np.sum(weight*electric*core),np.sum(weight*electric*outer)])
        # Quadratic scalar sums per cell permit a cancellation-resistant second
        # algebraic reduction at the final Rayleigh shift, without reintegration.
        samples.append((u,nu,m,weight))
    mass,n,graph,electric,ex,l2,core,outer=tot;rho=n/mass
    residual2=sum(float(np.sum(weight*np.sum(abs(nu-rho*m[:,None,:]*u)**2/m[:,None,:],axis=2))) for u,nu,m,weight in samples)/mass
    g=min(rho-1.277,1/.775-rho,abs(rho));r=np.sqrt(residual2)
    return {'status':'FLOATING_CONTINUOUS_FIELD_DIAGNOSTIC_ONLY','mass':float(mass),'rayleigh':float(rho),
            'residual':float(r),'gap_diagnostic':float(g),'r_over_g':float(r/g) if g>0 else None,
            'electric_norm':float(np.sqrt(electric/mass)),'Ex_fraction':float(ex/l2),
            'core_fraction':float(core/electric),'outer_fraction':float(outer/electric),'mean_epsilon':float(electric/l2),
            'quadrature':'independent 4x4 Duffy, exact degree coverage but floating arithmetic',
            'selector_masks':'floating quadrature point masks, NOT strict split-region bounds',
            'field_error_certified':False}
