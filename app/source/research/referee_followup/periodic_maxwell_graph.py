"""Independent periodic first-order Maxwell graph-form preflight, FLOATING ONLY.

The E and h trial fields are smooth periodic Fourier vector polynomials in
H(curl), so the continuous graph norm is integrated using piecewise epsilon^-1.
This is not N inv(compressed M) N. Cycles/um units divide N and kappa by 2*pi.
No MPB/Yee imports, pixel tensors, numerical quadrature, or certificate claim.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import numpy as np
from scipy import sparse
from scipy.linalg import eigh, eigvalsh
import json,sys,time,resource
from pathlib import Path

def rectangle(g,left,right):
    return (right-left)/4*np.sinc(g*(right-left)/4)*np.exp(-2j*np.pi*g*(left+right)/8)

def ln_epsilon(w):
    t=w*w
    no=1+2.6734*t/(t-.01764)+1.229*t/(t-.05914)+12.614*t/(t-474.6)
    ne=1+2.9804*t/(t-.02047)+.5981*t/(t-.0666)+8.9543*t/(t-416.08)
    return np.array([ne,no,no])

def coefficients(dg,w,inverse=False,uniform=None):
    dx,dy=dg[...,0],dg[...,1];z=(dx==0)&(dy==0)
    if uniform is not None:
        e=np.asarray(uniform);return z[...,None]*(1/e if inverse else e)
    core=ln_epsilon(w);sub=np.full(3,1.44**2)
    if inverse:core=1/core;sub=1/sub
    bottom=(dx==0)*rectangle(dy,-2,-.3)
    slab=(dx==0)*rectangle(dy,-.3,0)
    cap=rectangle(dx,-.7,.7)*rectangle(dy,0,.3)
    return z[...,None]+(sub-1)*bottom[...,None]+(core-1)*(slab+cap)[...,None]

def matrices(w,k,M,uniform=None):
    g=np.array([(i,j) for i in range(-M,M+1) for j in range(-M,M+1)])
    q=np.column_stack([g/4,np.full(len(g),k)])
    blocks=[np.array([[0,-z,y],[z,0,-x],[-y,x,0]]) for x,y,z in q]
    cross=sparse.block_diag(blocks,format='csr')
    zero=sparse.csr_matrix(cross.shape)
    N=sparse.bmat([[zero,-cross],[cross,zero]],format='csr')
    dg=g[:,None,:]-g[None,:,:];dim=3*len(g)
    ec=coefficients(dg,w,False,uniform);ic=coefficients(dg,w,True,uniform)
    mass=np.eye(2*dim,dtype=complex);inverse_coefficient=np.eye(2*dim,dtype=complex)
    for c in range(3):mass[c:dim:3,c:dim:3]=ec[...,c];inverse_coefficient[c:dim:3,c:dim:3]=ic[...,c]
    # N is exactly real symmetric; (N W N)^T = N W^T N.
    graph=(N@(N@inverse_coefficient).T).T
    return g,N.toarray(),mass,graph,ec,ic

def run(job,folder):
    start=time.monotonic();w,k,M=job['wave'],job['neff']/job['wave'],job['M']
    uniform=job.get('uniform');g,N,mass,graph,ec,ic=matrices(w,k,M,uniform)
    n=len(N);target=1/w;rows=[]
    # Audit graph integral against the projected substitute on a deterministic
    # trial vector. Difference is generally positive for discontinuous epsilon.
    v=np.random.default_rng(20261008).normal(size=n)+1j*np.random.default_rng(18).normal(size=n)
    from scipy.linalg import solve
    projected=float(np.vdot(N@v,solve(mass,N@v,assume_a='pos')).real)
    continuous=float(np.vdot(v,graph@v).real)
    assert continuous-projected>=-1e-8*max(continuous,1)
    for tau in job['shifts']:
        B=N-tau*mass;Q=graph-2*tau*N+tau*tau*mass
        herm=max(np.linalg.norm(B-B.conj().T),np.linalg.norm(Q-Q.conj().T))
        assert herm<1e-9*max(np.linalg.norm(Q),1)
        vals,vec=eigh(B,Q,check_finite=True,driver='gvd')
        negative=np.flatnonzero(vals< -1e-12)[:4]
        positive=np.flatnonzero(vals>1e-12)[-4:][::-1]
        selected=np.concatenate([negative,positive])
        transformed=tau+1/vals[selected]
        algebraic=[float(np.linalg.norm(B@vec[:,j]-vals[j]*(Q@vec[:,j]))/(np.linalg.norm(B@vec[:,j])+abs(vals[j])*np.linalg.norm(Q@vec[:,j]))) for j in selected]
        rows.append({'shift_cycles_per_um':tau,'mu':vals[selected].tolist(),
          'below_shift_float_candidates':transformed[:len(negative)].tolist(),
          'above_shift_float_candidates':transformed[len(negative):].tolist(),
          'generalized_residuals_float':algebraic,'hermiticity_defect_absolute':float(herm),
          'Q_positive_by_float_cholesky_only':True,'continuous_graph_form_used':True})
        np.savez_compressed(folder/f'shift-{tau}.npz',selected_vectors=vec[:,selected],selected_mu=vals[selected],g=g,epsilon_coefficients=ec,inverse_epsilon_coefficients=ic)
    calibration=None
    if uniform is not None:
        # Independent 3x3 transverse plane-wave analytic dispersion per Fourier q:
        # nonzero eigenvalues of -Qcross eps^-1 Qcross equal positive f^2.
        exact=[]
        for gx,gy in g:
            q=np.array([gx/4,gy/4,k]);x,y,z=q
            C=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
            exact.extend(np.sqrt(eigvalsh(-C@np.diag(1/np.array(uniform))@C)[1:]).tolist())
        exact=np.sort(exact);errors=[]
        for row in rows:
            tau=row['shift_cycles_per_um']
            expected_below=exact[exact<tau][::-1][:4]
            # Zero modes matter if fewer than four positive modes lie below tau.
            below=np.array(row['below_shift_float_candidates'])
            expected_below=np.pad(expected_below,(0,max(0,len(below)-len(expected_below))))
            above=np.array(row['above_shift_float_candidates']);expected_above=exact[exact>tau][:len(above)]
            errors.extend(abs(below-expected_below[:len(below)]).tolist());errors.extend(abs(above-expected_above).tolist())
        assert max(errors)<1e-8
        calibration={'max_abs_error_vs_independent_plane_wave_dispersion':max(errors),'rounding_certificate':False,'analytic_uniform_calibration_passed':True}
    result={'job':job,'dimension':n,'shifts':rows,'calibration':calibration,
      'random_vector_continuous_graph_norm_squared':continuous,'projected_substitute_squared':projected,'missing_graph_term_squared':continuous-projected,
      'bulk_epsilon':ln_epsilon(w).tolist(),'target_frequency_cycles_per_um':target,'full_vector_periodic':True,
      'status':'CERTIFICATE_INCOMPLETE','floating_only':True,'not_certificate':True,
      'limitations':['No outward coefficient/inertia certification','No validated shift spectral isolation or branch index','No continuous beta slope/identity enclosure','No interface-fitted slab enclosure calibration yet','Fourier trial E is smooth and may converge slowly at normal-E jumps'],
      'fixed_beta_blocks':1,'generalized_eigenproblems':len(job['shifts']),'new_MPB_calls':0,'new_API_calls':0,
      'seconds':time.monotonic()-start,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (folder/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)

if __name__=='__main__':
    request=Path(sys.argv[1]);job=json.loads(request.read_text());folder=request.parent/job['id'];folder.mkdir(exist_ok=False)
    run(job,folder)
