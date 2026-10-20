"""One conforming, cell-bubble least-residual correction; floating preflight.

The cubic bubble lambda0*lambda1*lambda2 vanishes on every edge. Adding it
preserves tangential/longitudinal shared traces and permits normal jumps.
No spectral projector, field-error bound or physical eigenpair is certified.
"""
import numpy as np
from .conforming_trials import EDGES,audit

def quadrature():
    x,w=np.polynomial.legendre.leggauss(4);x=(x+1)/2;w=w/2
    u,v=np.meshgrid(x,x,indexing='ij');wu,wv=np.meshgrid(w,w,indexing='ij');u=u.ravel();v=v.ravel()
    return np.stack([(1-u)*(1-v),u,(1-u)*v],axis=1),(wu*wv).ravel()*(1-u)

def local(data,start,stop,bary,k):
    ti=data['triangles'][start:stop];v=data['vertices'][ti]
    det=(v[:,1,0]-v[:,0,0])*(v[:,2,1]-v[:,0,1])-(v[:,1,1]-v[:,0,1])*(v[:,2,0]-v[:,0,0])
    if np.any(det<=0):raise ValueError('TRIANGLE_ORIENTATION')
    grad=np.stack([np.stack([v[:,j,1]-v[:,l,1],v[:,l,0]-v[:,j,0]],axis=1)/det[:,None] for i,j,l in ((0,1,2),(1,2,0),(2,0,1))],axis=1)
    edge=data['edge_dofs'][data['edge_ids'][start:stop],:,:1][...,0]*data['edge_signs'][start:stop,:,None]
    node=data['node_z_dofs'][data['periodic_node_ids'][ti],:,:1][...,0]
    values=np.zeros((len(ti),3,6),complex);d=[]
    for kind in (0,1):
        for component in (0,1):
            for l in range(3):
                for e,(i,j) in enumerate(EDGES):values[:,l,3*kind+component]+=edge[:,e,kind]*((l==i)*grad[:,j,component]-(l==j)*grad[:,i,component])
        values[:,:,3*kind+2]=node[:,:,kind]
        dz=np.einsum('bi,bic->bc',node[:,:,kind],grad)
        cz=sum(2*edge[:,e,kind]*(grad[:,i,0]*grad[:,j,1]-grad[:,i,1]*grad[:,j,0]) for e,(i,j) in enumerate(EDGES))
        d.append((dz[:,0],dz[:,1],cz))
    U=np.einsum('qi,bic->bqc',bary,values);N=np.zeros_like(U);t=1/(2*np.pi)
    N[:,:,0]=1j*d[1][1][:,None]*t+k*U[:,:,4];N[:,:,1]=-k*U[:,:,3]-1j*d[1][0][:,None]*t;N[:,:,2]=1j*d[1][2][:,None]*t
    N[:,:,3]=-1j*d[0][1][:,None]*t-k*U[:,:,1];N[:,:,4]=k*U[:,:,0]+1j*d[0][0][:,None]*t;N[:,:,5]=-1j*d[0][2][:,None]*t
    phi=np.prod(bary,axis=1);dphi=sum(np.prod(bary[:,[j for j in range(3) if j!=i]],axis=1)[None,:,None]*grad[:,i,None,:] for i in range(3))
    basis=np.zeros((len(ti),len(bary),6,6),complex)
    basis[:,:,0,4]=k*phi;basis[:,:,1,3]=-k*phi;basis[:,:,3,1]=-k*phi;basis[:,:,4,0]=k*phi
    basis[:,:,0,5]=1j*dphi[:,:,1]*t;basis[:,:,1,5]=-1j*dphi[:,:,0]*t
    basis[:,:,2,3]=-1j*dphi[:,:,1]*t;basis[:,:,2,4]=1j*dphi[:,:,0]*t
    basis[:,:,3,2]=-1j*dphi[:,:,1]*t;basis[:,:,4,2]=1j*dphi[:,:,0]*t
    basis[:,:,5,0]=1j*dphi[:,:,1]*t;basis[:,:,5,1]=-1j*dphi[:,:,0]*t
    return U,N,basis,phi,det,v.mean(axis=1)

def compare(data,k,rho):
    trace=audit(data);bary,weights=quadrature();total=len(data['triangles']);coefficients=np.zeros((total,6),complex)
    sums=[np.zeros(8,float),np.zeros(8,float)];max_normal_condition=0.
    def accumulate(acc,U,N,m,w,core,outer):
        u2=np.abs(U)**2;electric=np.sum(u2[:,:,:3]*m[:,None,:3],axis=2)
        acc[0]+=np.sum(w*np.sum(u2*m[:,None,:],axis=2));acc[1]+=np.sum(w*np.sum(np.conj(U)*N,axis=2).real)
        acc[2]+=np.sum(w*np.sum(abs(N)**2/m[:,None,:],axis=2));acc[3]+=np.sum(w*electric)
        acc[4]+=np.sum(w*u2[:,:,0]);acc[5]+=np.sum(w*np.sum(u2[:,:,:3],axis=2))
        acc[6]+=np.sum(w*electric*core[:,None]);acc[7]+=np.sum(w*electric*outer[:,None])
    for start in range(0,total,512):
        stop=min(total,start+512);U,N,basis,phi,det,center=local(data,start,stop,bary,k)
        m=np.concatenate([data['epsilon'][start:stop],np.ones((stop-start,3))],axis=1);w=det[:,None]*weights
        req=data['selector_geometry'];core=(abs(center[:,0])<=req['width']/2)&(abs(center[:,1])<=req['film']/2)
        outer=(abs(center[:,0])>1.8)|(abs(center[:,1])>1.8)
        residual=N-rho*m[:,None,:]*U
        B=basis.copy();di=np.arange(6);B[:,:,di,di]-=rho*m[:,None,:]*phi[None,:,None]
        gram=np.einsum('bqci,bqcj,bqc->bij',np.conj(B),B,w[:,:,None]/m[:,None,:],optimize=True)
        rhs=-np.einsum('bqci,bqc,bqc->bi',np.conj(B),residual,w[:,:,None]/m[:,None,:],optimize=True)
        correction=np.linalg.solve(gram,rhs[...,None])[...,0]
        if not np.isfinite(correction).all():raise ValueError('NONFINITE_LOCAL_CORRECTION')
        coefficients[start:stop]=correction
        V=U+phi[None,:,None]*correction[:,None,:];NV=N+np.einsum('bqci,bi->bqc',basis,correction)
        accumulate(sums[0],U,N,m,w,core,outer);accumulate(sums[1],V,NV,m,w,core,outer)
    rows=[]
    for name,values in zip(('old-low-order','one-cubic-bubble-correction'),sums):
        mass,normN,graph,electric,ex,l2,core,outer=values;ritz=normN/mass
        rows.append({'proposal':name,'combined_mass':mass,'electric_mass':electric,'rayleigh_frequency':ritz,
            'continuous_graph_residual_float':float(np.sqrt(max(0,graph/mass-ritz*ritz))),
            'residual_at_fixed_rho_float':float(np.sqrt(max(0,(graph-2*rho*normN+rho*rho*mass)/mass))),
            'unweighted_Ex_fraction':ex/l2,'core_energy_fraction':core/electric,'outer_energy_fraction':outer/electric,'mean_epsilon':electric/l2})
    return {'status':'PROJECTOR_CERTIFICATE_INCOMPLETE','rows':rows,'trace':trace,'enrichment_trace':'Cubic cell bubbles vanish identically on every edge; original periodic oriented DOFs preserved',
        'quadrature':'4x4 Duffy Gauss integrates degree-6 polynomial integrands algebraically; floating nodes/weights/geometry, not interval integration',
        'mask_scope':'Cell-centre floating classification for aligned masks; not certified region integrals',
        'small_local_normal_systems':total,'local_system_dimension':6,'proposals':2,'matrix_integral_passes':3,
        'rank_one_projection_certified':False,'field_error_certified':False,'new_physical_eigensolves_MPB_Meep_API':0},coefficients
