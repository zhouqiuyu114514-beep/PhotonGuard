"""Cell-interior elimination for a constrained floating residual proposal.

Only bounded 14x14 cell solves are factored; global shared traces use CG.
Full continuous residual integration remains the independent acceptance test.
"""
import time
import numpy as np
from scipy.sparse.linalg import LinearOperator,cg
from .higher_order_trace import apply_real


INTERIOR=np.array([9,10,11,12,13,14,24,34,35,36,37,38,39,49])


def condense(K,ids,b,interior=INTERIOR):
    width=ids.shape[1];trace=np.array([i for i in range(width) if i not in set(interior)])
    interior_ids=ids[:,interior]
    if len(np.unique(interior_ids))!=interior_ids.size:raise ValueError('CELL_INTERIORS_MUST_NOT_BE_SHARED')
    trace_global=np.unique(ids[:,trace]);mapping=np.full(len(b),-1,int);mapping[trace_global]=np.arange(len(trace_global))
    trace_ids=mapping[ids[:,trace]]
    if np.any(np.isin(interior_ids,trace_global)):raise ValueError('INTERIOR_TRACE_OVERLAP')
    nt=len(ids);S=np.empty((nt,len(trace),len(trace)));W=np.empty((nt,len(interior),len(trace)));v=np.empty((nt,len(interior)))
    rhs=b[trace_global].copy();local_rhs=np.empty((nt,len(trace)));beta=0.;min_cholesky=float('inf');asymmetry=0.
    for start in range(0,nt,256):
        stop=min(nt,start+256);block=K[start:stop]
        ii=block[:,interior][:,:,interior];it=block[:,interior][:,:,trace];tt=block[:,trace][:,:,trace]
        bi=b[interior_ids[start:stop]]
        chol=np.linalg.cholesky(ii);min_cholesky=min(min_cholesky,float(np.diagonal(chol,axis1=1,axis2=2).min()))
        solution=np.linalg.solve(ii,np.concatenate((it,bi[:,:,None]),axis=2))
        W[start:stop]=solution[:,:,:-1];v[start:stop]=solution[:,:,-1]
        schur=tt-it.transpose(0,2,1)@solution[:,:,:-1]
        asymmetry=max(asymmetry,float(np.max(abs(schur-schur.transpose(0,2,1)))))
        S[start:stop]=(schur+schur.transpose(0,2,1))/2
        local_rhs[start:stop]=np.einsum('bit,bi->bt',it,solution[:,:,-1])
        beta+=float(np.sum(bi*solution[:,:,-1]))
    rhs-=np.bincount(trace_ids.ravel(),weights=local_rhs.ravel(),minlength=len(rhs))
    return {'S':S,'W':W,'v':v,'rhs':rhs,'beta':beta,'trace_ids':trace_ids,
            'trace_global':trace_global,'interior_ids':interior_ids,
            'minimum_cell_cholesky_diagonal':min_cholesky,'schur_symmetry_roundoff':asymmetry}


def reconstruct(condensed,y,dimension):
    denominator=np.dot(condensed['rhs'],y)+condensed['beta']
    if not np.isfinite(denominator) or denominator<=0:raise ValueError('POSITIVE_ANCHOR_DENOMINATOR_REQUIRED')
    alpha=1/denominator;x=np.zeros(dimension);x[condensed['trace_global']]=alpha*y
    x[condensed['interior_ids']]=alpha*condensed['v']-np.einsum('bit,bt->bi',condensed['W'],x[condensed['trace_global']][condensed['trace_ids']])
    return x,alpha


def solve(ids,forms,anchor,initial,*,iterations=10000,outer_limit=3,seconds=760,logger=None):
    M,N,G=forms;start=time.monotonic();anchor=anchor/np.sqrt(np.dot(anchor,apply_real(M,ids,anchor)))
    b=apply_real(M,ids,anchor);x=initial.copy();history=[];checkpoints=[]
    class TimeCap(Exception):pass
    for outer in range(outer_limit):
        mass=np.dot(x,apply_real(M,ids,x));rho=float(np.dot(x,apply_real(N,ids,x))/mass)
        K=G-rho*(N+N.transpose(0,2,1))+rho*rho*M
        c=condense(K,ids,b);S=c['S'];ti=c['trace_ids'];rhs=c['rhs'];nt=len(rhs)
        diagonal=np.bincount(ti.ravel(),weights=np.diagonal(S,axis1=1,axis2=2).ravel(),minlength=nt)
        if np.any(diagonal<=0):raise ValueError('NONPOSITIVE_SCHUR_DIAGONAL')
        scale=1/np.sqrt(diagonal)
        def multiply(z):return scale*apply_real(S,ti,scale*z)
        scaled_rhs=scale*rhs;rhs_norm=np.linalg.norm(scaled_rhs)
        x=x/np.dot(b,x);alpha0=float(np.dot(x,apply_real(K,ids,x)))
        if alpha0<=0:raise ValueError('INITIAL_OBJECTIVE_NOT_POSITIVE')
        z0=x[c['trace_global']]/alpha0/scale
        last=[z0.copy()];nit=[0];outer_start=time.monotonic()
        def checkpoint(z):
            r=scaled_rhs-multiply(z)
            row={'outer':outer+1,'iteration':nit[0],'seconds':time.monotonic()-start,
                 'true_scaled_schur_residual':float(np.linalg.norm(r)),
                 'true_schur_relative_residual':float(np.linalg.norm(r)/max(rhs_norm,1e-300))}
            checkpoints.append(row)
            if logger:logger(row)
        def callback(z):
            nit[0]+=1;last[0]=z.copy()
            if nit[0]%500==0:checkpoint(z)
            if time.monotonic()-start>seconds:raise TimeCap()
        cap=False
        try:z,info=cg(LinearOperator((nt,nt),matvec=multiply,dtype=float),scaled_rhs,x0=z0,rtol=1e-9,atol=1e-14,maxiter=iterations,callback=callback)
        except TimeCap:z=last[0];info=iterations;cap=True
        checkpoint(z);x,alpha=reconstruct(c,scale*z,len(b));raw_overlap=float(np.dot(b,x));x/=raw_overlap
        kx=apply_real(K,ids,x);diag=np.bincount(ids.ravel(),weights=np.diagonal(K,axis1=1,axis2=2).ravel(),minlength=len(x))
        bs=b/np.sqrt(diag);gradient=kx/np.sqrt(diag);gradient-=bs*(np.dot(bs,gradient)/np.dot(bs,bs))
        mass=np.dot(x,apply_real(M,ids,x));newrho=float(np.dot(x,apply_real(N,ids,x))/mass)
        objective=float(np.dot(x,kx)/mass);r2=objective-(rho-newrho)**2
        row={'outer':outer+1,'shift':rho,'rayleigh':newrho,'iterations':nit[0],'cg_info':int(info),
             'seconds':time.monotonic()-outer_start,'time_cap':cap,'true_KKT_norm':float(np.linalg.norm(gradient)),
             'true_linear_relative_residual':checkpoints[-1]['true_schur_relative_residual'],
             'algebraic_residual_estimate':float(np.sqrt(max(0,r2))),
             'overlap_error_before_normalization':abs(raw_overlap-1),'overlap_error':float(abs(np.dot(b,x)-1)),
             'local_factored_dimension':len(INTERIOR),'global_trace_dofs':nt,
             'minimum_cell_cholesky_diagonal':c['minimum_cell_cholesky_diagonal'],
             'schur_symmetry_roundoff':c['schur_symmetry_roundoff']}
        history.append(row)
        if logger:logger(row)
        del c,S,K
        if cap or (info==0 and abs(newrho-rho)<1e-10):break
    x/=np.sqrt(np.dot(x,apply_real(M,ids,x)))
    return x,history,checkpoints
