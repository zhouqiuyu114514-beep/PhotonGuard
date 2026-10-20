"""Separate bounded research plan; never extends a product repair or old study."""
import copy,math
from .core import digest
from .adapters import mpb_modes,qpm_phase

POLICY={'version':'pro-numerical-review-window-v1','initialization_processes_max':6,
    'initialization_seconds_each':60,'find_k_workers_max':8,'worker_seconds_each':300,
    'total_wall_seconds':3600,'simultaneous_workers':1,'automatic_retries':0,
    'address_space_max_bytes':2*1024**3,'available_memory_fraction':.5,
    'file_max_bytes':8*1024**2,'persistent_output_max_bytes':64*1024**2,
    'existing_workspace_guard_bytes':1024**3,'additional_model_requests':0,
    'tensor_difference_threshold':1e-12,'per_wave_diagnostic_phase_budget_rad':.01,
    'early_stop_after_C1_if_translation_significant_and_identity_clear':True,
    'never_product_receipt':True,'old_product_and_qpm_policy_unchanged':True}

# A separate, optional research-only output contract. Original product and research
# policies stay frozen; chunks preserve even the previous runner's stricter
# 1 MiB file cap within the 64 MiB envelope.
EVIDENCE_POLICY={'version':'selected-mode-and-effective-tensors-v1',
    'selected_mode_only':True,'all_new_competitor_fields_persisted':False,
    'effective_tensors':'complete_real_epsilon_and_inverse_epsilon',
    'precision':'native_dtype_lossless','compression':'numpy.savez_compressed',
    'file_max_bytes':1024**2,'chunk_raw_max_bytes':768*1024,
    'per_worker_output_max_bytes':28*1024**2,
    'persistent_output_max_bytes':POLICY['persistent_output_max_bytes']}

def _validate_evidence_arrays(fields,tensors,grid):
    import numpy as np
    shape=tuple(grid['shape_xyz'])
    if shape!=(320,320,1):raise ValueError('REVIEW_EVIDENCE_GRID_SCOPE')
    expected={'E':shape+(3,),'H':shape+(3,),'electric_energy':shape,
        'x_um':(shape[0],),'y_um':(shape[1],),
        'epsilon':(3,3,*shape[:2]),'inverse_epsilon':(3,3,*shape[:2])}
    if set(fields)!={'E','H','electric_energy','x_um','y_um'} or set(tensors)!={'epsilon','inverse_epsilon'}:
        raise ValueError('REVIEW_EVIDENCE_KEYS')
    for key,value in {**fields,**tensors}.items():
        a=np.asarray(value)
        if a.shape!=expected[key] or a.dtype.kind not in 'fc' or not np.all(np.isfinite(a)):
            raise ValueError('REVIEW_EVIDENCE_SHAPE_DTYPE_OR_FINITE')
    if any(np.iscomplexobj(tensors[k]) for k in tensors):raise ValueError('REVIEW_EVIDENCE_REAL_TENSORS')
    if np.min(fields['electric_energy'])<0 or np.sum(fields['electric_energy'])<=0:
        raise ValueError('REVIEW_EVIDENCE_RAW_ENERGY')
    for key,length in zip(('x_um','y_um'),grid['lattice_size_um'][:2]):
        axis=np.asarray(fields[key]);expected_axis=(np.arange(len(axis))/len(axis)-.5)*length
        if not np.allclose(axis,expected_axis,rtol=0,atol=1e-12):raise ValueError('REVIEW_EVIDENCE_COORDINATES')
    product=np.einsum('ijxy,jkxy->ikxy',tensors['epsilon'],tensors['inverse_epsilon'])
    error=float(np.max(abs(product-np.eye(3)[:,:,None,None])))
    if error>=1e-10:raise ValueError('REVIEW_EVIDENCE_TENSOR_INVERSE')
    return error

def persist_research_evidence(folder,fields,tensors,grid,selected_band,policy):
    """Save selected fields and complete tensors losslessly, checking before writes.

    Each chunk is a separate archive, so no file requires an exception
    to the original research file cap. Compression runs before committing files;
    the manifest records the exact compressed estimate and actual stored size.
    """
    import hashlib,io,json
    from pathlib import Path
    import numpy as np
    if policy!=EVIDENCE_POLICY:raise ValueError('REVIEW_EVIDENCE_POLICY')
    inverse_error=_validate_evidence_arrays(fields,tensors,grid)
    if type(selected_band) is not int or not 1<=selected_band<=4:raise ValueError('REVIEW_EVIDENCE_SELECTED_BAND')
    arrays={**fields,**tensors};payloads={};records={}
    for key,value in arrays.items():
        arr=np.asarray(value);flat=arr.ravel(order='C');step=policy['chunk_raw_max_bytes']//arr.dtype.itemsize
        chunks=[]
        for index,start in enumerate(range(0,flat.size,step)):
            chunk=flat[start:start+step];stream=io.BytesIO();np.savez_compressed(stream,data=chunk)
            payload=stream.getvalue()
            if len(payload)>policy['file_max_bytes']:raise ValueError('REVIEW_EVIDENCE_FILE_CAP')
            filename=f'{key}-{index:03d}.npz';payloads[filename]=payload
            chunks.append({'filename':filename,'sha256':hashlib.sha256(payload).hexdigest(),
                'offset_elements':start,'elements':chunk.size,
                'compressed_estimate_bytes':len(payload),'stored_bytes':len(payload)})
        stored=sum(c['stored_bytes'] for c in chunks)
        records[key]={'chunks':chunks,'array_sha256':hashlib.sha256(arr.tobytes(order='C')).hexdigest(),
            'shape':list(arr.shape),'dtype':arr.dtype.str,'raw_array_bytes':arr.nbytes,
            'compressed_estimate_bytes':stored,'stored_bytes':stored,
            'compression_ratio_to_raw':stored/arr.nbytes}
    manifest={'schema_version':1,'kind':'RESEARCH_ONLY_LOSSLESS_SELECTED_FIELD_AND_TENSOR_EVIDENCE',
        'policy':copy.deepcopy(policy),'selected_band':selected_band,'actual_grid':copy.deepcopy(grid),
        'files':records,'tensor_axis_order':['row','column','x','y'],
        'field_axis_order':['x','y','z','component'],'tensor_inverse_max_abs_error':inverse_error,
        'arrays_stored_bytes':sum(len(p) for p in payloads.values()),
        'arrays_raw_bytes':sum(a.nbytes for a in arrays.values()),
        'all_new_competitor_fields_persisted':False,
        'independent_replay_scope':'selected new column against all four retained baseline modes; selected tails; complete effective tensors',
        'complete_four_by_four_matrix_independent_replay_available':False,
        'not_product_receipt':True}
    encoded=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    total=manifest['arrays_stored_bytes']+len(encoded)
    if len(encoded)>policy['file_max_bytes'] or total>policy['per_worker_output_max_bytes']:
        raise ValueError('REVIEW_EVIDENCE_OUTPUT_CAP')
    root=Path(folder);root.mkdir(exist_ok=False)
    for filename,payload in {**payloads,'manifest.json':encoded}.items():
        with (root/filename).open('xb') as f:f.write(payload)
    return {'folder':root.name,'manifest_sha256':hashlib.sha256(encoded).hexdigest(),
        'stored_bytes_including_manifest':total,'compressed_estimate_bytes_including_manifest':total,
        'raw_array_bytes':manifest['arrays_raw_bytes'],'maximum_file_bytes':max(map(len,[*payloads.values(),encoded])),
        'selected_band':selected_band,'complete_four_by_four_matrix_independent_replay_available':False}

def load_research_evidence(folder,expected_manifest_sha256=None):
    """Independent no-solver loader with file, array, geometry, and tensor audits."""
    import hashlib,json
    from pathlib import Path
    import numpy as np
    root=Path(folder);encoded=(root/'manifest.json').read_bytes()
    if expected_manifest_sha256 is not None and hashlib.sha256(encoded).hexdigest()!=expected_manifest_sha256:
        raise ValueError('REVIEW_EVIDENCE_MANIFEST_HASH')
    manifest=json.loads(encoded)
    if manifest['policy']!=EVIDENCE_POLICY:raise ValueError('REVIEW_EVIDENCE_POLICY')
    expected={'E','H','electric_energy','x_um','y_um','epsilon','inverse_epsilon'}
    if set(manifest['files'])!=expected:raise ValueError('REVIEW_EVIDENCE_KEYS')
    arrays={};total=len(encoded)
    for key,record in manifest['files'].items():
        parts=[];offset=0;array_stored=0
        for index,chunk in enumerate(record['chunks']):
            if chunk['filename']!=f'{key}-{index:03d}.npz':raise ValueError('REVIEW_EVIDENCE_FILENAME')
            path=root/chunk['filename'];nbytes=path.stat().st_size
            if nbytes>EVIDENCE_POLICY['file_max_bytes'] or nbytes!=chunk['stored_bytes']:
                raise ValueError('REVIEW_EVIDENCE_FILE_SIZE')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=chunk['sha256']:raise ValueError('REVIEW_EVIDENCE_FILE_HASH')
            with np.load(path,allow_pickle=False) as data:
                if data.files!=['data']:raise ValueError('REVIEW_EVIDENCE_ARCHIVE_KEYS')
                part=np.array(data['data'],copy=True)
            if (part.shape!=(chunk['elements'],) or part.dtype.str!=record['dtype']
                or chunk['offset_elements']!=offset or part.nbytes>EVIDENCE_POLICY['chunk_raw_max_bytes']):
                raise ValueError('REVIEW_EVIDENCE_CHUNK_BINDING')
            parts.append(part);offset+=part.size;array_stored+=nbytes
        if not parts or array_stored!=record['stored_bytes']:raise ValueError('REVIEW_EVIDENCE_CHUNK_BINDING')
        arr=np.concatenate(parts).reshape(record['shape'])
        if (list(arr.shape)!=record['shape'] or arr.dtype.str!=record['dtype'] or arr.nbytes!=record['raw_array_bytes']
            or hashlib.sha256(arr.tobytes(order='C')).hexdigest()!=record['array_sha256']):
            raise ValueError('REVIEW_EVIDENCE_ARRAY_BINDING')
        arrays[key]=arr;total+=array_stored
    if total>EVIDENCE_POLICY['per_worker_output_max_bytes']:raise ValueError('REVIEW_EVIDENCE_OUTPUT_CAP')
    fields={k:arrays[k] for k in ('E','H','electric_energy','x_um','y_um')}
    tensors={k:arrays[k] for k in ('epsilon','inverse_epsilon')}
    _validate_evidence_arrays(fields,tensors,manifest['actual_grid'])
    return fields,tensors,manifest

def make_plan(task,goal,baselines,source_binding,pro_package_sha256,recovery=None):
    mpb_modes.validate_task(task)
    if task['provenance'].get('synthetic') is not True:raise ValueError('REVIEW_PUBLIC_SYNTHETIC_ONLY')
    if task['requirements']['wavelengths_um']!=[goal['pump_wavelength_um'],goal['pump_wavelength_um']/2]:
        raise ValueError('REVIEW_WAVELENGTH_GOAL_BINDING')
    if type(baselines) is not list or not baselines:raise ValueError('REVIEW_BASELINE_REQUIRED')
    if any(type(b.get('manifest_sha256')) is not str or len(b['manifest_sha256'])!=64 for b in baselines):
        raise ValueError('REVIEW_BASELINE_HASH')
    # Validate independent goal using schema placeholders, never evaluate them.
    modes=[]
    for w in task['requirements']['wavelengths_um']:
        modes.append({'wavelength_um':w,'neff':2.,'beta_rad_per_um':qpm_phase.beta(w,2.),
            'mode_id':'SCHEMA_ONLY','source_sha256':'0'*64,'source':'SCHEMA_ONLY',
            'verification_status':'IMPORTED_NOT_VERIFIED','neff_sensitivity_estimate':0})
    qpm_phase.validate_task({'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':'SCHEMA_ONLY',
        'requirements':goal,'modes':modes,'provenance':{'reference':'schema validation; not evidence'}})
    if recovery is not None:
        if (type(recovery) is not dict or recovery.get('carried_initialization_attempts')!=1
            or recovery.get('carried_find_k_attempts')!=0 or recovery.get('reserved_wall_seconds')!=60
            or recovery.get('reserved_output_bytes')!=4*1024**2 or not recovery.get('failed_plan_sha256')
            or not recovery.get('original_deadline_utc') or recovery.get('scope')!='I0_I2_C1_ONLY'):
            raise ValueError('REVIEW_RECOVERY_CANNOT_CLEAR_OR_EXPAND_SPENT_RESERVATIONS')
    result={'schema_version':1,'kind':'SEPARATE_NUMERICAL_DIAGNOSTIC_RESEARCH_NOT_PRODUCT',
        'policy':copy.deepcopy(POLICY),'policy_sha256':digest(POLICY),'task':copy.deepcopy(task),
        'task_sha256':digest(task),'physical_requirements_sha256':digest(task['requirements']),
        'qpm_goal':copy.deepcopy(goal),'qpm_goal_sha256':digest(goal),'baselines':copy.deepcopy(baselines),
        'source_binding':copy.deepcopy(source_binding),'source_binding_sha256':digest(source_binding),
        'received_pro_package_sha256':pro_package_sha256,'approval':'REQUIRES_EXACT_PLAN_REVIEW',
        'initializations': [{'id':kind,'wavelength_um':w,'resolution':80,'domain_um':[4,4],
            'mesh_size':mesh,'geometry':geometry,'shift_x_um':0,'eigen_tolerance':1e-9,'root_tolerance':1e-9}
            for kind,mesh,geometry in [('I0',7,'original'),('I1',15,'original'),('I2',7,'equivalent_cap')]
            for w in task['requirements']['wavelengths_um']],
        'eigen_stages':{'C1':'r80 original mesh7 half-cell x translation, two wavelengths',
            'C2':'cap if tensor differs; else mesh15 if tensor differs; else tight tolerance',
            'C3':'r120 translation if C1 significant; else tight tolerance if untested; else remaining tensor branch',
            'C4':'only if still unresolved: r80 original mesh7 domain4x6'},
        'no_convergence_or_success_guarantee':True,'not_extension_of_exhausted_12_worker_study':True}
    if recovery is not None:
        result['recovery']=copy.deepcopy(recovery)
        result['initializations']=[s for s in result['initializations'] if s['id'] in ('I0','I2')]
        result['eigen_stages']={'C1':result['eigen_stages']['C1']}
        result['unexecuted_comparators']=['I1 mesh15','C2','C3','C4']
        result['not_automatic_retry_or_resume']=True
    return result

def verify_plan(plan,task,goal,binding):
    if plan!=make_plan(task,goal,plan['baselines'],binding,plan['received_pro_package_sha256'],plan.get('recovery')):
        raise ValueError('REVIEW_PLAN_OR_PHYSICAL_OR_SOURCE_BINDING')

def select_C2(cap_tensor_delta,mesh_tensor_delta):
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in (cap_tensor_delta,mesh_tensor_delta)):
        raise ValueError('REVIEW_TENSOR_DELTA')
    if cap_tensor_delta>POLICY['tensor_difference_threshold']:return 'equivalent_cap'
    if mesh_tensor_delta>POLICY['tensor_difference_threshold']:return 'mesh15'
    return 'tight_tolerance'

def select_C3(translation_significant,identity_clear,C2_branch,cap_difference,mesh_difference):
    if not identity_clear:raise ValueError('REVIEW_UNCLEAR_IDENTITY_STOP')
    if translation_significant:return 'half_cell_shift_r120'
    if C2_branch!='tight_tolerance':return 'tight_tolerance'
    if cap_difference and C2_branch!='equivalent_cap':return 'equivalent_cap'
    if mesh_difference and C2_branch!='mesh15':return 'mesh15'
    return None

def continuous_geometry_tensor(points,requirements,material,*,representation='original',shift_x=0):
    import numpy as np
    if representation not in ('original','equivalent_cap'):raise ValueError('REVIEW_GEOMETRY_VARIANT')
    p=np.asarray(points,float);x=p[:,0]-shift_x;y=p[:,1]
    film=requirements['film_thickness_um'];slab=requirements['slab_thickness_um'];width=requirements['ridge_width_um']
    tensors=np.tile(np.eye(3)*requirements['top_index']**2,(len(p),1,1))
    tensors[y<-film/2]=np.eye(3)*requirements['bottom_index']**2
    planar=(y>=-film/2)&(y<=-film/2+slab)
    bottom=-film/2 if representation=='original' else -film/2+slab
    ridge=(abs(x)<=width/2)&(y>=bottom)&(y<=film/2)
    tensors[planar|ridge]=material['laboratory_epsilon']
    return tensors
