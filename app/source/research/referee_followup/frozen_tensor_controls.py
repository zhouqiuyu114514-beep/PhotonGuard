"""New bounded referee E1 window. No model calls or production result writes."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
from pathlib import Path
import argparse,json,hashlib,subprocess,sys,time,resource,math,shutil
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local-validation/referee-followup-20261008/e1-fixed-v2'
PROD=ROOT/'local-validation/production-cap-validation-20261008/mode-artifacts/20261008T040316Z-cff43b8a'
sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,d):
    with Path(p).open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')
def size():return sum(p.stat().st_size for p in OUT.rglob('*') if p.is_file())

def replay(E,H,inv,k,spacing):
    import numpy as np
    nx,ny=H.shape[:2];gx=np.fft.fftfreq(nx,spacing[0]);gy=np.fft.fftfreq(ny,spacing[1])
    if nx%2==0:gx[nx//2]*=-1
    if ny%2==0:gy[ny//2]*=-1
    q=np.empty((nx,ny,3));q[:,:,0]=gx[:,None];q[:,:,1]=gy[None,:];q[:,:,2]=k
    def curl(v):return np.fft.ifftn(np.cross(q,np.fft.fftn(v,axes=(0,1))),axes=(0,1))
    def A(v):return -curl(np.einsum('xyij,xyj->xyi',inv,curl(v)))
    hhat=np.fft.fftn(H,axes=(0,1));q2=np.sum(q*q,axis=-1)
    longitudinal=q*np.sum(q*hhat,axis=-1)[:,:,None]/q2[:,:,None]
    projection_loss=float(np.linalg.norm(longitudinal)/np.linalg.norm(hhat))
    applied=A(H);rho=np.vdot(H,applied)/np.vdot(H,H);r=applied-rho.real*H
    absolute=float(np.linalg.norm(r)/np.linalg.norm(H))
    X,Y=np.meshgrid((np.arange(nx)/nx-.5)*4,(np.arange(ny)/ny-.5)*4,indexing='ij')
    radius=2*max(spacing)
    corners=np.minimum((X-.7)**2+Y**2,(X+.7)**2+Y**2)<=radius**2
    planes=(abs(Y+.3)<=radius)|(abs(Y-0.3)<=radius)|(abs(abs(Y)-2)<=radius)
    masks={'shoulders':corners,'flat_planes_excluding_shoulders':planes&~corners,'remaining':~(planes|corners)}
    density=np.sum(abs(r)**2,axis=-1);total=float(density.sum())
    Rhat=np.fft.fftn(r,axes=(0,1));tail=(abs(gx[:,None])>.75*max(abs(gx)))|(abs(gy[None,:])>.75*max(abs(gy)))
    rng=np.random.default_rng(20261008);u=rng.normal(size=H.shape)+1j*rng.normal(size=H.shape)
    v=rng.normal(size=H.shape)+1j*rng.normal(size=H.shape)
    au,av=A(u),A(v);left=np.vdot(u,av);right=np.vdot(au,v)
    hermitian_defect=float(abs(left-right)/(np.linalg.norm(u)*np.linalg.norm(av)+np.linalg.norm(au)*np.linalg.norm(v)))
    assert hermitian_defect<2e-13 and projection_loss<1e-9
    return {'rho_frequency_squared_cycles':float(rho.real),'rho_imaginary':float(rho.imag),
        'absolute_eigen_residual':absolute,'relative_eigen_residual':absolute/abs(float(rho.real)),
        'projection_loss_l2':projection_loss,'random_bilinear_hermiticity_defect':hermitian_defect,
        'residual_squared_fractions':{key:float(density[mask].sum()/total) if total else 0 for key,mask in masks.items()},
        'high_frequency_residual_fraction':float(np.sum(abs(Rhat[tail])**2)/np.sum(abs(Rhat)**2)),
        'not_continuous_error_bound':True},r

def prepare():
    import numpy as np
    from photonguard.approved_gui import source_manifest
    from photonguard.mode_numerical_review import load_research_evidence
    OUT.mkdir(parents=True,exist_ok=False)
    shutil.copy2(__file__,OUT/'frozen_worker.py')
    inputs={}
    for wave in (1.55,.775):
        cap=ROOT/f'local-validation/equivalent-cap-20261008/C2-cap-{wave}'
        record=read(cap/'result.json');fields,tensors,_=load_research_evidence(cap/'evidence',record['persisted_evidence']['manifest_sha256'])
        production=read(PROD/f'base-{wave}/result.json')
        assert record['selected_mode']['neff']==production['selected_mode']['neff']
        target=OUT/f'input-{wave}.npz';np.savez_compressed(target,**tensors,x_um=fields['x_um'],y_um=fields['y_um'])
        inputs[str(wave)]={'path':target.name,'sha256':sha(target),'old_result_path':str(PROD/f'base-{wave}/result.json'),
            'old_result_sha256':sha(PROD/f'base-{wave}/result.json'),'old_field_sha256':sha(PROD/f"base-{wave}"/production['selected_mode']['fields_npz']),
            'cap_tensor_manifest_sha256':record['persisted_evidence']['manifest_sha256'],'old_selected':production['selected_mode']}
    jobs=[]
    jobs += [{'id':f'fixed-{w}-{tol}','wave':w,'kind':'fixed','tolerance':tol} for w in (1.55,.775) for tol in (1e-9,1e-12)]
    plan={'schema_version':1,'source':source_manifest(ROOT),'worker_sha256':sha(OUT/'frozen_worker.py'),'inputs':inputs,'jobs':jobs,
        'resources':{'find_max':0,'fixed_blocks_max':4,'solve_kpoint_total_max':4,'seconds_each_max':300,'seconds_total_max':1200,
          'vmem_bytes':2*1024**3,'output_bytes':256*1024**2,'file_bytes':32*1024**2,'api_calls':0,'automatic_retries':0},
        'authority':'Owner 2026-10-08 requested implementation of attached Pro review; new separate E1 window within proposed limits.',
        'physical_task_sha256':sha(PROD/'task.json'),'production_unchanged':True,
        'fixed_k': 'original cap selected k at each wavelength; all four frequencies from this same operator',
        'prior_window':'e1','prior_find_k':2,'prior_eigenproblems_including_failed_capture':28,'amendment':'Official raw solve_kpoint does not update Python current_k. Set the supplied k on the wrapper before capture. Old failed capture and its one completed solve remain recorded. Only four fixed-k blocks, no repeated find_k.', 'diagnostic_phase_resolution_rad':.01,'not_an_acceptance_threshold':True}
    save(OUT/'plan.json',plan);print(json.dumps({'status':'FROZEN','plan_sha256':sha(OUT/'plan.json'),'jobs':4}))

def worker(request):
    import numpy as np
    import meep as mp
    from meep import mpb
    from photonguard.materials.ln_sellmeier import dielectric_tensor
    from photonguard.mpb_metadata import actual_grid,restore_array,runtime_build_fingerprint
    from photonguard.adapters.mpb_research_worker import effective_tensors_after_solve
    job=request['job'];plan=read(OUT/'plan.json');assert job in plan['jobs']
    assert sha(OUT/'plan.json')==request['plan_sha256'] and sha(__file__)==plan['worker_sha256']
    entry=plan['inputs'][str(job['wave'])];assert sha(OUT/entry['path'])==entry['sha256']
    old=read(entry['old_result_path']);assert sha(entry['old_result_path'])==entry['old_result_sha256']
    oldfield=Path(entry['old_result_path']).parent/old['selected_mode']['fields_npz'];assert sha(oldfield)==entry['old_field_sha256']
    with np.load(oldfield,allow_pickle=False) as data:reference={key:data[key].copy() for key in ('E','H')}
    with np.load(OUT/entry['path'],allow_pickle=False) as data:epsilon=data['epsilon'].copy();inverse=data['inverse_epsilon'].copy();x=data['x_um'].copy();y=data['y_um'].copy()
    cache={}
    def material(point):
        ix=int(round((point.x/4+.5)*320))%320;iy=int(round((point.y/4+.5)*320))%320;e=epsilon[:,:,ix,iy]
        key=tuple(e[[0,1,2,0,0,1],[0,1,2,1,2,2]])
        if key not in cache:cache[key]=mp.Medium(epsilon_diag=mp.Vector3(*key[:3]),epsilon_offdiag=mp.Vector3(*key[3:]))
        return cache[key]
    material.do_averaging=False
    folder=OUT/job['id'];folder.mkdir(exist_ok=False)
    solver=mpb.ModeSolver(geometry=[],default_material=material,epsilon_input_file='',geometry_lattice=mp.Lattice(size=mp.Vector3(4,4,0)),
        resolution=80,num_bands=4,mesh_size=1,tolerance=job['tolerance'],deterministic=True,optimize_grid_size=True,filename_prefix=str(folder/'unused-'))
    init_count=0;solve_count=0;trace=[];original_init=solver.init_params;original_solve=solver.solve_kpoint
    def init(*a,**kw):
        nonlocal init_count
        init_count+=1;return original_init(*a,**kw)
    def solve(k):
        nonlocal solve_count
        assert solve_count<request['remaining_solves'];solve_count+=1;solver.current_k=k;ret=original_solve(k)
        trace.append({'k_cycles':float(k.z),'frequencies':list(map(float,solver.freqs)),'iterations':int(solver.mode_solver.get_iterations())});return ret
    solver.init_params=init;solver.solve_kpoint=solve
    solver.init_params(mp.NO_PARITY,False)
    setting={'domain_um':[4,4],'resolution':80}
    tensors,_=effective_tensors_after_solve(solver,setting)
    err=float(np.max(abs(tensors['epsilon']-epsilon)));ierr=float(np.max(abs(tensors['inverse_epsilon']-inverse)))
    assert err<1e-12 and ierr<1e-12
    np.savez_compressed(folder/'tensors.npz',**tensors)
    rows=[];selected_band=old['selected_mode']['band']
    def capture(ms,band):
        grid=actual_grid(list(ms.mode_solver.get_dims()),[4,4,0],80,optimized=True)
        E=restore_array(ms.get_efield(band,False),grid,vector=True).copy();H=restore_array(ms.get_hfield(band,False),grid,vector=True).copy()
        energy=restore_array(ms.get_dpwr(band),grid,vector=False).copy();k=float(ms.current_k.z);freq=float(ms.freqs[band-1])
        overlap={key:float(abs(np.vdot(reference[key],arr))**2/(np.vdot(reference[key],reference[key]).real*np.vdot(arr,arr).real)) for key,arr in [('E',E),('H',H)]}
        audit,r=replay(E[:,:,0,:],H[:,:,0,:],tensors['inverse_epsilon'].transpose(2,3,0,1),k,grid['spacing_um'][:2])
        row={'band':band,'frequency_cycles_per_um':freq,'k_cycles_per_um':k,'neff':k*job['wave'],'E_H_identity_overlap_squared':overlap,
            'fixed_material_df_dk':float(ms.compute_one_group_velocity_component(mp.Vector3(0,0,1),band)),**audit}
        if job['kind']=='fixed' or band==selected_band:
            name=f'band-{band}-fields.npz';np.savez_compressed(folder/name,E=E,H=H,electric_energy=energy,x_um=x,y_um=y)
            row['fields_npz']=name;row['fields_sha256']=sha(folder/name)
        if job['kind']=='fixed' and band==selected_band:
            np.savez_compressed(folder/'selected-residual.npz',residual=r)
        rows.append(row)
    if job['kind']=='find':
        mat=dielectric_tensor(job['wave']);upper=max(mat['n_o'],mat['n_e'])*1.01/job['wave']
        roots=solver.find_k(mp.NO_PARITY,1/job['wave'],1,4,mp.Vector3(0,0,1),1e-9,2/job['wave'],.5/job['wave'],upper,capture)
        roots=list(map(float,roots))
    else:
        solver.solve_kpoint(mp.Vector3(0,0,old['selected_mode']['k_cycles_per_um']))
        for band in range(1,5):capture(solver,band)
        roots=None
    selected=next(row for row in rows if row['band']==selected_band)
    for key in ('E','H'):
        assert selected['E_H_identity_overlap_squared'][key]>.98
        assert selected['E_H_identity_overlap_squared'][key]-max(row['E_H_identity_overlap_squared'][key] for row in rows if row['band']!=selected_band)>.05
    result={'job':job,'selected':selected,'all_modes':rows,'roots':roots,'trace':trace,'tensor_error':err,'inverse_tensor_error':ierr,
        'eigenproblem_solves':solve_count,'init_params_calls':init_count,'init_only_precheck':1,'new_find_k':int(job['kind']=='find'),
        'runtime_build':runtime_build_fingerprint(),'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'same_k_spectrum':job['kind']=='fixed','same_k_spectral_gap_certified':False,'continuous_certificate':False,'new_API_calls':0}
    save(folder/'result.json',result)

def execute():
    from photonguard.approved_gui import source_manifest
    plan=read(OUT/'plan.json');assert source_manifest(ROOT)==plan['source'];assert sha(OUT/'frozen_worker.py')==plan['worker_sha256']
    save(OUT/'STARTED.json',{'at':time.time(),'plan_sha256':sha(OUT/'plan.json')})
    lock=OUT/'execution.lock'
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    start=time.monotonic();attempts=[];used=0
    try:
        for job in plan['jobs']:
            assert size()<plan['resources']['output_bytes'] and time.monotonic()-start<1200
            available=int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemAvailable:')))*1024
            assert available>=4*1024**3 and shutil.disk_usage(OUT).free>512*1024**2
            req=OUT/(job['id']+'.request.json');save(req,{'job':job,'plan_sha256':sha(OUT/'plan.json'),'remaining_solves':4-used})
            def limits():
                resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3));resource.setrlimit(resource.RLIMIT_CPU,(300,300))
                resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024**2,32*1024**2));resource.setrlimit(resource.RLIMIT_CORE,(0,0))
            print('Starting '+job['id'],flush=True);t=time.monotonic()
            with (OUT/(job['id']+'.stdout.log')).open('xb') as stdout,(OUT/(job['id']+'.stderr.log')).open('xb') as stderr:
                child=subprocess.Popen([sys.executable,'-B',str(OUT/'frozen_worker.py'),'--worker',str(req)],stdout=stdout,stderr=stderr,preexec_fn=limits)
                peak=0
                while child.poll() is None:
                    try:
                        status=Path(f'/proc/{child.pid}/status').read_text();line=next((s for s in status.splitlines() if s.startswith('VmPeak:')),None)
                        if line:peak=max(peak,int(line.split()[1])*1024)
                    except OSError:pass
                    if size()>plan['resources']['output_bytes']-65536 or time.monotonic()-t>300 or time.monotonic()-start>1200:
                        child.kill();child.wait();raise RuntimeError('RESOURCE_CAP')
                    time.sleep(.2)
            attempts.append({'job':job['id'],'returncode':child.returncode,'seconds':time.monotonic()-t,'VmPeak_bytes':peak})
            assert child.returncode==0,job['id']
            result=read(OUT/job['id']/'result.json');used+=result['eigenproblem_solves'];assert used<=4
            print('Completed '+job['id']+'; total eigenproblems '+str(used),flush=True)
        assert source_manifest(ROOT)==plan['source']
        rows=[]
        for wave in (1.55,.775):
            a=read(OUT.parent/'e1'/f'null-{wave}/result.json');b=read(OUT/f'fixed-{wave}-1e-09/result.json');c=read(OUT/f'fixed-{wave}-1e-12/result.json')
            null_delta=a['selected']['neff']-plan['inputs'][str(wave)]['old_selected']['neff']
            df=c['selected']['frequency_cycles_per_um']-b['selected']['frequency_cycles_per_um'];vg=c['selected']['fixed_material_df_dk']
            dn=-wave*df/vg
            rows.append({'wave':wave,'null_delta_neff':null_delta,'fixed_k_frequency_change':df,'diagnostic_delta_neff_linearized_not_bound':dn,
                'loose_residual':b['selected']['relative_eigen_residual'],'tight_residual':c['selected']['relative_eigen_residual'],
                'same_k_frequencies_loose':[m['frequency_cycles_per_um'] for m in b['all_modes']],
                'same_k_frequencies_tight':[m['frequency_cycles_per_um'] for m in c['all_modes']]})
        coefficient=4*math.pi*1000/1.55
        summary={'status':'COMPLETED_DISCRETE_CONTROLS_NOT_CONTINUOUS_CERTIFICATE','rows':rows,'attempts':attempts,
            'eigenproblem_solves':used,'find_k_calls':0,'prior_find_k_referenced':2,'prior_eigenproblems_including_failed_capture':28,'fixed_k_blocks':4,'explicit_init_only_prechecks':4,
            'null_absolute_phase_change_sum_rad':coefficient*sum(abs(r['null_delta_neff']) for r in rows),
            'tight_tolerance_linearized_absolute_phase_sum_rad_NOT_BOUND':coefficient*sum(abs(r['diagnostic_delta_neff_linearized_not_bound']) for r in rows),
            'seconds':time.monotonic()-start,'output_bytes':size(),'new_API_calls':0,'production_status_unchanged':True,
            'limitations':['same-k gaps are observed floats, not certified intervals','fixed-k frequency change converted using one-point derivative is diagnostic only','no continuous error certificate','local residual fractions are not independent causal attribution']}
        save(OUT/'summary.json',summary);print(json.dumps(summary),flush=True)
    except BaseException as e:
        save(OUT/'STOPPED.json',{'status':'STOPPED_NO_RETRY','error_type':type(e).__name__,'reason':str(e),'attempts':attempts,'used_eigenproblems_from_completed_workers':used})
        raise
    finally:lock.unlink()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--execute',action='store_true');p.add_argument('--worker',type=Path);a=p.parse_args()
    if a.prepare:prepare()
    elif a.execute:execute()
    elif a.worker:worker(read(a.worker))
    else:p.error('Select prepare, execute or worker')
