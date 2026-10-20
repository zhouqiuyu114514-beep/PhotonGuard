"""Protocol, goal/approval and finance tests. Synthetic fixtures, no physics claims."""
import copy, hashlib, json, threading
from datetime import datetime,timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import pytest
from photonguard.core import load,digest,write_json
from photonguard import mode_execution as execution,mode_diagnosis as diagnosis
from photonguard.adapters import registry,qpm_phase
from photonguard.mode_pipeline import ModePipeline
from photonguard.workflow import WorkflowStore,WorkflowError

@pytest.fixture
def data(tmp_path,monkeypatch):
    task=load('examples/mode_qpm/ridge.task.json');lock=registry.lock_task(task,approve=True,confirmation_kind='SIMULATED')
    candidate=execution.initial_candidate(task)
    goal={'process':'SHG','pump_wavelength_um':1.55,'length_um':1000,'poling_period_um':20,'qpm_order':1,'target_phase_factor_min':.8}
    modes=[{'wavelength_um':w,'neff':n,'beta_rad_per_um':qpm_phase.beta(w,n),'mode_id':str(w),
        'source_sha256':'a'*64,'source':'SYNTHETIC UNIT FIXTURE','verification_status':'PASS','neff_sensitivity_estimate':d}
        for w,n,d in ((1.55,1.906,.0001),(.775,2.101,.000001))]
    receipts={'a'*64+':'+m['mode_id']:m for m in modes}
    report={'verification_status':'PASS','checks':[],'mode_inputs':modes}
    for m in modes:
        report['checks'] += [{'id':str(m['wavelength_um'])+'.mode_identity','status':'PASS'},
            {'id':str(m['wavelength_um'])+'.tested_setting_sensitivity','status':'PASS',
             'grid_neff_change':m['neff_sensitivity_estimate'],'domain_neff_change':1e-7,'grid_limit':.002,'domain_limit':.0005},
            {'id':str(m['wavelength_um'])+'.root_and_boundary','status':'PASS'}]
    bundle=tmp_path/'bundle';bundle.mkdir()
    for name,value in [('task.json',task),('lock.json',lock),('report.json',report)]:write_json(bundle/name,value)
    write_json(bundle/'manifest.json',{'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in bundle.iterdir()}})
    monkeypatch.setattr(diagnosis.mpb_modes,'qpm_sources',lambda _:(copy.deepcopy(modes),copy.deepcopy(receipts)))
    qtask={'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':task['task_id']+'-QPM','requirements':goal,
        'modes':modes,'provenance':{'reference':'SYNTHETIC UNIT FIXTURE','mode_task_sha256':digest(task),
            'confirmed_goal_sha256':digest(goal),'confirmation_inherited_from_explicit_workflow_consent':True}}
    qpm=qpm_phase.evaluate(qtask,verified_mode_sources=receipts)
    return task,lock,candidate,goal,'SYNTHETIC UNIT FIXTURE',bundle,qpm

def action(request,new=64):
    return {'decision':'propose_patch','changes':[{'path':['numerics','resolution'],'new':new}],
        'rationale':'structured_claims','evidence_ids':['phase_precision'],
        'issues':[{'location_key':'numerics.resolution','reason':'structured_claims','evidence_ids':['phase_precision']}],
        'claims':[{'claim_type':'bounded_inference','fact_refs':['check.phase_precision.metric','check.phase_precision.tolerance'],
            'operation':'above_threshold','conclusion':'tested_metric_exceeds_tolerance'}]}

def test_patch_changes_only_candidate_and_has_a_real_bounded_basis(data):
    task,lock,candidate,goal,*_=data;before=[digest(v) for v in (task,lock,candidate,goal)]
    request,table,context=diagnosis.build_request(*data);result=diagnosis.validate_action(task,candidate,goal,request,table,action(request))
    assert result['status']=='PROPOSED' and result['explanation_audit_status']=='VERIFIED_STRUCTURED_CLAIMS'
    after=execution.apply_change(task,candidate,{'path':['numerics','resolution'],'new':64})
    assert after['numerics']['resolution']==64 and task['numerics']['resolution']==32
    assert [digest(v) for v in (task,lock,candidate,goal)]==before
    assert 'canonical_patch' not in request and 'rule_answer' not in json.dumps(request)
    assert 'provenance' not in request['task'] and 'SYNTHETIC UNIT FIXTURE' not in json.dumps(request)
    assert table['facts']['check.phase_precision.metric']['value']>.1
    assert hashlib.sha256((json.dumps(context,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest()==table['facts']['check.phase_precision.metric']['artifact_sha256']

@pytest.mark.parametrize('path,new',[
    (['qpm_goal','length_um'],10),(['qpm_goal','poling_period_um'],4),(['qpm_goal','target_phase_factor_min'],0),
    (['requirements','ridge_width_um'],2),(['policy','max_phase_sensitivity_rad'],1),(['numerics','resolution'],128),
    (['numerics','resolution'],24),(['numerics','resolution'],True),(['numerics','domain_um'],[100,100])])
def test_goal_verifier_unknown_or_resource_changes_are_rejected(data,path,new):
    request,table,_=diagnosis.build_request(*data);value=action(request);value['changes'][0]={'path':path,'new':new}
    with pytest.raises((ValueError,TypeError)):diagnosis.validate_action(data[0],data[2],data[3],request,table,value)

@pytest.mark.parametrize('mutation',['decision_object','decision_list','wrong_units','invented_value','prose','false_direction','empty_basis','wrong_location','two_changes','identity_unknown'])
def test_bad_real_model_outputs_do_not_become_cards(data,mutation):
    request,table,_=diagnosis.build_request(*data);value=action(request)
    if mutation=='decision_object':value['decision']={}
    if mutation=='decision_list':value['decision']=[]
    if mutation=='wrong_units':value['claims']=[{'claim_type':'measured_fact','fact_refs':['check.phase_precision.metric'],'operation':'value','value':table['facts']['check.phase_precision.metric']['value'],'unit':'dimensionless'}]
    if mutation=='invented_value':value['claims']=[{'claim_type':'measured_fact','fact_refs':['actual.resolution'],'operation':'value','value':160,'unit':'pixels_per_um'}]
    if mutation=='prose':value['rationale']='I guarantee convergence and 100% efficiency'
    if mutation=='false_direction':value['claims'][0].update(operation='within_threshold',conclusion='tested_metric_within_tolerance')
    if mutation=='empty_basis':value['claims']=[]
    if mutation=='wrong_location':value['issues'][0]['location_key']='qpm_goal.length_um'
    if mutation=='two_changes':value['changes'].append({'path':['numerics','domain_um'],'new':[6,6]})
    if mutation=='identity_unknown':request['observations']['mode_identity_unambiguous']=False
    with pytest.raises(ValueError):diagnosis.validate_action(data[0],data[2],data[3],request,table,value)

def test_wrong_evidence_or_stale_qpm_stops_before_transport(data):
    changed=list(data);changed[3]=copy.deepcopy(data[3]);changed[3]['length_um']=10
    with pytest.raises(ValueError,match='RECOMPUTATION'):diagnosis.build_request(*changed)
    changed=list(data);changed[2]=copy.deepcopy(data[2]);changed[2]['numerics']['resolution']=64
    with pytest.raises(ValueError,match='ACTUALLY_SOLVED'):diagnosis.build_request(*changed)
    (data[5]/'report.json').write_text('{}')
    with pytest.raises(ValueError,match='EVIDENCE'):diagnosis.build_request(*data)

def test_not_met_is_not_a_permission_to_change_design(data):
    changed=list(data);goal=copy.deepcopy(data[3]);goal['length_um']=10;changed[3]=goal
    modes,receipts=diagnosis.mpb_modes.qpm_sources(data[5])
    task={'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':data[0]['task_id']+'-QPM','requirements':goal,'modes':modes,
        'provenance':{'reference':data[4],'mode_task_sha256':digest(data[0]),'confirmed_goal_sha256':digest(goal),'confirmation_inherited_from_explicit_workflow_consent':True}}
    changed[-1]=qpm_phase.evaluate(task,verified_mode_sources=receipts)
    assert changed[-1]['verification_status']=='PASS' and changed[-1]['design_goal_status']=='NOT_MET'
    request,table,_=diagnosis.build_request(*changed)
    with pytest.raises(ValueError,match='UNSUPPORTED'):diagnosis.validate_action(data[0],data[2],goal,request,table,action(request))
    value={'decision':'no_change','changes':[],'rationale':'structured_claims','evidence_ids':['qpm_goal'],
        'issues':[{'location_key':'qpm_goal.poling_period_um','reason':'structured_claims','evidence_ids':['qpm_goal']}],
        'claims':[{'claim_type':'measured_fact','fact_refs':['qpm.design_goal_status'],'operation':'value','value':'NOT_MET','unit':'status'}]}
    assert diagnosis.validate_action(data[0],data[2],goal,request,table,value)['patch'] is None

def test_numerical_execution_is_bound_without_changing_old_lock(data,monkeypatch):
    source={'git_commit':'f'*40,'files':{'SYNTHETIC':'a'*64}}
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:source)
    task,lock,candidate=data[:3];permit=execution.permit(task,lock,candidate,approve=True)
    execution.verify_permit(task,lock,candidate,permit)
    changed=execution.apply_change(task,candidate,{'path':['numerics','resolution'],'new':64})
    with pytest.raises(ValueError):execution.verify_permit(task,lock,changed,permit)
    with pytest.raises(ValueError):execution.permit(task,lock,changed,approve=True)
    repair=execution.permit(task,lock,changed,approve=True,phase='repair',card_sha256='b'*64)
    execution.verify_permit(task,lock,changed,repair);assert lock['repair_approved'] is False

@pytest.mark.parametrize('failure',['none','invalid_action','network','invalid_usage'])
def test_mode_broker_uses_same_cumulative_ledger_and_preserves_failures(data,tmp_path,failure):
    from photonguard.development_phase import ledger_for
    from photonguard.repair_diagnosis import prepare_binding,RepairBroker
    from photonguard.backend import TransportResponse,ENDPOINT
    phase=tmp_path/'phase';phase.mkdir();stamp=datetime.now(timezone.utc).isoformat()
    write_json(phase/'phase.json',{'owner_approved_budget_cny':'20','reference':'SYNTHETIC OWNER FIXTURE','official_rates_checked_at':stamp})
    ledger=ledger_for(phase,stamp)
    with ledger._locked():
        initial=ledger._empty();initial.update(attempts=28,live_provider_attempts=28,reserved_cny='4.173962000028',
            settled_cny='4.173962000028',reserved_usd='.6260943',settled_usd='.6260943');ledger._write(initial)
    destination=tmp_path/'binding';calls=[]
    def transport(request):
        calls.append(request)
        if failure=='network':raise OSError('SYNTHETIC failure')
        req,_,_=diagnosis.build_request(*data);value=action(req)
        if failure=='invalid_action':value['changes'][0]['path']=['qpm_goal','length_um']
        usage={'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}
        if failure=='invalid_usage':usage['total_tokens']=999
        body={'model':'SYNTHETIC_NOT_REAL','choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(value)}}],'usage':usage}
        return TransportResponse(200,json.dumps(body).encode(),ENDPOINT)
    with patch('photonguard.repair_diagnosis.source_manifest',return_value={'SYNTHETIC_SOURCE':True}):
        prepare_binding(Path.cwd(),phase,destination,stamp,mode_ai=True)
        bound=RepairBroker(Path.cwd(),phase,destination,lambda:'sk-synthetic-not-real',transport=transport)
        broker=diagnosis.ModeBroker(bound);result=broker.diagnose(*data);after=ledger.snapshot()
        assert len(calls)==1 and after['attempts']==29 and after['live_provider_attempts']==28
        assert Decimal(after['reserved_cny'])>Decimal('4.173962000028')
        assert (after['pending'] is not None)==(failure in ('network','invalid_usage'))
        expected={'none':'PROPOSED','invalid_action':'REJECTED','network':'FAILED','invalid_usage':'FAILED'}[failure]
        assert result['status']==expected and Path(result['evidence_directory']).joinpath('result.json').exists()
        with pytest.raises((ValueError,FileExistsError)):broker.diagnose(*data)
        assert len(calls)==1

def test_old_film_scope_binding_cannot_implicitly_enable_mode_ai(data,tmp_path):
    fake=SimpleNamespace(preflight=lambda **_:None,binding={})
    with pytest.raises(ValueError,match='SCOPE'):diagnosis.ModeBroker(fake)

def test_interpretation_checked_separately_from_legal_patch(data):
    request,table,_=diagnosis.build_request(*data);value=action(request)
    value['claims'].append({'claim_type':'mode_interpretation','fact_refs':['check.phase_precision.metric','check.phase_precision.tolerance','qpm.verification_status'],
        'conclusion':'phase_precision_insufficient'})
    result=diagnosis.validate_action(data[0],data[2],data[3],request,table,value)
    assert '暂不能判断设计达标' in result['reason']
    value['claims'][-1]={'claim_type':'mode_interpretation','fact_refs':['mode.verification_status','qpm.verification_status','qpm.design_goal_status','qpm.phase_factor_NOT_efficiency'],
        'conclusion':'locked_design_not_met'}
    with pytest.raises(ValueError,match='UNSUPPORTED'):diagnosis.validate_action(data[0],data[2],data[3],request,table,value)

def test_incomplete_field_identity_cannot_be_falsely_assumed_unique(data):
    request,table,_=diagnosis.build_request(*data)
    request['observations']['mode_identity_unambiguous']=False
    with pytest.raises(ValueError,match='AMBIGUOUS'):diagnosis.validate_action(data[0],data[2],data[3],request,table,action(request))

def test_fact_citation_aliases_preserve_exact_claims_and_patch(data):
    request,table,_=diagnosis.build_request(*data);value=action(request)
    value['evidence_ids']=['check.phase_precision.metric','check.phase_precision.tolerance','check.fund_tested_setting_sensitivity.status']
    value['issues'][0]['evidence_ids']=['check.phase_precision.metric']
    original=copy.deepcopy(value);result=diagnosis.validate_action(data[0],data[2],data[3],request,table,value)
    assert result['status']=='PROPOSED' and result['citation_normalizations']
    assert value==original and result['patch']['change']['new']==64
    assert result['citation_normalizations'][0]=={'from_fact_id':'check.phase_precision.metric','to_check_id':'phase_precision'}

@pytest.mark.parametrize('bad',['invented_fact','wrong_family','wrong_value','missing_issue'])
def test_namespace_support_never_loosens_patch_or_fact_checks(data,bad):
    request,table,_=diagnosis.build_request(*data);value=action(request)
    value['evidence_ids']=['check.phase_precision.metric'];value['issues'][0]['evidence_ids']=['check.phase_precision.metric']
    if bad=='invented_fact':value['evidence_ids']=['check.invented.metric']
    if bad=='wrong_family':value['changes'][0]={'path':['numerics','domain_um'],'new':[6,6]};value['issues'][0]['location_key']='numerics.domain_um'
    if bad=='wrong_value':value['claims'].append({'claim_type':'measured_fact','fact_refs':['actual.resolution'],'operation':'value','value':99,'unit':'pixels_per_um'})
    if bad=='missing_issue':value['issues']=[]
    with pytest.raises(ValueError):diagnosis.validate_action(data[0],data[2],data[3],request,table,value)

def test_output_caps_apply_to_actual_grid_and_domain_variants(data):
    candidate=copy.deepcopy(data[2]);candidate['numerics'].update(resolution=80,domain_um=[6,6])
    with pytest.raises(ValueError,match='RESOURCE'):execution.validate_repair_candidate(data[0],candidate)
    assert all(e['estimated_max_band_file_bytes']<=execution.POLICY['max_band_file_estimate_bytes'] for e in execution.eligible_changes(data[0],data[2]))

def awaiting(store,data,monkeypatch):
    source={'git_commit':'f'*40,'files':{'SYNTHETIC':'a'*64}}
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:source)
    controller=ModePipeline(store);store.mode_controller=controller
    state=controller.create_demo();raw=store._load(state['id']);flow=raw['adapter_flow']
    flow.update(mode_task=data[0],mode_lock=data[1],candidate=data[2],qpm_goal=data[3],qpm_source=data[4],
        qpm_goal_sha256=digest(data[3]),stage='RESULT',selected_diagnostic_mode='live')
    # Fixture stays external only for this state/approval unit test; not a production archive.
    import shutil
    shutil.copytree(data[5],store.case_dir(state['id'])/'owned-bundle')
    flow['result']={'status':'completed','mode_bundle':'owned-bundle','qpm_report':data[6]}
    flow['initial_result']=copy.deepcopy(flow['result']);request,table,_=diagnosis.build_request(*data)
    flow['diagnosis']=diagnosis.validate_action(data[0],data[2],data[3],request,table,action(request))
    flow['repair_card']=controller.card(raw,flow['diagnosis']);store._save(raw)
    return store.get(state['id']),controller

@pytest.mark.parametrize('bad',['no_approval','stale_card','source_changed','goal_changed','candidate_changed'])
def test_no_solver_without_current_exact_repair_approval(data,tmp_path,monkeypatch,bad):
    store=WorkflowStore(tmp_path/'workspace',allow_workers=True)
    try:
        state,controller=awaiting(store,data,monkeypatch);starts=[]
        monkeypatch.setattr('photonguard.mode_pipeline.subprocess.Popen',lambda *a,**k:(starts.append(a) or SimpleNamespace(pid=999999)))
        request={'type':'mode-approve-repair','expected_revision':state['revision'],'approve':True,'card_sha256':state['adapter_flow']['repair_card_sha256']}
        if bad=='no_approval':request['approve']=False
        if bad=='stale_card':request['card_sha256']='0'*64
        if bad=='source_changed':monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:{'changed':True})
        if bad in ('goal_changed','candidate_changed'):
            raw=store._load(state['id'])
            if bad=='goal_changed':raw['adapter_flow']['qpm_goal']['length_um']=1
            else:raw['adapter_flow']['candidate']['numerics']['resolution']=48
            store._save(raw);request['expected_revision']=raw['revision']
        with pytest.raises(WorkflowError):store.action(state['id'],request)
        assert not starts and not store._load(state['id'])['adapter_flow'].get('repair_count')
    finally:store.close()

def test_one_approval_starts_once_and_keeps_goal_lock(data,tmp_path,monkeypatch):
    store=WorkflowStore(tmp_path/'workspace',allow_workers=True)
    try:
        state,controller=awaiting(store,data,monkeypatch);starts=[]
        monkeypatch.setattr('photonguard.mode_pipeline.subprocess.Popen',lambda *a,**k:(starts.append(a) or SimpleNamespace(pid=999999)))
        original=copy.deepcopy(state['adapter_flow']['mode_lock']);goal=digest(state['adapter_flow']['qpm_goal'])
        request={'type':'mode-approve-repair','expected_revision':state['revision'],'approve':True,'card_sha256':state['adapter_flow']['repair_card_sha256']}
        result=store.action(state['id'],request)
        assert len(starts)==1 and result['adapter_flow']['candidate']['numerics']['resolution']==64
        assert result['adapter_flow']['mode_lock']==original and digest(result['adapter_flow']['qpm_goal'])==goal
        with pytest.raises(WorkflowError):store.action(state['id'],request)
        assert len(starts)==1 and result['adapter_flow']['repair_count']==1
    finally:store.close()

def test_ai_rejection_has_no_rules_fallback_or_solver(data,tmp_path,monkeypatch):
    store=WorkflowStore(tmp_path/'workspace',allow_workers=True)
    try:
        state,controller=awaiting(store,data,monkeypatch);raw=store._load(state['id']);flow=raw['adapter_flow']
        flow.pop('diagnosis');flow.pop('repair_card');flow['diagnosis_job']={'id':'SYNTHETIC','status':'running'};store._save(raw)
        controller.broker=SimpleNamespace(diagnose=lambda *a:{'status':'REJECTED','patch':None,'issues':[],'reason':'SYNTHETIC REJECTION','actual_model_calls':1})
        monkeypatch.setattr(diagnosis,'rules_diagnosis',lambda *a:pytest.fail('fallback forbidden'))
        monkeypatch.setattr('photonguard.mode_pipeline.subprocess.Popen',lambda *a,**k:pytest.fail('solver forbidden'))
        controller.diagnose(state['id']);result=store._load(state['id'])['adapter_flow']
        assert result['diagnosis']['status']=='REJECTED' and not result.get('repair_card') and result['model_requests']==1
    finally:store.close()

def test_interrupted_ai_marker_is_preserved_without_replay(data,tmp_path,monkeypatch):
    store=WorkflowStore(tmp_path/'workspace',allow_workers=True)
    try:
        state,controller=awaiting(store,data,monkeypatch);raw=store._load(state['id']);raw['adapter_flow']['diagnosis_job']={'id':'SYNTHETIC','status':'running'};store._save(raw)
        result=store.get(state['id'])
        assert result['adapter_flow']['diagnosis_job']['status']=='interrupted'
        assert result['pipeline']['status']=='INTERRUPTED' and result['adapter_flow']['result']
        with pytest.raises(WorkflowError):store.action(state['id'],{'type':'mode-diagnose','diagnostic_mode':'rules','expected_revision':result['revision']})
    finally:store.close()

def test_live_diagnosis_requires_data_scope_and_preflight_before_lock(tmp_path,monkeypatch):
    store=WorkflowStore(tmp_path/'workspace',allow_workers=True);calls=[]
    try:
        broker=SimpleNamespace(preflight=lambda **_:calls.append('preflight'),status=lambda:{'live_enabled':True})
        store.mode_controller=ModePipeline(store,broker);state=store.mode_controller.create_demo()
        monkeypatch.setattr('photonguard.mode_pipeline.subprocess.Popen',lambda *a,**k:pytest.fail('solver forbidden'))
        with pytest.raises(WorkflowError):store.action(state['id'],{'type':'mode-confirm-run','expected_revision':state['revision'],
            'approve':True,'accept_resources':True,'diagnostic_mode':'live','approve_diagnostic_data':False})
        assert not calls and not store._load(state['id'])['adapter_flow'].get('mode_lock')
    finally:store.close()

def test_imported_development_archive_cannot_replay_requests_or_approvals(data,tmp_path,monkeypatch):
    store=WorkflowStore(tmp_path/'workspace',allow_workers=True)
    try:
        state,controller=awaiting(store,data,monkeypatch);raw=store._load(state['id'])
        raw['mode_evidence_archive']={'source_case_id':state['id'],'read_only':True};store._save(raw)
        for kind in ('mode-diagnose','mode-reassess','mode-approve-repair','mode-confirm-run'):
            with pytest.raises(WorkflowError,match='只读迁移'):store.action(state['id'],{'type':kind,'expected_revision':raw['revision']})
        result=store.action(state['id'],{'type':'mode-new-version','expected_revision':raw['revision'],'reason':'独立资料明确更新，建立新任务版本'})
        assert not result.get('mode_evidence_archive') and not result['adapter_flow'].get('mode_lock')
        assert store._load(state['id'])['mode_evidence_archive']['read_only']
    finally:store.close()
