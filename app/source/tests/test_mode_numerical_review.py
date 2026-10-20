"""Synthetic preregistration, geometry and metadata fixtures, zero solver runs."""
import copy
import numpy as np
import pytest
from photonguard.core import load,digest
from photonguard.mode_numerical_review import make_plan,verify_plan,select_C2,select_C3,continuous_geometry_tensor,POLICY
from photonguard.materials.ln_sellmeier import dielectric_tensor

def context():
    task=load('examples/mode_qpm/ridge.task.json')
    goal={'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':20,'qpm_order':1,'target_phase_factor_min':.8}
    binding={'git_commit':'SYNTHETIC_FIXTURE'}
    plan=make_plan(task,goal,[{'manifest_sha256':'a'*64,'folder':'SYNTHETIC_FIXTURE'}],binding,'b'*64)
    return task,goal,binding,plan

def test_new_window_is_exact_separate_frozen_and_does_not_approve_product():
    task,goal,binding,p=context();verify_plan(p,task,goal,binding)
    assert p['approval']=='REQUIRES_EXACT_PLAN_REVIEW' and p['not_extension_of_exhausted_12_worker_study']
    assert len(p['initializations'])==6 and p['policy']['find_k_workers_max']==8
    assert p['policy']['additional_model_requests']==0 and p['policy']['persistent_output_max_bytes']==64*1024**2
    assert p['physical_requirements_sha256']==digest(task['requirements'])

@pytest.mark.parametrize('mutation',[lambda p:p['qpm_goal'].update(length_um=10),
    lambda p:p['task']['requirements'].update(ridge_width_um=1.5),
    lambda p:p['policy'].update(find_k_workers_max=20),lambda p:p['source_binding'].update(git_commit='OTHER'),
    lambda p:p['initializations'][0].update(mesh_size=1)])
def test_plan_cannot_mutate_physics_goal_resource_source_or_menu(mutation):
    task,goal,binding,p=context();mutation(p)
    with pytest.raises(ValueError):verify_plan(p,task,goal,binding)

@pytest.mark.parametrize('cap,mesh,branch',[(0,0,'tight_tolerance'),(1e-12,0,'tight_tolerance'),
    (2e-12,0,'equivalent_cap'),(2e-12,1,'equivalent_cap'),(0,2e-12,'mesh15')])
def test_C2_priority_is_preregistered_not_selected_for_better_F(cap,mesh,branch):
    assert select_C2(cap,mesh)==branch

def test_missing_or_uncertain_evidence_cannot_choose_an_eigen_branch():
    with pytest.raises(ValueError):select_C2(float('nan'),0)
    with pytest.raises(ValueError):select_C3(True,False,'equivalent_cap',True,True)
    assert select_C3(True,True,'equivalent_cap',True,True)=='half_cell_shift_r120'
    assert select_C3(False,True,'mesh15',False,True)=='tight_tolerance'
    assert select_C3(False,True,'tight_tolerance',False,False) is None

def test_equivalent_cap_matches_at_boundaries_corners_and_interior():
    task,_,_,_=context();r=task['requirements'];material=dielectric_tensor(1.55)
    x=np.array([-.7-1e-10,-.7,-.7+1e-10,0,.7-1e-10,.7,.7+1e-10])
    y=np.array([-.3-1e-10,-.3,-.3+1e-10,-1e-10,0,1e-10,.3-1e-10,.3,.3+1e-10])
    X,Y=np.meshgrid(x,y);points=np.c_[X.ravel(),Y.ravel()]
    assert np.array_equal(continuous_geometry_tensor(points,r,material),
        continuous_geometry_tensor(points,r,material,representation='equivalent_cap'))

def test_translation_changes_position_and_not_width_or_material():
    task,_,_,_=context();r=task['requirements'];material=dielectric_tensor(.775)
    points=np.random.default_rng(42).uniform(-2,2,(2048,2));shift=.00625
    assert np.array_equal(continuous_geometry_tensor(points,r,material),
        continuous_geometry_tensor(points+[shift,0],r,material,shift_x=shift))

def test_worker_uses_actual_grid_and_captures_fixed_material_derivative_without_solver(monkeypatch,tmp_path):
    # Fake ModeSolver; importing the installed module constructs no MPB instance.
    from photonguard.adapters import mpb_worker
    class Backend:
        def get_dims(self):return [320,324]
    class Fake:
        def __init__(self,**kwargs):
            self.mode_solver=Backend();self.optimize_grid_size=True;self.iterations=7
            x=(np.arange(320)/320-.5)*4;y=(np.arange(324)/324-.5)*4.07
            X,Y=np.meshgrid(x,y,indexing='ij');self.energy=np.exp(-12*(X*X+Y*Y))[:,:,None]
        def solve_kpoint(self,*args,**kwargs):pass
        def get_efield(self,band,bloch_phase=False):
            a=np.zeros((320,324,1,3),complex);a[...,0]=np.sqrt(self.energy);return a
        def get_hfield(self,band,bloch_phase=False):return self.get_efield(band,bloch_phase)
        def get_dpwr(self,band):return self.energy
        def compute_one_group_velocity_component(self,direction,band):return .41
        def find_k(self,parity,omega,bmin,bmax,direction,tol,guess,lower,upper,capture):
            roots=[]
            for band in range(1,5):
                self.solve_kpoint();self.current_k=mpb_worker.mp.Vector3(0,0,(2.1-.05*band)/1.55)
                self.freqs=[omega]*4;roots.append(self.current_k.z);capture(self,band)
            return roots
    monkeypatch.setattr(mpb_worker.mpb,'ModeSolver',Fake)
    monkeypatch.setattr(mpb_worker,'runtime_build_fingerprint',lambda:{'kind':'SYNTHETIC_MOCK'})
    r=mpb_worker.solve(1.55,80,[4,4.07],tmp_path,context()[0]['requirements'])
    assert r['all_modes'][0]['field_shape']==[320,324,1,3]
    assert r['all_modes'][0]['actual_grid']['spacing_um'][1]==pytest.approx(4.07/324)
    assert r['all_modes'][0]['fixed_material_df_dk_cycles_per_um_per_cycles_per_um']==.41
    assert r['all_modes'][0]['returned_root_cycles_per_um']==r['roots_cycles_per_um'][0]
    assert r['solver_counts']['eigenproblem_solves']==4

def test_tensor_reader_primes_native_output_before_reading_components(monkeypatch):
    from photonguard.adapters import mpb_research_worker as worker
    from multiprocessing import shared_memory,resource_tracker
    calls=[]
    class Backend:
        primed=False
        def get_dims(self):return [320,320]
        def get_epsilon(self):self.primed=True;calls.append('prime_curfield')
        def get_epsilon_tensor(self,i,j,imag,inv):
            assert self.primed,'Native curfield would be null'
            calls.append('tensor');self.value=0. if i!=j or imag else (1/(4+i) if inv else 4+i)
    class Solver:
        mode_solver=Backend()
        def init_params(self,parity,reset):calls.append('init')
        def get_curfield_as_array(self,bloch):
            assert self.mode_solver.primed;return np.full((320,320),self.mode_solver.value)
    class Memory:
        _name='SYNTHETIC_MOCK';buf=bytearray(2*3*3*320*320*8)
        def close(self):calls.append('close')
    monkeypatch.setattr(shared_memory,'SharedMemory',lambda name:Memory())
    monkeypatch.setattr(resource_tracker,'unregister',lambda *args:None)
    setting={'domain_um':[4,4],'resolution':80}
    result=worker.initialize(Solver(),setting,'SYNTHETIC_MOCK')
    assert calls[:2]==['init','prime_curfield'] and len(result['tensor_components'])==12
    assert result['find_k_invocations']==result['eigenproblem_solves']==0

def test_recovery_preserves_failed_attempt_reservations_and_reduces_scope():
    task,goal,binding,p=context()
    recovery={'carried_initialization_attempts':1,'carried_find_k_attempts':0,
        'reserved_wall_seconds':60,'reserved_output_bytes':4*1024**2,
        'failed_plan_sha256':'a'*64,'original_deadline_utc':'2099-01-01T00:00:00+00:00','scope':'I0_I2_C1_ONLY'}
    value=make_plan(task,goal,p['baselines'],binding,'b'*64,recovery)
    verify_plan(value,task,goal,binding)
    assert len(value['initializations'])==4 and set(value['eigen_stages'])=={'C1'}
    assert value['recovery']['carried_initialization_attempts']==1
    changed=copy.deepcopy(recovery);changed['carried_initialization_attempts']=0
    with pytest.raises(ValueError):make_plan(task,goal,p['baselines'],binding,'b'*64,changed)
    changed=copy.deepcopy(recovery);changed['reserved_output_bytes']=0
    with pytest.raises(ValueError):make_plan(task,goal,p['baselines'],binding,'b'*64,changed)

def test_sparse_operator_difference_cannot_disappear_from_research_thumbnail():
    from tools.review_mode_numerics import tensor_comparison
    first=np.zeros((2,3,3,320,320));second=first.copy()
    second[0,0,0,104,160]=.2;second[0,0,0,216,160]=.3
    r=tensor_comparison(first,second,context()[0]['requirements'])
    assert r['changed_spatial_points']==2 and r['max_abs_difference']==.3
    assert np.max(r['low_resolution_difference_slice'])==.3
    assert {tuple(p['grid_index']) for p in r['largest_changed_cell_locations']}=={(104,160),(216,160)}
