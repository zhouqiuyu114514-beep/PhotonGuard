"""Independent research prototype: diagonal-epsilon full-vector Yee beta² modes.

No MPB imports/calls. Periodic supercell, exp(i beta z - i omega t), h=Z0 H.
Hx at (x,y+dy/2), Hy at (x+dx/2,y), Ez at (x,y), Hz at (x+dx/2,y+dy/2).
This is an exploratory discretization, not a continuous beta error certificate.
"""
import os,resource,signal,time
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1';os.environ['MKL_NUM_THREADS']='1'
resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
resource.setrlimit(resource.RLIMIT_CPU,(60,60));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('60 second prototype limit')))
signal.alarm(60)
START=time.monotonic()
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
from scipy import sparse
from scipy.sparse.linalg import eigs
from scipy.optimize import brentq


def derivative(n,step):
    rows=np.repeat(np.arange(n),2);cols=np.column_stack((np.arange(n),(np.arange(n)+1)%n)).ravel()
    values=np.tile([-1/step,1/step],n)
    plus=sparse.coo_matrix((values,(rows,cols)),shape=(n,n)).tocsr()
    return plus,-plus.T


def operator(ex,ey,ez,sx,sy,wave):
    nx,ny=ez.shape;dx,dy=sx/nx,sy/ny;n=nx*ny;k0=2*np.pi/wave
    px,mx=derivative(nx,dx);py,my=derivative(ny,dy)
    xp=sparse.kron(px,sparse.eye(ny),format='csr');xm=sparse.kron(mx,sparse.eye(ny),format='csr')
    yp=sparse.kron(sparse.eye(nx),py,format='csr');ym=sparse.kron(sparse.eye(nx),my,format='csr')
    X=sparse.diags(ex.ravel());Y=sparse.diags(ey.ravel());Z=sparse.diags(1/ez.ravel());I=sparse.eye(n)
    Axx=xm@xp+Y@(k0*k0*I+yp@Z@ym)
    Axy=xm@yp-Y@yp@Z@xm
    Ayx=ym@xp-X@xp@Z@ym
    Ayy=ym@yp+X@(k0*k0*I+xp@Z@xm)
    A=sparse.bmat([[Axx,Axy],[Ayx,Ayy]],format='csc')
    return A,(xp,xm,yp,ym),k0


def recover(vector,beta,derivatives,ex,ey,ez,k0):
    xp,xm,yp,ym=derivatives;n=ex.size;hx,hy=vector[:n],vector[n:]
    hz=1j/beta*(xp@hx+yp@hy)
    Ex=1j/k0*(ym@hz-1j*beta*hy)/ex.ravel()
    Ey=1j/k0*(1j*beta*hx-xm@hz)/ey.ravel()
    Ez=1j/k0*(xm@hy-ym@hx)/ez.ravel()
    electric=np.vstack((Ex,Ey,Ez));magnetic=np.vstack((hx,hy,hz))
    curlE=np.vstack((yp@Ez-1j*beta*Ey,1j*beta*Ex-xp@Ez,xp@Ey-yp@Ex))
    curl_res=np.linalg.norm(curlE-1j*k0*magnetic)/max(np.linalg.norm(k0*magnetic),1e-30)
    div_h=xp@hx+yp@hy+1j*beta*hz
    div_d=xm@(ex.ravel()*Ex)+ym@(ey.ravel()*Ey)+1j*beta*ez.ravel()*Ez
    return electric,magnetic,{'curl_E_relative_residual':float(curl_res),
        'div_H_relative_residual':float(np.linalg.norm(div_h)/max(beta*np.linalg.norm(magnetic),1e-30)),
        'div_D_relative_residual':float(np.linalg.norm(div_d)/max(beta*np.linalg.norm(electric),1e-30))}


def solve(ex,ey,ez,sx,sy,wave,guess_neff,count=6):
    A,D,k0=operator(ex,ey,ez,sx,sy,wave)
    vals,vec=eigs(A,k=count,sigma=(k0*guess_neff)**2,which='LM',tol=1e-10,maxiter=200,
        v0=np.random.default_rng(20261008).normal(size=A.shape[0]))
    rows=[];fields=[]
    for j in np.argsort(vals.real)[::-1]:
        value=vals[j];v=vec[:,j];require(abs(value.imag)<1e-7,'unexpected complex beta squared')
        if value.real<=0:continue
        beta=math.sqrt(value.real);E,H,residuals=recover(v,beta,D,ex,ey,ez,k0)
        energy_E=np.sum(abs(E)**2,axis=1);energy_H=np.sum(abs(H)**2,axis=1)
        row={'neff':beta/k0,'beta_rad_per_um':beta,'beta_cycles_per_um':beta/(2*np.pi),
            'eigen_residual':float(np.linalg.norm(A@v-value*v)/max(np.linalg.norm(value*v),1e-30)),
            'E_L2_component_fractions':(energy_E/energy_E.sum()).tolist(),
            'H_L2_component_fractions':(energy_H/energy_H.sum()).tolist(),**residuals}
        rows.append(row);fields.append((E,H))
    return rows,fields,{'matrix_shape':list(A.shape),'matrix_nnz':A.nnz,'eigensolver_calls':1,
        'eigensolver':'scipy ARPACK shift-invert / SuperLU','field_normalization':'arbitrary eigenvector L2; not 1 W'}


def require(value,reason):
    if not value:raise ValueError(reason)


def fraction(center,width,left,right):
    return np.maximum(0.,np.minimum(center+width/2,right)-np.maximum(center-width/2,left))/width


def overlap_weights(centers, step, edges, period):
    """Exact periodic interval fractions; each window spans one grid cell."""
    result=np.zeros((len(centers),len(edges)-1))
    for shift in (-period,0.,period):
        result += np.maximum(0.,np.minimum(centers[:,None]+step/2,edges[None,1:]+shift)
            -np.maximum(centers[:,None]-step/2,edges[None,:-1]+shift))/step
    require(np.max(abs(result.sum(axis=1)-1))<1e-12,'tile partition incomplete')
    return result


def material_builder(x,y,dx,dy,xedges,yedges,tile_epsilon,sx,sy):
    """Directional edge-voltage/dual-flux closure, common to every geometry.

    Ex: < <1/eps_x>_x^-1 >_y; Ey: < <1/eps_y>_y^-1 >_x;
    Ez: <eps_z>_xy. The parallel-strip assumption at corners is approximate.
    No MPB tensors, geometry or effective-material routines are imported.
    """
    arrays=[]
    for comp,(ox,oy) in enumerate(((dx/2,0),(0,dy/2),(0,0))):
        wx=overlap_weights(x+ox,dx,xedges,sx)
        wy=overlap_weights(y+oy,dy,yedges,sy)
        local=tile_epsilon[:,:,comp]
        if comp==0:eps=(1/(wx@(1/local)))@wy.T
        elif comp==1:eps=wx@(1/((1/local)@wy.T))
        else:eps=wx@local@wy.T
        require(np.all(np.isfinite(eps)) and np.min(eps)>0,'invalid constitutive coefficient')
        arrays.append(eps)
    return arrays


def analytic_slab(wave,width,core,clad,polarization):
    k0=2*np.pi/wave;a=width/2
    if polarization=='TE':
        upper=k0*k0*core[1]
        def u(beta2):return a*np.sqrt(max(0.,upper-beta2))
        factor=1.;cutoff=upper-(np.pi/(2*a))**2
    else:
        upper=k0*k0*core[0]
        def u(beta2):return a*np.sqrt(max(0.,core[2]*(k0*k0-beta2/core[0])))
        factor=core[2]/clad;cutoff=core[0]*(k0*k0-(np.pi/(2*a))**2/core[2])
    lower=max(k0*k0*clad,cutoff)
    def residual(beta2):
        z=u(beta2);w=a*np.sqrt(max(0.,beta2-k0*k0*clad))
        return z*np.tan(z)-factor*w
    return float(np.sqrt(brentq(residual,lower+1e-10,upper-1e-10,xtol=1e-12))/k0)


def geometry(config):
    sx,sy=config['domain_um'];nx,ny=config['grid'];dx,dy=sx/nx,sy/ny
    phase=np.array(config['grid_phase_cells'])
    x=(np.arange(nx)/nx-.5)*sx+phase[0]*dx
    y=(np.arange(ny)/ny-.5)*sy+phase[1]*dy
    if config['geometry']=='slab':
        core=np.array(config['core_epsilon']);clad=1.44**2
        xe=np.array([-sx/2,-.3,.3,sx/2]);ye=np.array([-sy/2,sy/2])
        tiles=np.full((3,1,3),clad);tiles[1,0]=core
    else:
        wave=config['wavelength_um']
        def n2(terms):return 1+sum(a*wave*wave/(wave*wave-b) for a,b in terms)
        no2=n2([(2.6734,.01764),(1.229,.05914),(12.614,474.6)])
        ne2=n2([(2.9804,.02047),(.5981,.0666),(8.9543,416.08)])
        core=np.array([ne2,no2,no2])
        xe=np.array([-sx/2,-.7,.7,sx/2]);ye=np.array([-sy/2,-.3,0.,.3,sy/2])
        tiles=np.ones((3,4,3));tiles[:,0,:]=1.44**2;tiles[:,1,:]=core;tiles[1,2,:]=core
    arrays=material_builder(x,y,dx,dy,xe,ye,tiles,sx,sy)
    return arrays,x,y,core,{'x_edges_um':xe.tolist(),'y_edges_um':ye.tolist(),'tile_epsilon':tiles.tolist()}


def storage_fields(E,H,shape,x,y,dx,dy,prefix=''):
    arrays={}
    for kind,field,offsets in [('E',E,((dx/2,0),(0,dy/2),(0,0))),
                              ('h',H,((0,dy/2),(dx/2,0),(dx/2,dy/2)))]:
        for i,(ox,oy) in enumerate(offsets):
            label=prefix+kind+'xyz'[i]
            arrays[label]=np.asarray(field[i].reshape(shape),dtype=np.complex128)
            arrays[label+'_x_um']=x+ox;arrays[label+'_y_um']=y+oy
    return arrays


def builder_checks():
    # An off-grid planar interface has a closed-form normal/tangential average.
    x=np.array([-.25,.25]);y=np.array([-.25,.25]);edge=np.array([-.5,-.1,.5])
    vals=np.array([[[4.,5.,6.]],[[1.,2.,3.]]])
    eps=material_builder(x,y,.5,.5,edge,np.array([-.5,.5]),vals,1.,1.)
    wx=overlap_weights(x+.25,.5,edge,1.);w0=overlap_weights(x,.5,edge,1.)
    require(np.max(abs(eps[0]-(1/(wx@np.array([.25,1.])))[:,None]))<1e-13,'normal harmonic check')
    require(np.max(abs(eps[1]-(w0@np.array([5.,2.]))[:,None]))<1e-13,'tangential arithmetic check')
    # Transpose tests the y-normal branch with anisotropic components swapped.
    swapped=vals.transpose(1,0,2)[:,:,[1,0,2]]
    rotated=material_builder(y,x,.5,.5,np.array([-.5,.5]),edge,swapped,1.,1.)
    require(np.max(abs(eps[0]-rotated[1].T))<1e-13,'axis permutation Ex/Ey')
    require(np.max(abs(eps[1]-rotated[0].T))<1e-13,'axis permutation Ey/Ex')
    require(np.max(abs(eps[2]-rotated[2].T))<1e-13,'axis permutation Ez')
    return {'planar_normal_harmonic':True,'planar_tangent_arithmetic':True,'anisotropic_axis_permutation':True}


def experiment(config,outdir):
    arrays,x,y,core,tiles=geometry(config)
    sx,sy=config['domain_um'];nx,ny=config['grid'];wave=config['wavelength_um']
    rows,fields,meta=solve(*arrays,sx,sy,wave,float(np.sqrt(max(core)))*1.001 if config['geometry']=='slab' else float(np.sqrt(core[0]))*.98)
    require(max(r['eigen_residual'] for r in rows)<1e-7,'eigen residual')
    require(max(r['curl_E_relative_residual'] for r in rows)<1e-7,'Maxwell residual')
    saved={};checks=[];selected=[]
    if config['geometry']=='slab':
        for pol,hindex in [('TE',0),('TM',1)]:
            index=max((j for j,r in enumerate(rows) if r['H_L2_component_fractions'][hindex]>.5),key=lambda j:rows[j]['neff'])
            exact=analytic_slab(wave,.6,core,1.44**2,pol)
            checks.append({'polarization':pol,'analytic_neff':exact,'fd_neff':rows[index]['neff'],
                'signed_neff_error':rows[index]['neff']-exact,'selected_index_zero_based':index})
            selected.append(index);saved.update(storage_fields(*fields[index],(nx,ny),x,y,sx/nx,sy/ny,pol+'_'))
    else:
        index=max((j for j,r in enumerate(rows) if r['E_L2_component_fractions'][0]>.5),key=lambda j:rows[j]['neff'])
        selected=[index];saved.update(storage_fields(*fields[index],(nx,ny),x,y,sx/nx,sy/ny))
    for j in selected:
        E,H=fields[j]
        # Ex/Hy and Ey/Hx live at the same respective Yee sites. Sum two
        # quadratures; do not multiply vectors from mismatched staggered sites.
        rows[j]['scaled_z_flux_quadrature']=float(.5*np.real(np.sum(E[0]*H[1].conj()-E[1]*H[0].conj()))*(sx/nx)*(sy/ny))
    for i,eps in enumerate(arrays):saved['eps_'+'xyz'[i]]=eps
    npz=outdir/(config['id']+'.npz')
    with npz.open('xb') as stream:np.savez(stream,**saved)
    return {'config':config,'material_builder':'directional_edge_dual_flux_v2','bulk_epsilon_core':core.tolist(),
        'continuous_geometry_tiles':tiles,'all_modes':rows,'selected_indices_zero_based':selected,
        'analytic_slab_checks':checks,'fields_file':npz.name,'fields_sha256':hashlib.sha256(npz.read_bytes()).hexdigest(),
        'fields_bytes':npz.stat().st_size,'complex_fields_saved':True,'magnetic_field_convention':'h=Z0 H',
        'coordinates':'per component physical um; periodic grid phase changes sampling, not geometry',
        'scaled_z_flux_units':'arbitrary electric amplitude squared * um^2; divide by Z0 and convert area to SI for W',
        'not_continuous_error_certificate':True,'corner_closure_approximate':True,**meta}


def main():
    p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--id',required=True)
    args=p.parse_args();plan_bytes=args.plan.read_bytes();plan=json.loads(plan_bytes)
    selfsha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    require(selfsha==plan['worker_sha256'],'frozen worker source mismatch')
    require(len(plan['cases'])==4 and plan['max_worker_attempts']==4,'batch cap')
    configs=[c for c in plan['cases'] if c['id']==args.id];require(len(configs)==1,'exact case whitelist')
    folder=args.plan.parent;out=folder/(args.id+'.json');start=folder/(args.id+'.started.json')
    require(not out.exists(),'no result overwrite')
    require(sum(p.stat().st_size for p in folder.iterdir() if p.is_file())<100*1024**2,'output reserve exhausted')
    require(len(list(folder.glob('*.started.json')))<4,'attempt budget exhausted')
    receipt={'id':args.id,'source_sha256':selfsha,'plan_sha256':hashlib.sha256(plan_bytes).hexdigest()}
    with start.open('x') as stream:json.dump(receipt,stream,indent=2)
    try:
        checks=builder_checks();result=experiment(configs[0],folder);result['builder_checks']=checks;result['status']='OK'
    except BaseException as error:
        result={'status':'FAILED','error_type':type(error).__name__,'error':str(error)}
    result.update(receipt,wall_seconds=time.monotonic()-START,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        resource_limits={'wall_seconds':60,'address_space_bytes':2*1024**3},
        MPB_calls=0,model_calls=0,production_acceptance_modified=False)
    with out.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps({k:result[k] for k in ('id','status','wall_seconds','peak_rss_mib')}))
    if result['status']!='OK':raise SystemExit(1)

if __name__=='__main__':main()
