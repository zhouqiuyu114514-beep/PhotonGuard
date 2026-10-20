from datetime import datetime,timezone
from decimal import Decimal
import json
import pytest
from photonguard.novice import draft,TEMPLATE_TEXT
from photonguard.workflow import WorkflowStore,WorkflowError
from photonguard.service_identity import require_match
from photonguard.product_phase import initialize,ProductLedger

def test_template_and_unknowns():
    d=draft('a'*32,'teaching','');assert d['ready'] and not d['approval']
    assert d['task']['nfreq']==41 and d['task']['layers'][0]['thickness_um']==.3
    assert 'frequencies_for_monitors' in d['source']
    missing=draft('b'*32,'specified',TEMPLATE_TEXT.replace('膜厚为300 nm。',''))
    assert not missing['ready'] and any(x['field']=='film_thickness' for x in missing['missing'])
    conflict=draft('c'*32,'specified',TEMPLATE_TEXT+'\n膜厚为400 nm。')
    assert not conflict['ready'] and any(x['status']=='conflict' for x in conflict['missing'])

def test_simulated_confirmation_cannot_run(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=False)
    try:
        store.simulation_context={'actor_type':'SIMULATED','scenario_id':'D08','max_solver_calls':0}
        s=store.create('novice-teaching');assert s['actor_type']=='SIMULATED'
        with pytest.raises(WorkflowError,match='禁止新求解'):
            store.action(s['id'],{'type':'novice-start','expected_revision':s['revision'],'approve':True,'plan_sha256':s['novice']['plan_sha256']})
        assert store.get(s['id'])['approval'] is None
    finally:store.close()

def test_phase_carry_settle_and_old_change_guard(tmp_path):
    old=tmp_path/'old.json';carried={'schema_version':3,'approval_sha256':'old','attempts':37,'live_provider_attempts':37,'settled_usd':'.6','settled_cny':'4.000000000001','reserved_usd':'.6','reserved_cny':'4.000000000001','pending':None,'halted':False}
    old.write_text(json.dumps(carried));original=old.read_bytes()
    folder=tmp_path/'new';initialize(folder,old,datetime.now(timezone.utc).isoformat());l=ProductLedger(folder)
    p=l.reserve_worst(True);assert p['attempts']==38
    with pytest.raises(ValueError):l.reserve_worst(True)
    s=l.settle_usage(p['pending']['id'],{'prompt_tokens':1000,'completion_tokens':500,'total_tokens':1500})
    assert Decimal('.006')<=Decimal(s['reserved_cny'])-Decimal(carried['reserved_cny'])<=Decimal('.006000000001')
    assert old.read_bytes()==original
    old.write_text('{}')
    with pytest.raises(ValueError,match='Previous ledger changed'):l.reserve_worst(True)

def test_service_identity_is_exact():
    require_match({'mode':'RULES_ONLY'},{'service_identity':{'mode':'RULES_ONLY'}})
    with pytest.raises(ValueError):require_match({'mode':'LIVE'}, {'service_identity':{'mode':'RULES_ONLY'}})

def test_unknown_status_feedback_does_not_repair_model_output():
    from photonguard import workflow_intake as i
    from photonguard.novice_ai import review
    v=i.prepare('missing-upper',i.DEMO.replace('真空波长上界为1700 nm。',''))['view']
    candidate=i.rule_candidate(v);candidate['review_status']='REVIEW_REQUIRED'
    result=review(v,json.dumps(candidate))
    assert not result['accepted'] and result['reason_code']=='SEMANTIC_STATUS_UNRESOLVED'
    assert 'CLARIFICATION_REQUIRED' in result['hint']
    assert candidate['review_status']=='REVIEW_REQUIRED'

def test_explicit_novice_plan_reaches_existing_lock_without_running_worker(tmp_path):
    from photonguard.repair_pipeline import ThreeStepPipeline
    store=WorkflowStore(tmp_path,allow_workers=False);launched=[]
    try:
        store.allow_workers=True;store.meep_available=True
        controller=ThreeStepPipeline(store);store.pipeline_controller=controller
        controller.launch=lambda ident,phase:launched.append((ident,phase))
        s=store.create('novice-teaching')
        payload={'type':'novice-start','expected_revision':s['revision'],'approve':True,'plan_sha256':s['novice']['plan_sha256']}
        s=store.action(s['id'],payload)
        assert s['approval'] and s['candidate'] and launched==[(s['id'],'initial')]
        assert s['runs']==[] and not s['job']
        with pytest.raises(WorkflowError):store.action(s['id'],payload)
        assert len(launched)==1
    finally:store.close()

def test_unknown_cost_remains_fully_occupied_without_reset_or_retry(tmp_path):
    from photonguard.product_phase import retain_unknown_reservation
    old=tmp_path/'previous.json';old.write_text(json.dumps({'attempts':37,'live_provider_attempts':37,'settled_usd':'.6','settled_cny':'4.000000000001','reserved_usd':'.6','reserved_cny':'4.000000000001','pending':None,'halted':False}))
    folder=tmp_path/'phase';initialize(folder,old,datetime.now(timezone.utc).isoformat());l=ProductLedger(folder)
    reservation=l.reserve_worst(True);l.halt();closed=l.path.read_bytes()
    failure=tmp_path/'failure.json';failure.write_text(json.dumps({'audit':{'status':'TRANSPORT_FAILURE','budget':reservation,'usage':None,'request_sha256':'f'*64}}))
    carried=retain_unknown_reservation(folder,failure);next_l=ProductLedger(folder)
    assert l.path.read_bytes()==closed and carried['attempts']==38
    assert carried['reserved_cny']==reservation['reserved_cny']
    assert carried['settled_cny']==reservation['reserved_cny']
    assert next_l.cny.total_budget_cny==l.cny.total_budget_cny
    assert next_l.epoch['held_unknown_requests'][0]['request_sha256']=='f'*64
    assert next_l.reserve_worst(True)['attempts']==39
    with pytest.raises(ValueError):l.reserve_worst(True)


@pytest.mark.parametrize('status',['PASS','INCONCLUSIVE','UNSUPPORTED'])
def test_initial_completed_check_retains_exact_verdict_without_repair(tmp_path,monkeypatch,status):
    from photonguard.repair_pipeline import ThreeStepPipeline
    import photonguard.repair_pipeline as module
    store=WorkflowStore(tmp_path,allow_workers=False)
    try:
        s=store._load(store.create('novice-teaching')['id'])
        s.update(pipeline={'status':'CHECKING','phase':'initial'},runs=[{'run_id':'offline-fixture'}])
        store._save(s);controller=ThreeStepPipeline(store)
        controller.wait_solver=lambda ident:store._load(ident)
        monkeypatch.setattr(module,'verify_evidence',lambda path:True)
        monkeypatch.setattr(module,'load',lambda path:{'status':status,'run_id':'offline-fixture'})
        def forbidden(*a,**k):raise AssertionError('Completed initial result must not request a repair')
        monkeypatch.setattr(module,'propose_patch',forbidden)
        controller.run(s['id'],'initial');result=store._load(s['id'])
        assert result['pipeline']['status']=='RESULT'
        assert result['initial_result']['status']==status
        assert result['initial_result']['design_goal_status']=='NOT_EVALUATED'
        assert not result.get('repair_result') and not result.get('repair_permit')
        assert not result.get('diagnosis') and not result.get('proposal')
    finally:store.close()


def test_novice_new_version_is_editable_and_does_not_inherit_approval(tmp_path):
    from photonguard.repair_pipeline import ThreeStepPipeline
    store=WorkflowStore(tmp_path,allow_workers=False)
    try:
        store.allow_workers=True;store.meep_available=True
        controller=ThreeStepPipeline(store);store.pipeline_controller=controller;controller.launch=lambda *args:None
        s=store._load(store.create('novice-teaching')['id']);s['actor_type']='SIMULATED';store._save(s)
        s=store.action(s['id'],{'type':'novice-start','expected_revision':s['revision'],'approve':True,'plan_sha256':s['novice']['plan_sha256']})
        assert s['approval']['actor_type']=='SIMULATED'
        s=store._load(s['id']);s['pipeline'].update(status='RESULT');store._save(s)
        before={p.name:p.read_bytes() for p in store.case_dir(s['id']).iterdir() if p.is_file()}
        child=store.action(s['id'],{'type':'derive-version','expected_revision':s['revision'],'reason':'修改教学参数，建立独立版本'})
        assert child['id']!=s['id'] and child['novice']['kind']=='specified'
        assert child['novice']['ready'] and child['novice']['plan_sha256']!=s['novice']['plan_sha256']
        assert child['actor_type']=='SIMULATED' and not child['approval'] and not child['runs']
        assert not child.get('development_execution') and not child['novice'].get('model_attempt')
        updated=store.action(child['id'],{'type':'novice-material','expected_revision':child['revision'],'text':child['novice']['original_text'].replace('膜厚为300 nm。','膜厚为500 nm。')})
        assert updated['novice']['ready'] and updated['novice']['task']['layers'][0]['thickness_um']==.5
        assert before=={p.name:p.read_bytes() for p in store.case_dir(s['id']).iterdir() if p.is_file()}
    finally:store.close()
