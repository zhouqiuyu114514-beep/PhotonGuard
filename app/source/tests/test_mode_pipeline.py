"""State/approval boundaries for the opt-in mode workspace; no solver starts."""
import copy
from types import SimpleNamespace
import pytest
from photonguard.workflow import WorkflowStore,WorkflowError
from photonguard.mode_pipeline import ModePipeline

@pytest.fixture
def store(tmp_path):
    result=WorkflowStore(tmp_path/'workspace',allow_workers=True);result.mode_controller=ModePipeline(result)
    yield result
    result.close()

def action(store,state,kind,**data):return store.action(state['id'],{'type':kind,'expected_revision':state['revision'],**data})

def test_missing_geometry_can_be_saved_and_paused_without_filling(store):
    state=store.mode_controller.create_demo();flow=state['adapter_flow'];task=copy.deepcopy(flow['mode_task']);task['requirements']['ridge_width_um']=None
    state=action(store,state,'mode-save',mode_task=task,qpm_goal=flow['qpm_goal'],qpm_source=flow['qpm_source'])
    assert state['adapter_flow']['mode_task']['requirements']['ridge_width_um'] is None
    state=action(store,state,'mode-pause');assert state['adapter_flow']['paused']
    with pytest.raises(WorkflowError):action(store,state,'mode-confirm-run',approve=True,accept_resources=True)
    state=action(store,state,'mode-resume');assert not state['adapter_flow']['paused']
    with pytest.raises(ValueError):action(store,state,'mode-confirm-run',approve=True,accept_resources=True)
    assert not store.get(state['id'])['adapter_flow']['job']

def test_conflicting_wavelengths_and_unsupported_material_cannot_launch(store):
    for change in ('wave','MgO'):
        state=store.mode_controller.create_demo();flow=state['adapter_flow'];task=copy.deepcopy(flow['mode_task'])
        if change=='wave':task['requirements']['wavelengths_um']=[1.55,.8]
        else:task['requirements']['composition']='MgO'
        state=action(store,state,'mode-save',mode_task=task,qpm_goal=flow['qpm_goal'],qpm_source=flow['qpm_source'])
        with pytest.raises(ValueError):action(store,state,'mode-confirm-run',approve=True,accept_resources=True)
        assert not store.get(state['id'])['adapter_flow']['job']

def test_confirm_requires_both_explicit_consents_and_same_resource_contract(store):
    state=store.mode_controller.create_demo()
    with pytest.raises(WorkflowError):action(store,state,'mode-confirm-run',approve=True,accept_resources=False)
    with pytest.raises(WorkflowError):action(store,state,'run')
    with pytest.raises(WorkflowError):action(store,state,'task',task=state['task'])
    with pytest.raises(WorkflowError):action(store,state,'mode-confirm-run',approve=True,accept_resources=True,model_approved=True)

def test_repeat_click_and_version_change_preserve_original_task(store,monkeypatch):
    source={'git_commit':'a'*40,'files':{'owned.py':'b'*64}}
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:source)
    starts=[]
    monkeypatch.setattr('photonguard.mode_pipeline.subprocess.Popen',lambda *a,**k:(starts.append(a) or SimpleNamespace(pid=98765432)))
    state=store.mode_controller.create_demo();raw=store._load(state['id']);raw['development_confirmation']='SIMULATED';store._save(raw);state=store.get(state['id'])
    original_revision=state['revision'];state=action(store,state,'mode-confirm-run',approve=True,accept_resources=True)
    assert len(starts)==1 and state['adapter_flow']['mode_lock']['confirmation_kind']=='SIMULATED'
    with pytest.raises(WorkflowError):store.action(state['id'],{'type':'mode-confirm-run','expected_revision':original_revision,'approve':True,'accept_resources':True})
    with pytest.raises(WorkflowError):action(store,state,'mode-confirm-run',approve=True,accept_resources=True)
    assert len(starts)==1
    # A failed launch/result never renews the task; a deliberate new version is a draft.
    raw=store._load(state['id']);raw['adapter_flow']['job']['status']='failed';raw['adapter_flow']['stage']='FAILED';store._save(raw);state=store.get(state['id'])
    previous=copy.deepcopy(state['adapter_flow']['mode_lock']);child=action(store,state,'mode-new-version',reason='用户资料更新，明确新需求版本')
    assert child['id']!=state['id'] and not child['adapter_flow'].get('mode_lock') and child['parent_version']['case_id']==state['id']
    assert store.get(state['id'])['adapter_flow']['mode_lock']==previous

def test_initial_large_task_stops_before_lock_or_worker_without_loosening_file_caps(store,monkeypatch):
    state=store.mode_controller.create_demo();task=copy.deepcopy(state['adapter_flow']['mode_task']);task['numerics']['resolution']=128
    state=action(store,state,'mode-save',mode_task=task,qpm_goal=state['adapter_flow']['qpm_goal'],qpm_source=state['adapter_flow']['qpm_source'])
    monkeypatch.setattr('photonguard.mode_pipeline.subprocess.Popen',lambda *a,**k:pytest.fail('Oversized initial recipe must not dispatch'))
    with pytest.raises(WorkflowError,match='资源上限'):action(store,state,'mode-confirm-run',approve=True,accept_resources=True)
    final=store.get(state['id']);assert not final['adapter_flow'].get('mode_lock') and not final['adapter_flow']['job']
    assert final['adapter_flow']['mode_task']['numerics']['resolution']==128
