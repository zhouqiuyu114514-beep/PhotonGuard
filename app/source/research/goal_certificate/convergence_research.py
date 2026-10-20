"""Bounded continuation with true KKT residuals and one final localization.

Floating research only. Never promotes finite-space convergence into a
continuous field/error certificate. Old proposal windows remain untouched.
"""
import time
import numpy as np
from scipy.sparse.linalg import LinearOperator,cg
from .shared_trace_proposal import apply_local,topology,quadrature,local_basis


def solve_forms(ids,forms,anchor,initial,*,iterations=6000,outer_limit=3,
                seconds=780,logger=None,apply_fn=apply_local):
    start=time.monotonic();M,N,G=forms
    anchor=anchor/np.sqrt(np.vdot(anchor,apply_fn(M,ids,anchor)).real)
    b=apply_fn(M,ids,anchor);x=initial.copy();history=[];checkpoints=[]
    if not np.isfinite(x).all() or abs(np.vdot(b,x))<1e-12:
        raise ValueError('ANCHOR_OVERLAP_REQUIRED')
    class TimeCap(Exception):pass
    for outer in range(outer_limit):
        mass=np.vdot(x,apply_fn(M,ids,x)).real
        rho=float((np.vdot(x,apply_fn(N,ids,x))/mass).real)
        K=G-rho*(N+N.conj().transpose(0,2,1))+rho*rho*M
        diag=np.bincount(ids.ravel(),weights=np.diagonal(K,axis1=1,axis2=2).real.ravel(),minlength=len(x))
        if min(diag)<=0:raise ValueError('POSITIVE_NORMAL_DIAGONAL_REQUIRED')
        scale=1/np.sqrt(diag);bt=scale*b;bt2=np.vdot(bt,bt).real
        def project(z):return z-bt*(np.vdot(bt,z)/bt2)
        def multiply(z):return project(scale*apply_fn(K,ids,scale*project(z)))+bt*(np.vdot(bt,z)/bt2)
        x=x/np.vdot(b,x);y0=x/scale
        rhs=-project(scale*apply_fn(K,ids,x));rhsnorm=np.linalg.norm(rhs)
        last=[np.zeros_like(x)];nit=[0];outer_start=time.monotonic()
        def checkpoint(y):
            xx=scale*(y0+project(y));kx=apply_fn(K,ids,xx)
            grad=project(scale*kx);m=np.vdot(xx,apply_fn(M,ids,xx)).real
            item={'outer':outer+1,'iteration':nit[0],'seconds':time.monotonic()-start,
                'true_scaled_KKT_norm':float(np.linalg.norm(grad)),
                'true_linear_relative_residual':float(np.linalg.norm(rhs-multiply(y))/max(rhsnorm,1e-300)),
                'objective_at_fixed_shift':float(np.vdot(xx,kx).real/m),
                'overlap_error':float(abs(np.vdot(b,xx)-1))}
            checkpoints.append(item)
            if logger:logger(item)
        def callback(y):
            nit[0]+=1;last[0]=y.copy()
            if nit[0]%500==0:checkpoint(y)
            if time.monotonic()-start>seconds:raise TimeCap()
        cap=False
        try:
            y,info=cg(LinearOperator((len(x),len(x)),matvec=multiply,dtype=x.dtype),rhs,
                      rtol=1e-8,atol=1e-14,maxiter=iterations,callback=callback)
        except TimeCap:y=last[0];info=iterations;cap=True
        checkpoint(y);x=scale*(y0+project(y));x=x/np.vdot(b,x)
        mass=np.vdot(x,apply_fn(M,ids,x)).real
        newrho=np.vdot(x,apply_fn(N,ids,x))/mass
        objective=np.vdot(x,apply_fn(K,ids,x)).real/mass
        residual2=objective-(rho-newrho.real)**2
        item={'outer':outer+1,'shift':rho,'rayleigh':float(newrho.real),'iterations':nit[0],
            'cg_info':int(info),'seconds':time.monotonic()-outer_start,'time_cap':cap,
            'true_KKT_norm':checkpoints[-1]['true_scaled_KKT_norm'],
            'true_linear_relative_residual':checkpoints[-1]['true_linear_relative_residual'],
            'algebraic_residual_estimate':float(np.sqrt(max(0,residual2))),
            'rayleigh_imaginary':float(newrho.imag),'overlap_error':float(abs(np.vdot(b,x)-1))}
        history.append(item)
        if logger:logger(item)
        del K
        if cap:break
        if info==0 and abs(newrho.real-rho)<1e-10:break
    x/=np.sqrt(np.vdot(x,apply_fn(M,ids,x)).real)
    return x,history,checkpoints


def diagnostic_map(data,k,coeff,model,rho,*,basis=local_basis,topology_fn=topology,order=4):
    """Single independent continuous integration, per-cell residual map saved.

    The reported localization uses floating barycentric coordinates and region
    classification. It is not outward integration or a certified region bound.
    """
    ids,sign,nd=topology_fn(data);bary,w=quadrature(order);tot=np.zeros(8)
    residual_cells=np.zeros((len(ids),6));mass_cells=np.zeros(len(ids))
    for start in range(0,len(ids),128):
        stop=min(start+128,len(ids));U,N,det=basis(data,start,stop,bary,k)
        x=coeff[ids[start:stop]]*sign[start:stop]
        u=np.einsum('bqci,bi->bqc',U,x);nu=np.einsum('bqci,bi->bqc',N,x)
        m=np.concatenate((data['epsilon'][start:stop],np.ones((stop-start,3))),axis=1)
        weight=det[:,None]*w;u2=abs(u)**2;electric=np.sum(u2[:,:,:3]*m[:,None,:3],axis=2)
        pts=np.einsum('qi,bic->bqc',bary,data['vertices'][data['triangles'][start:stop]])
        req=model['task']['requirements'];core=(abs(pts[:,:,0])<=req['ridge_width_um']/2)&(abs(pts[:,:,1])<=req['film_thickness_um']/2)
        outer=(abs(pts[:,:,0])>1.8)|(abs(pts[:,:,1])>1.8)
        mass_cells[start:stop]=np.sum(weight*np.sum(u2*m[:,None,:],axis=2),axis=1)
        tot+=np.array([mass_cells[start:stop].sum(),np.sum(weight*np.sum(u.conj()*nu,axis=2).real),
            np.sum(weight*np.sum(abs(nu)**2/m[:,None,:],axis=2)),np.sum(weight*electric),
            np.sum(weight*u2[:,:,0]),np.sum(weight*np.sum(u2[:,:,:3],axis=2)),
            np.sum(weight*electric*core),np.sum(weight*electric*outer)])
        residual_cells[start:stop]=np.sum(weight[:,:,None]*abs(nu-rho*m[:,None,:]*u)**2/m[:,None,:],axis=1)
    mass,n,graph,electric,ex,l2,core,outer=tot;rayleigh=n/mass
    # Exact identity for real shifts, evaluated here only in floating arithmetic.
    r2=residual_cells.sum()/mass-(rho-rayleigh)**2
    if r2<0:raise ValueError('NEGATIVE_DIAGNOSTIC_RESIDUAL')
    residual=np.sqrt(r2);gap=min(rayleigh-1.277,1/.775-rayleigh,abs(rayleigh))
    centers=data['vertices'][data['triangles']].mean(axis=1);req=model['task']['requirements']
    shoulder_y=[-req['film_thickness_um']/2+req['slab_thickness_um'],req['film_thickness_um']/2]
    corners=np.array([(x,y) for x in [-req['ridge_width_um']/2,req['ridge_width_um']/2] for y in shoulder_y])
    distance=np.min(np.max(abs(centers[:,None,:]-corners[None,:,:]),axis=2),axis=1)
    weights=residual_cells.sum(axis=1)
    localization={str(radius):float(weights[distance<=radius].sum()/weights.sum()) for radius in [.025,.05,.1,.2]}
    return {'status':'FLOATING_CONTINUOUS_RESIDUAL_ONLY','mass':float(mass),'rayleigh':float(rayleigh),
        'independent_rayleigh_shift_difference':float(rayleigh-rho),'residual':float(residual),
        'gap_diagnostic':float(gap),'r_over_g':float(residual/gap) if gap>0 else None,
        'electric_norm':float(np.sqrt(electric/mass)),'Ex_fraction':float(ex/l2),
        'core_fraction':float(core/electric),'outer_fraction':float(outer/electric),'mean_epsilon':float(electric/l2),
        'corner_Linf_radius_residual_squared_fraction':localization,
        'component_residual_squared_fraction':(residual_cells.sum(axis=0)/residual_cells.sum()).tolist(),
        'field_error_certified':False,'selector_regions_certified':False,
        'quadrature_order_per_duffy_axis':order},residual_cells,mass_cells
