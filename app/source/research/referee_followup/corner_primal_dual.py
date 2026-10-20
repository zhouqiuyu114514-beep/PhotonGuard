"""Matched-boundary P2 primal / rotated-P1 dual local electrostatic bounds.

Bounds enclose energies for exact stored binary64 coefficients on an exact
dyadic fitted mesh. They do not certify material data, Maxwell dynamics or beta.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
from pathlib import Path
import argparse,json,hashlib,time,resource,sys
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
OUT=ROOT/'local-validation/referee-followup-20261008/e2'
from photonguard.materials.ln_sellmeier import dielectric_tensor

def interval(x):return np.asarray(x,dtype=float),np.asarray(x,dtype=float)
def add(a,b):return np.nextafter(a[0]+b[0],-np.inf),np.nextafter(a[1]+b[1],np.inf)
def neg(a):return -a[1],-a[0]
def mul(a,b):
    c=np.stack([a[0]*b[0],a[0]*b[1],a[1]*b[0],a[1]*b[1]])
    return np.nextafter(c.min(axis=0),-np.inf),np.nextafter(c.max(axis=0),np.inf)
def reduce_sum(a,axis=0):
    lo=np.moveaxis(a[0],axis,0);hi=np.moveaxis(a[1],axis,0)
    while len(lo)>1:
        n=len(lo)//2;b=add((lo[:2*n:2],hi[:2*n:2]),(lo[1:2*n:2],hi[1:2*n:2]))
        lo=np.concatenate([b[0],lo[-1:]],axis=0) if len(lo)%2 else b[0]
        hi=np.concatenate([b[1],hi[-1:]],axis=0) if len(hi)%2 else b[1]
    return lo[0],hi[0]
def div_positive(a,b):return mul(a,(np.nextafter(1/np.asarray(b),-np.inf),np.nextafter(1/np.asarray(b),np.inf)))
def quad(a,epsilon):
    out=interval(np.zeros(a[0].shape[:-1]))
    for i in range(2):
        for j in range(2):out=add(out,mul(mul((a[0][...,i],a[1][...,i]),(a[0][...,j],a[1][...,j])),interval(epsilon[...,i,j])))
    return out

def mesh(N):
    assert N in (2,4,8,16,32,64) # dyadic geometry and gradients are exact binary64
    ij=np.array([(i,j) for i in range(N) for j in range(N)])
    a=ij*(2);b=a+[2,0];c=a+[2,2];d=a+[0,2]
    raw=np.stack([np.stack([a,b,c],1),np.stack([a,c,d],1)],1).reshape(-1,3,2)
    fine=np.concatenate([raw,(raw[:,0:1]+raw[:,1:2])//2,(raw[:,1:2]+raw[:,2:3])//2,(raw[:,2:3]+raw[:,0:1])//2],axis=1)
    t2=fine[:,:,0]*(2*N+1)+fine[:,:,1];t1=(raw[:,:,0]//2)*(N+1)+raw[:,:,1]//2
    v2=np.array([(i/(2*N)-.5,j/(2*N)-.5) for i in range(2*N+1) for j in range(2*N+1)])
    v1=np.array([(i/N-.5,j/N-.5) for i in range(N+1) for j in range(N+1)])
    grad=np.tile(np.array([[[-N,0],[N,-N],[0,N]],[[0,-N],[N,0],[-N,N]]]),(N*N,1,1))
    G=np.empty((len(t1),3,6,2))
    for k in range(3):
        for i in range(3):G[:,k,i]=(4*int(i==k)-1)*grad[:,i]
        for z,(i,j) in enumerate(((0,1),(1,2),(2,0))):G[:,k,3+z]=4*(int(i==k)*grad[:,j]+int(j==k)*grad[:,i])
    return v1,v2,t1,t2,grad,G,1/(2*N*N)

def boundary_values(xy,kind='standard'):
    x,y=xy.T
    if kind=='plane':return np.stack([np.where(x<=0,(x+.5)/2,.25+x/4),y],1)
    return np.stack([x,y,x*x-y*y,x*y],1)
def g_grad_vertices(xy,kind='standard'):
    x,y=xy[:,:,0],xy[:,:,1];z=np.zeros_like(x);o=np.ones_like(x)
    if kind=='plane':
        # Each fitted triangle lies wholly on one side; coefficients at interface
        # use that triangle's material side, not an ambiguous point value.
        slope=np.where(x.mean(axis=1)<=0,.5,.25)
        return np.stack([np.stack([slope[:,None]*o,z],-1),np.stack([z,o],-1)],axis=2)
    return np.stack([np.stack([o,z],-1),np.stack([z,o],-1),np.stack([2*x,-2*y],-1),np.stack([y,x],-1)],axis=2)

def energy_bounds(u,psi,t1,t2,grad,G,area,eps,gg):
    # Interpret every stored coefficient exactly; round each arithmetic operation
    # outward. Pairwise interval reduction avoids an unchecked np.sum rounding.
    assert np.array_equal(eps[:,0,1],eps[:,1,0])
    assert np.all(eps[:,0,0]>0)
    coeff=u[t2];e=interval(np.zeros((len(t2),3,2)))
    for j in range(6):e=add(e,mul(interval(coeff[:,None,j,None]),interval(G[:,:,j,:])))
    total_e=reduce_sum(e,axis=1)
    sum_diag=reduce_sum(quad(e,eps[:,None,:,:]),axis=1)
    U=reduce_sum(mul(div_positive(add(sum_diag,quad(total_e,eps)),12),interval(area)))
    q=interval(np.zeros((len(t1),2)))
    for j in range(3):q=add(q,mul(interval(psi[t1[:,j],None]),interval(grad[:,j,:])))
    q=(np.stack([q[0][:,1],-q[1][:,0]],axis=-1),np.stack([q[1][:,1],-q[0][:,0]],axis=-1))
    mean_g=div_positive(reduce_sum(interval(gg),axis=1),3)
    pairing=reduce_sum(mul(mean_g,q),axis=1)
    # Exact inverse of a positive 2x2 stored tensor, with outward operations.
    determinant=add(mul(interval(eps[:,0,0]),interval(eps[:,1,1])),neg(mul(interval(eps[:,0,1]),interval(eps[:,1,0]))))
    assert np.all(determinant[0]>0)
    inv_det=(np.nextafter(1/determinant[1],-np.inf),np.nextafter(1/determinant[0],np.inf))
    qinvq=interval(np.zeros(len(t1)))
    for i in range(2):
        for j in range(2):
            cofactor=eps[:,1-i,1-j]*(1 if i==j else -1)
            qinvq=add(qinvq,mul(mul((q[0][:,i],q[1][:,i]),(q[0][:,j],q[1][:,j])),mul(interval(cofactor),inv_det)))
    L=reduce_sum(mul(add(mul(interval(2),pairing),neg(qinvq)),interval(area)))
    assert np.isfinite([*U,*L]).all() and L[0]<=U[1]
    return {'lower':float(L[0]),'upper':float(U[1]),'relative_gap':float((U[1]-L[0])/U[1]),
        'upper_rounding_width':float(U[1]-U[0]),'lower_rounding_width':float(L[1]-L[0])}

def assembled(N,eps_kind,wave=1.55,constant=None):
    v1,v2,t1,t2,grad,G,area=mesh(N);centers=v1[t1].mean(axis=1);nt=len(t1)
    bulk=np.asarray(dielectric_tensor(wave)['laboratory_epsilon'])[:2,:2]
    if eps_kind=='corner':eps=np.where(((centers[:,0]>0)&(centers[:,1]>0))[:,None,None],np.eye(2),bulk)
    elif eps_kind=='plane':eps=np.where((centers[:,0]<0)[:,None,None],2*np.eye(2),4*np.eye(2))
    else:eps=np.tile(2*np.eye(2) if constant is None else constant,(nt,1,1))
    # Exact polynomial integral represented in floats only for finding trial functions.
    C=np.ones((3,3));np.fill_diagonal(C,2);C*=area/12
    kel=np.einsum('tvia,tab,twjb,vw->tij',G,eps,G,C,optimize=True)
    def sparse(local,t,n):return coo_matrix((local.ravel(),(np.repeat(t,t.shape[1],axis=1).ravel(),np.tile(t,(1,t.shape[1])).ravel())),shape=(n,n)).tocsc()
    K=sparse(kel,t2,len(v2))
    rotated=np.stack([grad[:,:,1],-grad[:,:,0]],axis=-1)
    dual_local=area*np.einsum('tia,tab,tjb->tij',rotated,np.linalg.inv(eps),rotated,optimize=True)
    D=sparse(dual_local,t1,len(v1))
    return v1,v2,t1,t2,grad,G,area,eps,K,D,rotated

def solve_case(N,wave,kind='corner',constant=None):
    v1,v2,t1,t2,grad,G,area,eps,K,D,rotated=assembled(N,kind,wave,constant)
    mask=np.any(abs(v2)==.5,axis=1);inner=np.flatnonzero(~mask);free=np.arange(1,len(v1))
    values=boundary_values(v2);gg=g_grad_vertices(v1[t1]);U=values.copy();U[inner]=0
    primal=splu(K[inner][:,inner]);dual=splu(D[free][:,free]);P=np.zeros((len(v1),4))
    rhs_local=area*np.einsum('tqa,tia->tiq',gg.mean(axis=1),rotated)
    rhs=np.zeros((len(v1),4))
    for col in range(4):np.add.at(rhs[:,col],t1.ravel(),rhs_local[:,:,col].ravel())
    if kind=='corner':
        U[inner]=primal.solve(-(K@U)[inner]);P[free]=dual.solve(rhs[free]);solves=8
    else:
        # Affine g has exact u=g and constant q=epsilon grad g; use its affine
        # streamfunction. Only quadratic g needs new primal/dual RHS solves.
        U[:,0:2]=values[:,0:2];e=eps[0]
        for col in range(2):P[:,col]=e[0,col]*v1[:,1]-e[1,col]*v1[:,0]
        P-=P[0]
        U[inner,2:]=primal.solve(-(K@U[:,2:])[inner]);P[free,2:]=dual.solve(rhs[free,2:]);solves=4
    bounds=[energy_bounds(U[:,col],P[:,col],t1,t2,grad,G,area,eps,gg[:,:,col,:]) for col in range(4)]
    boundary_error=float(np.max(abs(U[mask]-values[mask])));assert boundary_error==0
    # Rotated gradient of globally continuous P1 has identically zero element
    # divergence and continuous normal flux in exact arithmetic.
    response=U.T@(K@U)
    result={'N':N,'wave':wave,'kind':kind,'constant_tensor':None if constant is None else constant.tolist(),
        'excitations':['x','y','x^2-y^2','xy'],'bounds':bounds,'primal_port_energy_matrix_float':response.tolist(),
        'linear_rhs_solves':solves,'boundary_trace_error':boundary_error,'bulk_epsilon_frozen_binary64':eps.max(axis=0).tolist(),
        'primal_space':'continuous fitted P2, exact prescribed quadratic trace','dual_space':'rotated gradient of continuous P1; divergence zero, normal continuity exact',
        'full_boundary_DtN_not_computed':True,'interval_arithmetic':'binary64 outward nextafter at every operation and pairwise sum; stored coefficients interpreted exactly',
        'not_full_wave_or_beta_certificate':True}
    return result,{'primal_coefficients':U,'dual_stream_coefficients':P,'vertices_p1':v1,'vertices_p2':v2,'triangles_p1':t1,'triangles_p2':t2,'piecewise_epsilon':eps}

def calibrate():
    records=[]
    for kind in ('constant','plane'):
        v1,v2,t1,t2,grad,G,area,eps,K,D,rotated=assembled(8,kind)
        values=boundary_values(v2,'plane' if kind=='plane' else 'standard');gg=g_grad_vertices(v1[t1],'plane' if kind=='plane' else 'standard')
        mask=np.any(abs(v2)==.5,axis=1);inner=np.flatnonzero(~mask)
        exact_energies=[2.,2.,4/3,1/3] if kind=='constant' else [.375,3.]
        for col,energy in enumerate(exact_energies):
            u=values[:,col]
            if kind=='constant':
                x,y=v1.T
                psi=[2*y,-2*x,4*x*y,y*y-x*x][col]
            elif col==0:psi=v1[:,1]
            else:psi=np.where(v1[:,0]<=0,-2*v1[:,0],-4*v1[:,0])
            rec=energy_bounds(u,psi,t1,t2,grad,G,area,eps,gg[:,:,col,:]);assert rec['lower']<=energy<=rec['upper']
            residual=float(np.max(abs((K@u)[inner])));assert residual<1e-11
            records.append({'kind':kind,'excitation':col,'analytic_energy':energy,'bounds':rec,'primal_assembled_residual':residual})
    return records

def tau(core,angle):
    a=np.deg2rad(angle);Q=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
    def T(e):return np.array([[-1/e[0,0],e[0,1]/e[0,0]],[e[1,0]/e[0,0],e[1,1]-e[1,0]*e[0,1]/e[0,0]]])
    z=.75*T(Q.T@core@Q)+.25*T(np.eye(2));e=np.array([[-1/z[0,0],-z[0,1]/z[0,0]],[-z[1,0]/z[0,0],z[1,1]-z[1,0]*z[0,1]/z[0,0]]])
    out=Q@e@Q.T
    out[0,1]=out[1,0]=(out[0,1]+out[1,0])/2
    return out

def run():
    plan=json.loads((OUT/'plan.json').read_text());assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==plan['worker_sha256']
    with (OUT/'STARTED.json').open('x') as f:json.dump({'at':time.time(),'plan_sha256':hashlib.sha256((OUT/'plan.json').read_bytes()).hexdigest()},f)
    started=time.monotonic();cal=calibrate();rows=[];counts=0
    for wave in (1.55,.775):
        for N in (16,32,64):
            result,arrays=solve_case(N,wave);counts+=result['linear_rhs_solves']
            name=f'corner-{wave}-{N}';np.savez_compressed(OUT/(name+'.npz'),**arrays)
            result['coefficients_npz']=name+'.npz';rows.append(result);print(name+' max gap '+str(max(b['relative_gap'] for b in result['bounds'])),flush=True)
        core=np.asarray(dielectric_tensor(wave)['laboratory_epsilon'])[:2,:2]
        # One-cell directional series/parallel under the stated 3/4 occupancy.
        yee=np.diag([.5*core[i,i]+.5/(.5/core[i,i]+.5) for i in (0,1)])
        for name,constant in [('tau45',tau(core,45)),('yee_series_parallel',yee)]:
            result,arrays=solve_case(64,wave,'constant',constant);counts+=result['linear_rhs_solves'];result['closure']=name
            file=f'{name}-{wave}.npz';np.savez_compressed(OUT/file,**arrays);result['coefficients_npz']=file;rows.append(result)
        assert counts<=64 and time.monotonic()-started<600
        assert sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())<32*1024**2
    comparisons=[]
    for row in [r for r in rows if r['kind']=='constant']:
        reference=next(r for r in rows if r['kind']=='corner' and r['wave']==row['wave'] and r['N']==64)
        comparisons.append({'wave':row['wave'],'closure':row['closure'],
            'outside_reference_intervals':[a['upper']<b['lower'] or b['upper']<a['lower'] for a,b in zip(row['bounds'],reference['bounds'])],
            'reference_gaps':[b['relative_gap'] for b in reference['bounds']],
            'reference_gap_requirement_met':all(b['relative_gap']<1e-3 for b in reference['bounds']),
            'scope':'matched exact quadratic Dirichlet trace, unit 3/4-filled static corner; no Maxwell claim'})
    summary={'status':'COMPLETED_LOCAL_STATIC_ENERGY_ENCLOSURES','calibrations':cal,'rows':rows,'comparisons':comparisons,
        'linear_rhs_solves':counts,'calibration_new_linear_solves':0,'calibration_method':'analytic feasible polynomial fields and assembled residual; no solve needed',
        'seconds':time.monotonic()-started,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'new_MPB_calls':0,'new_API_calls':0,'production_unchanged':True,'continuous_beta_certificate':False,
        'limitations':['static local response only','material coefficients are exact stored binary64 values, not certified experimental material intervals','4-port response, not full boundary Schur matrix','normal/tangential transmission follows conforming spaces; dynamic remainder not bounded']}
    with (OUT/'summary.json').open('x') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
    print(json.dumps({'status':summary['status'],'linear_rhs_solves':counts,'seconds':summary['seconds'],'comparisons':comparisons}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--calibrate',action='store_true');a=p.parse_args()
    if a.calibrate:print(json.dumps(calibrate()))
    else:run()
