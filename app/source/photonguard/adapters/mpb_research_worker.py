"""Owned bounded research worker; no product receipts or model transport.

Full E/H are computed in RAM. An explicit frozen persistence contract can retain
the selected mode and effective tensors within the original resource limits.
Material initialization uses owner-created shared memory, never an arbitrary code file.
"""
from pathlib import Path
import hashlib,json,sys,time,resource
import numpy as np
import meep as mp
from meep import mpb
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from photonguard.core import digest
from photonguard.materials.ln_sellmeier import dielectric_tensor
from photonguard.mpb_metadata import actual_grid,restore_array,energy_audit,runtime_build_fingerprint
from photonguard.mode_numerical_review import (continuous_geometry_tensor,POLICY,
    EVIDENCE_POLICY,persist_research_evidence)
from photonguard.mode_field_research import load_fields,pair_metrics,common_bulk_weight
from photonguard.approved_gui import source_manifest

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def build_solver(requirements,setting,out):
    wave=setting['wavelength_um'];material=dielectric_tensor(wave)
    tensor=np.asarray(material['laboratory_epsilon'])
    crystal=mp.Medium(epsilon_diag=mp.Vector3(*np.diag(tensor)),
        epsilon_offdiag=mp.Vector3(tensor[0,1],tensor[0,2],tensor[1,2]))
    sx,sy=setting['domain_um'];film=requirements['film_thickness_um'];slab=requirements['slab_thickness_um'];width=requirements['ridge_width_um']
    geometry=[mp.Block(size=mp.Vector3(mp.inf,sy/2-film/2,mp.inf),center=mp.Vector3(0,-sy/4-film/4,0),material=mp.Medium(index=requirements['bottom_index'])),
        mp.Block(size=mp.Vector3(mp.inf,slab,mp.inf),center=mp.Vector3(0,-film/2+slab/2,0),material=crystal)]
    height=film if setting['geometry']=='original' else film-slab
    center=0 if setting['geometry']=='original' else slab/2
    geometry.append(mp.Block(size=mp.Vector3(width,height,mp.inf),center=mp.Vector3(setting['shift_x_um'],center,0),material=crystal))
    solver=mpb.ModeSolver(geometry_lattice=mp.Lattice(size=mp.Vector3(sx,sy,0)),geometry=geometry,
        default_material=mp.Medium(index=requirements['top_index']),resolution=setting['resolution'],num_bands=4,
        tolerance=setting['eigen_tolerance'],deterministic=True,mesh_size=setting['mesh_size'],
        optimize_grid_size=True,filename_prefix=str(out/'research-'))
    return solver,material

def initialize(solver,setting,shm_name):
    from multiprocessing import shared_memory,resource_tracker
    solver.init_params(mp.NO_PARITY,False)
    # Native get_epsilon_tensor writes fft_data but does not set curfield.
    # Match official output_epsilon: initialize the output buffer first.
    # Its visualization scalar is deliberately discarded, never called epsilon_xx.
    solver.mode_solver.get_epsilon()
    grid=actual_grid(list(solver.mode_solver.get_dims()),[*setting['domain_um'],0],setting['resolution'],optimized=True)
    nx,ny,nz=grid['shape_xyz']
    if (nx,ny,nz)!=(320,320,1):raise ValueError('REVIEW_INIT_SHARED_GRID_MISMATCH')
    shm=shared_memory.SharedMemory(name=shm_name)
    # This child has its own tracker; only the parent owns/unlinks this segment.
    resource_tracker.unregister(shm._name,'shared_memory')
    planes=np.ndarray((2,3,3,nx,ny),dtype=np.float64,buffer=shm.buf);summaries=[]
    try:
        for inv in (False,True):
            for i in range(3):
                for j in range(i,3):
                    solver.mode_solver.get_epsilon_tensor(i,j,0,inv)
                    raw=np.asarray(solver.get_curfield_as_array(False))
                    arr=restore_array(raw,grid,vector=False)[:,:,0]
                    planes[int(inv),i,j]=arr;planes[int(inv),j,i]=arr
                    imaginary_max=0.
                    if mpb.with_hermitian_epsilon() and i!=j:
                        solver.mode_solver.get_epsilon_tensor(i,j,1,inv)
                        imag=restore_array(solver.get_curfield_as_array(False),grid,vector=False)[:,:,0]
                        imaginary_max=float(np.max(abs(imag)))
                        if imaginary_max>1e-12:raise ValueError('REVIEW_REAL_TENSOR_ASSUMPTION')
                    summaries.append({'inverse':inv,'component':str(i)+str(j),'sha256':hashlib.sha256(arr.tobytes()).hexdigest(),
                        'minimum':float(arr.min()),'maximum':float(arr.max()),
                        'integral_um2':float(arr.sum()*np.prod(grid['spacing_um'][:2])),
                        'imaginary_max_abs':imaginary_max})
    finally:del planes;shm.close()
    return {'actual_grid':grid,'tensor_components':summaries,'find_k_invocations':0,
        'eigenproblem_solves':0,'only_material_initialization':True,'full_arrays_persisted':False}

def effective_tensors_after_solve(solver,setting):
    """Read the existing solver's real effective tensor; never initializes again."""
    solver.mode_solver.get_epsilon()
    grid=actual_grid(list(solver.mode_solver.get_dims()),[*setting['domain_um'],0],setting['resolution'],optimized=True)
    nx,ny,nz=grid['shape_xyz']
    if (nx,ny,nz)!=(320,320,1):raise ValueError('REVIEW_EVIDENCE_GRID_SCOPE')
    values=np.empty((2,3,3,nx,ny),dtype=np.float64);summaries=[]
    for inv in (False,True):
        for i in range(3):
            for j in range(i,3):
                solver.mode_solver.get_epsilon_tensor(i,j,0,inv)
                arr=restore_array(solver.get_curfield_as_array(False),grid,vector=False)[:,:,0].copy()
                values[int(inv),i,j]=arr;values[int(inv),j,i]=arr
                imaginary_max=0.
                if mpb.with_hermitian_epsilon() and i!=j:
                    solver.mode_solver.get_epsilon_tensor(i,j,1,inv)
                    imag=restore_array(solver.get_curfield_as_array(False),grid,vector=False)[:,:,0]
                    imaginary_max=float(np.max(abs(imag)))
                    if imaginary_max>1e-12:raise ValueError('REVIEW_REAL_TENSOR_ASSUMPTION')
                summaries.append({'inverse':inv,'component':str(i)+str(j),
                    'sha256':hashlib.sha256(arr.tobytes()).hexdigest(),
                    'minimum':float(arr.min()),'maximum':float(arr.max()),
                    'integral_um2':float(arr.sum()*np.prod(grid['spacing_um'][:2])),
                    'imaginary_max_abs':imaginary_max})
    return {'epsilon':values[0],'inverse_epsilon':values[1]},summaries

def solve_research(solver,requirements,setting,material,baseline,*,evidence_out=None,evidence_policy=None):
    root=Path(baseline['folder']);old=json.loads((root/'result.json').read_text())
    old_fields={m['band']:load_fields(root/m['fields_npz']) for m in old['all_modes']}
    modes=[];matrix=[];counts={'eigenproblem_solves':0};original=solver.solve_kpoint
    retained=None;retained_neff=-np.inf
    def candidate(m):
        return (m['electric_component_L2_fraction'][0]>.55 and m['neff']>1.44
            and m['ridge_rectangle_energy_fraction']>.35 and m['outer_cell_energy_fraction']<.05)
    def counted(*a,**kw):counts['eigenproblem_solves']+=1;return original(*a,**kw)
    solver.solve_kpoint=counted;wave=setting['wavelength_um']
    def capture(ms,band):
        nonlocal retained,retained_neff
        grid=actual_grid(list(ms.mode_solver.get_dims()),[*setting['domain_um'],0],setting['resolution'],optimized=True)
        nx,ny,nz=grid['shape_xyz'];sx,sy=setting['domain_um']
        E=restore_array(ms.get_efield(band,False),grid,vector=True)
        H=restore_array(ms.get_hfield(band,False),grid,vector=True)
        energy=restore_array(ms.get_dpwr(band),grid,vector=False);ea=energy_audit(energy)
        if ea['minimum']<0 or ea['raw_sum']<=0:raise ValueError('REVIEW_RAW_DPWR_INVALID')
        x=(np.arange(nx)/nx-.5)*sx;y=(np.arange(ny)/ny-.5)*sy;X,Y=np.meshgrid(x,y,indexing='ij')
        core=(abs(X-setting['shift_x_um'])<=requirements['ridge_width_um']/2)&(abs(Y)<=requirements['film_thickness_um']/2)
        outer=(abs(X)>.45*sx)|(abs(Y)>.45*sy);density=energy[:,:,0]
        fractions=np.sum(abs(E)**2,axis=(0,1,2));fractions/=fractions.sum()
        mode={'band':band,'frequency_cycles_per_um':float(ms.freqs[band-1]),'k_cycles_per_um':float(ms.current_k.z),
            'neff':float(ms.current_k.z*wave),'electric_component_L2_fraction':fractions.tolist(),
            'ridge_rectangle_energy_fraction':float(density[core].sum()/density.sum()),
            'outer_cell_energy_fraction':float(density[outer].sum()/density.sum()),'actual_grid':grid,
            'raw_energy_audit':ea,'fixed_material_df_dk':float(ms.compute_one_group_velocity_component(mp.Vector3(0,0,1),band)),
            'not_material_dispersive_group_velocity':True,'field_shape':list(E.shape),
            'field_hashes_not_replayable_without_arrays':{k:hashlib.sha256(a.tobytes()).hexdigest() for k,a in [('E',E),('H',H)]}}
        new={'E':E,'H':H,'electric_energy':energy,'x_um':x,'y_um':y}
        for old_band,first in old_fields.items():
            weight=common_bulk_weight(first['x_um'],first['y_um'],requirements,material)
            matrix.append({'old_band':old_band,'new_band':band,
                **pair_metrics(first,new,weight=weight,shift_um=(setting['shift_x_um'],0))})
        if evidence_out is not None and candidate(mode) and mode['neff']>retained_neff:
            # Native output buffers can be reused by later bands or tensor reads.
            retained={k:np.array(v,copy=True) for k,v in new.items()};retained_neff=mode['neff']
        modes.append(mode)
    upper=max(material['n_o'],material['n_e'])*1.01/wave
    roots=solver.find_k(mp.NO_PARITY,1/wave,1,4,mp.Vector3(0,0,1),setting['root_tolerance'],2/wave,.5/wave,upper,capture)
    for m in modes:m['returned_root_cycles_per_um']=float(roots[m['band']-1])
    candidates=[m for m in modes if candidate(m)]
    selected=max(candidates,key=lambda m:m['neff']) if candidates else None
    if selected is None:raise ValueError('REVIEW_NO_MODE_CANDIDATE')
    a=old['selected_mode']['band'];b=selected['band']
    same=[r for r in matrix if r['old_band']==a];choice=next(r for r in same if r['new_band']==b)
    identity={}
    for key in ('E_L2_overlap_research','H_L2_overlap_research'):
        chosen=choice['metrics'][key]['squared_normalized_overlap']
        alternatives=[r['metrics'][key]['squared_normalized_overlap'] for r in same if r['new_band']!=b]
        identity[key]={'selected':chosen,'margin':chosen-max(alternatives,default=0)}
    clear=all(v['selected']>=.98 and v['margin']>=.05 for v in identity.values())
    if max(abs(m['frequency_cycles_per_um']-1/wave) for m in modes)>1e-7:clear=False
    result={'roots_cycles_per_um':list(map(float,roots)),'all_modes':modes,'selected_mode':selected,
        'old_selected_mode':old['selected_mode'],'full_four_by_four_E_H_research_matrix':matrix,
        'selected_identity':identity,'identity_clear_within_four_bands':clear,
        'field_arrays_persisted':False,'full_field_posthoc_replay_not_available':True,
        'old_result_sha256':sha(root/'result.json'),
        'old_field_files':[{'path':str(root/m['fields_npz']),'sha256':sha(root/m['fields_npz'])} for m in old['all_modes']],
        'solver_counts':{'find_k_invocations':1,'eigenproblem_solves':counts['eigenproblem_solves'],'fdtd_runs':0}}
    if evidence_out is not None:
        if retained is None:raise ValueError('REVIEW_EVIDENCE_SELECTED_FIELDS_MISSING')
        tensors,summaries=effective_tensors_after_solve(solver,setting)
        persisted=persist_research_evidence(evidence_out,retained,tensors,selected['actual_grid'],selected['band'],evidence_policy)
        selected['field_hashes']=selected.pop('field_hashes_not_replayable_without_arrays')
        selected['persisted_evidence_folder']=persisted['folder']
        result.update(persisted_evidence=persisted,effective_tensor_components=summaries,
            field_arrays_persisted=True,selected_field_arrays_persisted=True,
            all_new_competitor_field_arrays_persisted=False,
            full_field_posthoc_replay_not_available=False,
            full_four_by_four_matrix_posthoc_replay_available=False,
            independent_replay_scope='selected new column and complete effective tensors only',
            extra_material_initializations_for_persistence=0)
    return result

def main():
    req=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);out.mkdir(exist_ok=False)
    setting=req['setting'];task=req['plan']['task'];policy=req['plan']['policy']
    if policy!=POLICY or digest(task['requirements'])!=req['plan']['physical_requirements_sha256']:
        raise ValueError('REVIEW_WORKER_PLAN_SCOPE')
    if source_manifest(Path(__file__).resolve().parents[2])!=req['plan']['source_binding']:
        raise ValueError('REVIEW_WORKER_SOURCE_BINDING_CHANGED')
    if digest(req['plan']['qpm_goal'])!=req['plan']['qpm_goal_sha256']:
        raise ValueError('REVIEW_WORKER_GOAL_BINDING_CHANGED')
    if req['kind']=='initialize' and setting not in req['plan']['initializations']:
        raise ValueError('REVIEW_WORKER_INITIALIZATION_NOT_PREREGISTERED')
    persist=req.get('persist_evidence',False)
    if type(persist) is not bool:raise ValueError('REVIEW_WORKER_PERSISTENCE_FLAG')
    if persist and (req['kind']!='find_k' or req['plan'].get('evidence_persistence')!=EVIDENCE_POLICY
        or setting not in req['plan'].get('find_k_settings',[])):
        raise ValueError('REVIEW_WORKER_PERSISTENCE_NOT_PREREGISTERED')
    if req['plan'].get('kind')=='EQUIVALENT_CAP_TWO_WORKER_RESEARCH':
        if req['kind']!='find_k' or persist is not True or setting not in req['plan']['find_k_settings']:
            raise ValueError('REVIEW_WORKER_CAP_EXACT_SCOPE')
        parent=Path(req['plan']['baseline']['folder'])
        expected=parent/('base-'+str(setting['wavelength_um']))
        if req.get('baseline')!={'folder':str(expected)}:
            raise ValueError('REVIEW_WORKER_CAP_BASELINE_BINDING')
        if sha(parent/'manifest.json')!=req['plan']['baseline']['manifest_sha256']:
            raise ValueError('REVIEW_WORKER_CAP_BASELINE_MANIFEST')
        expected_files=req['plan']['old_manifest_files']
        if json.loads((parent/'manifest.json').read_text())['files']!=expected_files:
            raise ValueError('REVIEW_WORKER_CAP_BASELINE_MANIFEST')
        old=json.loads((expected/'result.json').read_text())
        for path in [expected/'result.json',*[expected/m['fields_npz'] for m in old['all_modes']]]:
            if not path.resolve().is_relative_to(expected.resolve()):raise ValueError('REVIEW_WORKER_CAP_BASELINE_PATH')
            if sha(path)!=expected_files.get(str(path.relative_to(parent))):
                raise ValueError('REVIEW_WORKER_CAP_BASELINE_FILE')
    assert setting['geometry'] in ('original','equivalent_cap') and setting['mesh_size'] in (7,15)
    assert setting['resolution'] in (80,120) and setting['domain_um'] in ([4,4],[4,6])
    assert setting['wavelength_um'] in task['requirements']['wavelengths_um']
    assert setting['shift_x_um'] in (0.,.5/setting['resolution'])
    assert setting['eigen_tolerance'] in (1e-9,1e-11) and setting['root_tolerance'] in (1e-9,1e-11)
    started=time.monotonic();solver,material=build_solver(task['requirements'],setting,out)
    if req['kind']=='initialize':result=initialize(solver,setting,req['shared_memory_name'])
    elif req['kind']=='find_k':result=solve_research(solver,task['requirements'],setting,material,req['baseline'],
        evidence_out=out/'evidence' if persist else None,
        evidence_policy=req['plan'].get('evidence_persistence') if persist else None)
    else:raise ValueError('REVIEW_WORKER_KIND')
    result.update(kind='RESEARCH_ONLY_NOT_PRODUCT_RECEIPT',setting=setting,
        physical_requirements_sha256=req['plan']['physical_requirements_sha256'],qpm_goal_sha256=req['plan']['qpm_goal_sha256'],
        material=material,runtime_build=runtime_build_fingerprint(),wall_seconds=time.monotonic()-started,
        peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,model_requests=0,
        original_qpm_status_unchanged='INCONCLUSIVE',original_design_goal_status='NOT_EVALUATED')
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
