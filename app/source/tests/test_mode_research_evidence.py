"""Lossless bounded research evidence fixtures; never construct a real solver."""
import copy
import hashlib
import json
import numpy as np
import pytest

from photonguard import mode_numerical_review as review
from photonguard.mpb_metadata import actual_grid


@pytest.fixture
def evidence():
    grid=actual_grid([320,320],[4,4,0],80,optimized=True)
    x=(np.arange(320)/320-.5)*4;y=x.copy()
    X,Y=np.meshgrid(x,y,indexing='ij');energy=np.exp(-24*(X*X+Y*Y))[:,:,None]
    E=np.zeros((320,320,1,3),complex);E[...,0]=np.sqrt(energy)
    H=np.zeros_like(E);H[...,1]=np.sqrt(energy)*1j
    fields={'E':E,'H':H,'electric_energy':energy,'x_um':x,'y_um':y}
    eps=np.zeros((3,3,320,320));inverse=np.zeros_like(eps)
    for i in range(3):eps[i,i]=4+i;inverse[i,i]=1/(4+i)
    return fields,{'epsilon':eps,'inverse_epsilon':inverse},grid


def test_selected_fields_and_complete_tensor_roundtrip_preserves_exact_complex_values(tmp_path,evidence):
    fields,tensors,grid=evidence
    result=review.persist_research_evidence(tmp_path/'evidence',fields,tensors,grid,1,review.EVIDENCE_POLICY)
    loaded,loaded_tensors,manifest=review.load_research_evidence(tmp_path/'evidence',result['manifest_sha256'])
    for key in fields:assert np.array_equal(loaded[key],fields[key])
    for key in tensors:assert np.array_equal(loaded_tensors[key],tensors[key])
    assert manifest['complete_four_by_four_matrix_independent_replay_available'] is False
    assert manifest['arrays_raw_bytes']<28*1024**2
    paths=list((tmp_path/'evidence').iterdir())
    assert max(p.stat().st_size for p in paths)<=1024**2
    assert sum(p.stat().st_size for p in paths)==result['stored_bytes_including_manifest']
    assert result['compressed_estimate_bytes_including_manifest']==result['stored_bytes_including_manifest']
    with pytest.raises(FileExistsError):
        review.persist_research_evidence(tmp_path/'evidence',fields,tensors,grid,1,review.EVIDENCE_POLICY)


@pytest.mark.parametrize('mutation,error',[
    ('nan','SHAPE_DTYPE_OR_FINITE'),('inverse','TENSOR_INVERSE'),('axis','COORDINATES'),
    ('negative_energy','RAW_ENERGY'),('missing_field','KEYS')])
def test_invalid_evidence_fails_before_any_files_are_written(tmp_path,evidence,mutation,error):
    fields,tensors,grid=evidence
    if mutation=='nan':fields['E'][0,0,0,0]=np.nan
    elif mutation=='inverse':tensors['inverse_epsilon'][0,0,0,0]=0
    elif mutation=='axis':fields['x_um'][0]+=.001
    elif mutation=='negative_energy':fields['electric_energy'][0,0,0]=-1
    elif mutation=='missing_field':del fields['H']
    with pytest.raises(ValueError,match=error):
        review.persist_research_evidence(tmp_path/'evidence',fields,tensors,grid,1,review.EVIDENCE_POLICY)
    assert not (tmp_path/'evidence').exists()


@pytest.mark.parametrize('limit',['file_max_bytes','per_worker_output_max_bytes'])
def test_compressed_estimate_enforces_file_and_total_caps_before_commit(tmp_path,evidence,monkeypatch,limit):
    fields,tensors,grid=evidence
    policy=copy.deepcopy(review.EVIDENCE_POLICY);policy[limit]=100
    monkeypatch.setattr(review,'EVIDENCE_POLICY',policy)
    with pytest.raises(ValueError,match='CAP'):
        review.persist_research_evidence(tmp_path/'evidence',fields,tensors,grid,1,policy)
    assert not (tmp_path/'evidence').exists()


def test_loader_detects_archive_and_manifest_tampering(tmp_path,evidence):
    fields,tensors,grid=evidence
    result=review.persist_research_evidence(tmp_path/'evidence',fields,tensors,grid,1,review.EVIDENCE_POLICY)
    with pytest.raises(ValueError,match='MANIFEST_HASH'):
        review.load_research_evidence(tmp_path/'evidence','0'*64)
    path=tmp_path/'evidence'/'E-000.npz';data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
    with pytest.raises(ValueError,match='FILE_HASH'):
        review.load_research_evidence(tmp_path/'evidence',result['manifest_sha256'])


@pytest.mark.parametrize('mutation,error',[
    ('disable_persistence','CAP_EXACT_SCOPE'),
    ('foreign_setting','PERSISTENCE_NOT_PREREGISTERED'),
    ('foreign_baseline','CAP_BASELINE_BINDING')])
def test_cap_worker_cannot_bypass_frozen_evidence_settings_or_baseline(tmp_path,monkeypatch,mutation,error):
    from photonguard.adapters import mpb_research_worker as worker
    from photonguard.core import digest
    task={'requirements':{}};goal={'synthetic_fixture':True};binding={'synthetic_fixture':True}
    setting={'wavelength_um':1.55}
    plan={'kind':'EQUIVALENT_CAP_TWO_WORKER_RESEARCH','task':task,'policy':review.POLICY,
        'physical_requirements_sha256':digest(task['requirements']),
        'qpm_goal':goal,'qpm_goal_sha256':digest(goal),'source_binding':binding,
        'find_k_settings':[setting],'baseline':{'folder':str(tmp_path/'baseline')},
        'evidence_persistence':review.EVIDENCE_POLICY}
    request={'kind':'find_k','setting':copy.deepcopy(setting),'plan':plan,'persist_evidence':True,
        'baseline':{'folder':str(tmp_path/'baseline'/'base-1.55')}}
    if mutation=='disable_persistence':request['persist_evidence']=False
    if mutation=='foreign_setting':request['setting']['wavelength_um']=.775
    if mutation=='foreign_baseline':request['baseline']['folder']=str(tmp_path/'foreign')
    path=tmp_path/'request.json';path.write_text(json.dumps(request))
    monkeypatch.setattr(worker.sys,'argv',['worker',str(path),str(tmp_path/'out')])
    monkeypatch.setattr(worker,'source_manifest',lambda root:binding)
    def forbidden(*args):raise AssertionError('Invalid request must not construct a solver')
    monkeypatch.setattr(worker,'build_solver',forbidden)
    with pytest.raises(ValueError,match=error):worker.main()


def test_mock_worker_persists_selected_fields_and_reads_tensors_without_extra_initialization(tmp_path,evidence,monkeypatch):
    from photonguard.adapters import mpb_research_worker as worker
    from photonguard.core import load
    from photonguard.materials.ln_sellmeier import dielectric_tensor
    from photonguard.mode_field_research import pair_metrics,common_bulk_weight
    fields,tensors,grid=evidence
    requirements=load('examples/mode_qpm/ridge.task.json')['requirements'];material=dielectric_tensor(1.55)
    setting={'wavelength_um':1.55,'domain_um':[4,4],'resolution':80,'shift_x_um':0,'root_tolerance':1e-9}
    baseline=tmp_path/'baseline';baseline.mkdir()
    old={'all_modes':[{'band':band,'fields_npz':f'field-{band}.npz'} for band in range(1,5)],
         'selected_mode':{'band':1,'neff':2.1}}
    (baseline/'result.json').write_text(json.dumps(old))
    for mode in old['all_modes']:(baseline/mode['fields_npz']).write_bytes(b'SYNTHETIC_ONLY')
    def mode_fields(band):
        values={k:np.array(v,copy=True) for k,v in fields.items()}
        if band in (2,3):
            values['E']=np.roll(values['E'],band-1,axis=-1)
            values['H']=np.roll(values['H'],band-1,axis=-1)
        if band==4:
            for key in ('E','H'):values[key]*=fields['x_um'][:,None,None,None]
        return values
    monkeypatch.setattr(worker,'load_fields',lambda path:mode_fields(int(path.stem.split('-')[-1])))
    calls=[]
    class Backend:
        def get_dims(self):return [320,320]
        def get_epsilon(self):calls.append('tensor_after_find_k');solver.shared_E.fill(77)
        def get_epsilon_tensor(self,i,j,imag,inv):
            assert calls and calls[-1]=='tensor_after_find_k'
            self.value=0. if imag else tensors['inverse_epsilon' if inv else 'epsilon'][i,j,0,0]
    class Fake:
        mode_solver=Backend()
        shared_E=np.zeros_like(fields['E']);shared_H=np.zeros_like(fields['H'])
        def init_params(self,*args):raise AssertionError('No extra material initialization allowed')
        def solve_kpoint(self,*args):calls.append('solve_kpoint')
        def get_efield(self,band,bloch):self.shared_E[:]=mode_fields(band)['E'];return self.shared_E
        def get_hfield(self,band,bloch):self.shared_H[:]=mode_fields(band)['H'];return self.shared_H
        def get_dpwr(self,band):return fields['electric_energy']
        def compute_one_group_velocity_component(self,*args):return .4
        def get_curfield_as_array(self,bloch):return np.full((320,320),self.mode_solver.value)
        def find_k(self,parity,omega,first,last,direction,tol,guess,lower,upper,capture):
            roots=[]
            for band in range(1,5):
                self.solve_kpoint();self.current_k=worker.mp.Vector3(0,0,(2.2-.1*band)/1.55)
                self.freqs=[omega]*4;roots.append(self.current_k.z);capture(self,band)
            calls.append('find_k_completed');return roots
    solver=Fake()
    result=worker.solve_research(solver,requirements,setting,material,{'folder':str(baseline)},
        evidence_out=tmp_path/'evidence',evidence_policy=review.EVIDENCE_POLICY)
    assert calls[-2:]==['find_k_completed','tensor_after_find_k']
    assert result['solver_counts']=={'find_k_invocations':1,'eigenproblem_solves':4,'fdtd_runs':0}
    assert result['selected_mode']['band']==1 and result['identity_clear_within_four_bands']
    assert result['field_arrays_persisted'] and not result['full_four_by_four_matrix_posthoc_replay_available']
    saved,saved_tensors,manifest=review.load_research_evidence(tmp_path/'evidence',result['persisted_evidence']['manifest_sha256'])
    assert np.array_equal(saved['E'],fields['E']) and np.array_equal(saved['H'],fields['H'])
    assert len(result['effective_tensor_components'])==12
    for item in result['effective_tensor_components']:
        i,j=map(int,item['component']);array=saved_tensors['inverse_epsilon' if item['inverse'] else 'epsilon'][i,j]
        assert item['sha256']==hashlib.sha256(array.tobytes()).hexdigest()
    # Recompute every retained column entry using only baseline and stored files.
    for row in result['full_four_by_four_E_H_research_matrix']:
        if row['new_band']==1:
            first=mode_fields(row['old_band'])
            weight=common_bulk_weight(first['x_um'],first['y_um'],requirements,material)
            computed=pair_metrics(first,saved,weight=weight)
            assert computed=={k:v for k,v in row.items() if k not in ('old_band','new_band')}
