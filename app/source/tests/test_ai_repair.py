"""Offline boundary tests. All approvals/model responses are simulated."""
import copy
import http.client
import json
import shutil
from pathlib import Path
import threading
from unittest.mock import patch
import pytest
from photonguard.core import load,write_json,lock_task,digest,POLICY_HASH
from photonguard.runner import run_case
from photonguard.script_import import preview_bytes
from photonguard.repair_diagnosis import model_request,validate_model_action,RepairBroker
from photonguard.repair_pipeline import ThreeStepPipeline
from photonguard.workflow import WorkflowStore,WorkflowError,make_server
from photonguard.workflow_intake import prepare,apply
from photonguard.task_mapping import project
from tools.serve_ai_repair import TEXT,OPTIONS

ROOT=Path(__file__).resolve().parents[1]

def test_historical_explanation_overlay_preserves_saved_bytes(evidence,tmp_path):
    store=WorkflowStore(tmp_path/'old-workspace',allow_workers=False)
    try:
        state=store._load(store.create('own')['id']);state['task']=load(evidence/'task.original.json')
        state['diagnostic_mode']='live';state['diagnosis']={'reason':'时间敏感度通过，说明不是时间步长问题。','issues':[]}
        state['runs']=[{'run_id':evidence.name}]
        shutil.copytree(evidence,store.case_dir(state['id'])/'artifacts'/evidence.name)
        store._save(state);saved=store.case_dir(state['id'])/'state.json';original=saved.read_bytes()
        presented=store.get(state['id'])
        assert presented['historical_explanation_audit']['status']=='UNSUPPORTED'
        assert presented['historical_explanation_audit']['derived_read_only']
        assert saved.read_bytes()==original and 'historical_explanation_audit' not in load(saved)
    finally:store.close()
def intake(text=TEXT):return apply(prepare('synthetic',text),{'type':'intake-review','mode':'mock'})
def setup(store):
    state=store._load(store.create('own')['id']);state['intake']=intake();store._save(state)
    controller=ThreeStepPipeline(store);store.pipeline_controller=controller
    controller.launch=lambda *_:None
    return state,controller
def data(state,**extra):
    return dict(type='start-review',expected_revision=state['revision'],approve=True,accept_initial_checks=True,
        diagnostic_mode='rules',approve_diagnostic_data=False,result_sha256=state['intake']['result_sha256'],
        options=copy.deepcopy(OPTIONS),source=(ROOT/'examples/script_import/numerical_film_scan.py').read_text(),**extra)

@pytest.fixture
def evidence(tmp_path):
    value=intake();value=apply(value,{'type':'intake-confirm','approve':True,'result_sha256':value['result_sha256']})
    task=project(value,OPTIONS)[0]
    # Deliberate mismatch only exercises action validation, not AI-value claims.
    candidate=preview_bytes((ROOT/'examples/script_import/numerical_film_scan.py').read_bytes())['candidate']
    candidate['layers'][0]['material_value']=3.0
    candidate.pop('origin')
    write_json(tmp_path/'t.json',task);write_json(tmp_path/'c.json',candidate);lock_task(tmp_path/'t.json',tmp_path/'l.json')
    return run_case(tmp_path/'t.json',tmp_path/'c.json',tmp_path/'l.json',tmp_path/'runs',0)[1]

def test_request_does_not_supply_rule_patch_or_source_prose(evidence):
    base,request=model_request(evidence)
    assert request['contract']=='ai-repair-diagnosis-3'
    assert request['observations']['source_locations']=={}
    assert 'origin' not in request['candidate'] and 'sources' not in request['task']
    assert 'canonical_patch' not in request and 'ground_truth' not in request

@pytest.mark.parametrize('decision',['no_change','inconclusive','unsupported'])
def test_abstention_preserved(evidence,decision):
    base,request=model_request(evidence)
    action=dict(decision=decision,changes=[],rationale='structured_claims',evidence_ids=[],issues=[],claims=[])
    assert validate_model_action(evidence,base,request,action,{'actual_llm_calls':0})==(None,[])

@pytest.mark.parametrize('bad',[{},[],{'policy':['threshold']},'approve','PASS'])
def test_malformed_decision_is_controlled(evidence,bad):
    base,request=model_request(evidence)
    with pytest.raises(ValueError):validate_model_action(evidence,base,request,dict(decision=bad,changes=[],rationale='x',evidence_ids=[],issues=[]),{})

def test_request_ast_location_tampering_rejected(evidence):
    base,request=model_request(evidence);request['observations']['source_locations']['policy.tolerance']=[{'line':1}]
    with pytest.raises(ValueError,match='BINDING'):validate_model_action(evidence,base,request,dict(decision='no_change',changes=[],rationale='x',evidence_ids=[],issues=[]),{})

def test_patch_requires_actual_location_and_citations(evidence):
    base,request=model_request(evidence)
    a=dict(decision='propose_patch',changes=[{'path':['layers',0,'material_value'],'new':3.4}],rationale='structured_claims',evidence_ids=['task_parameters'],issues=[],claims=[])
    with pytest.raises(ValueError,match='LOCATED'):validate_model_action(evidence,base,request,a,{})
    a['issues']=[{'location_key':'invented','reason':'x','evidence_ids':['task_parameters']}]
    with pytest.raises(ValueError,match='CITATION'):validate_model_action(evidence,base,request,a,{})

@pytest.mark.parametrize('field,value',[('approve',False),('accept_initial_checks',False),('result_sha256','stale')])
def test_no_lock_without_current_explicit_confirmation(tmp_path,field,value):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=setup(store);request=data(state);request[field]=value
        with pytest.raises(WorkflowError):store.action(state['id'],request)
        assert not store.get(state['id'])['approval']
    finally:store.close()

def test_one_confirmation_starts_once_blocks_direct_actions(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=setup(store);launch=[];c.launch=lambda *a:launch.append(a)
        result=store.action(state['id'],data(state));assert result['approval'] and len(launch)==1
        assert not result.get('repair_permit')
        for kind,extra in [('start-review',{}),('propose',{}),('apply',{'approve':True}),('pause',{'reason':'cancel now'}),('derive-version',{'reason':'change target'})]:
            request=data(result) if kind=='start-review' else {'type':kind,'expected_revision':result['revision'],**extra}
            with pytest.raises(WorkflowError):store.action(state['id'],request)
        assert len(launch)==1
    finally:store.close()

def test_budget_read_failure_disables_service_without_recreating_ledger():
    broker=object.__new__(RepairBroker)
    class Broken:
        def snapshot(self):raise ValueError('missing')
    broker.ledger=Broken();broker.preflight=lambda:(_ for _ in ()).throw(ValueError('missing'))
    assert broker.status()['live_enabled'] is False

def test_same_ui_asset_available_for_both_modes(tmp_path):
    server=make_server(tmp_path,port=0,allow_workers=False);server.store.pipeline_controller=ThreeStepPipeline(server.store)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
        conn.request('GET','/repair.js');response=conn.getresponse();body=response.read().decode()
        assert response.status==200 and 'text/javascript' in response.getheader('Content-Type')
        assert 'AI 问题分析' in body and '规则诊断' in body
        conn.request('GET','/api/bootstrap');response=conn.getresponse();assert json.loads(response.read())['repair_service']['live_enabled'] is False
        conn.close()
    finally:server.shutdown();server.server_close();thread.join()

def awaiting(store):
    state,c=setup(store);store.action(state['id'],data(state))
    state=store._load(state['id']);patch_value={'changes':[{'path':['numerics','resolution'],'old':80,'new':320}],
        'rationale':'Synthetic approval guard fixture, not a model result','based_on_run':'synthetic'}
    state['proposal']=patch_value;state['pipeline']['status']='AWAITING_APPROVAL'
    state['repair_card']={'task_sha256':digest(state['task']),'candidate_sha256':digest(state['candidate']),
        'patch_sha256':digest(patch_value),'policy_sha256':POLICY_HASH,'source_binding':{'synthetic':True}}
    store._save(state);return state,c

def test_approve_once_queues_exactly_one_reverification(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=awaiting(store);calls=[];c.launch=lambda *a:calls.append(a)
        with patch('photonguard.approved_gui.source_manifest',return_value={'synthetic':True}):
            result=store.action(state['id'],{'type':'approve-repair','expected_revision':state['revision'],
                'approve':True,'card_sha256':digest(state['repair_card'])})
        assert calls==[(state['id'],'repair')]
        assert result['repair_permit']['max_fresh_fdtd_runs']==8
        assert result['repair_permit']['additional_model_requests']==0
        with pytest.raises(WorkflowError):store.action(state['id'],{'type':'approve-repair','expected_revision':result['revision'],
            'approve':True,'card_sha256':digest(state['repair_card'])})
        assert len(calls)==1
    finally:store.close()

@pytest.mark.parametrize('changed',['task','candidate','proposal','policy','source','stale_card'])
def test_changed_approval_scope_blocks_execution(tmp_path,changed):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=awaiting(store);calls=[];c.launch=lambda *a:calls.append(a)
        card_hash=digest(state['repair_card'])
        if changed=='task':state['task']['layers'][0]['n']=3.5
        if changed=='candidate':state['candidate']['numerics']['resolution']=160
        if changed=='proposal':state['proposal']['changes'][0]['new']=160
        if changed=='policy':state['repair_card']['policy_sha256']='changed'
        if changed=='stale_card':card_hash='obsolete'
        store._save(state)
        with patch('photonguard.approved_gui.source_manifest',return_value={'synthetic':changed!='source'}):
            with pytest.raises(WorkflowError):store.action(state['id'],{'type':'approve-repair','expected_revision':state['revision'],
                'approve':True,'card_sha256':card_hash})
        assert not calls and not store.get(state['id']).get('repair_permit')
    finally:store.close()

def test_repair_phase_applies_once_runs_once_never_calls_model(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=awaiting(store);state['repair_permit']={'status':'APPROVED'};store._save(state)
        calls=[];c.legacy=lambda *a,**k:calls.append(a)
        def completed(ident):
            calls.append((ident,'run'))
            result=store._load(ident);result['runs']=[{'run_id':'synthetic-verified'}];return result
        c.wait_solver=completed
        report={'status':'FAIL','run_id':'synthetic-verified','candidate_hash':digest(state['candidate'])}
        with patch('photonguard.repair_pipeline.verify_evidence',return_value=True),patch('photonguard.repair_pipeline.load',return_value=report):
            c.run(state['id'],'repair')
        result=store.get(state['id'])
        assert calls==[(state['id'],'apply'),(state['id'],'run')]
        assert result['repair_result']['status']=='FAIL' and result['pipeline']['status']=='RESULT'
        assert result['repair_result']['source_script_modified'] is False
    finally:store.close()

@pytest.mark.parametrize('failure',[False,True])
def test_same_financial_counter_carried_and_failed_call_not_refunded(tmp_path,evidence,failure):
    from datetime import datetime,timezone
    from decimal import Decimal
    from photonguard.development_phase import ledger_for
    from photonguard.repair_diagnosis import prepare_binding
    from photonguard.backend import TransportResponse,ENDPOINT
    phase=tmp_path/'phase';phase.mkdir();stamp=datetime.now(timezone.utc).isoformat()
    write_json(phase/'phase.json',{'owner_approved_budget_cny':'20','reference':'OFFLINE OWNER FIXTURE',
        'official_rates_checked_at':stamp})
    ledger=ledger_for(phase,stamp)
    # Existing cumulative count/cost, explicitly synthetic test authorization.
    with ledger._locked():
        initial=ledger._empty();initial.update(attempts=25,live_provider_attempts=25,
            reserved_cny='4.084946000025',settled_cny='4.084946000025',reserved_usd='.6127419',settled_usd='.6127419')
        ledger._write(initial)
    dest=tmp_path/'binding';calls=[]
    action={'decision':'inconclusive','changes':[],'rationale':'structured_claims','evidence_ids':[],'issues':[],'claims':[]}
    def transport(request):
        calls.append(request)
        if failure:raise OSError('synthetic transport failure')
        body={'id':'offline','model':'SYNTHETIC_NOT_A_REAL_MODEL','choices':[{'index':0,'finish_reason':'stop',
            'message':{'role':'assistant','content':json.dumps(action)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}}
        return TransportResponse(200,json.dumps(body).encode(),ENDPOINT)
    with patch('photonguard.repair_diagnosis.source_manifest',return_value={'synthetic':True}):
        binding=prepare_binding(ROOT,phase,dest,stamp);assert binding['carried_attempts']==25
        broker=RepairBroker(ROOT,phase,dest,lambda:'sk-synthetic-not-real',transport=transport)
        result=broker.diagnose(evidence);after=ledger.snapshot()
        assert len(calls)==1 and after['attempts']==26 and after['live_provider_attempts']==25
        assert after['pending'] is not None if failure else after['pending'] is None
        assert Decimal(after['reserved_cny'])>Decimal('4.084946000025')
        assert result['status']=='FAILED' if failure else result['status']=='NO_PATCH'
        with pytest.raises((ValueError,FileExistsError)):broker.diagnose(evidence)
        assert len(calls)==1

@pytest.mark.parametrize('text',[TEXT.replace('膜厚为800 nm。',''),TEXT+'\n膜层折射率为1.9。',TEXT.replace('入射角为0 deg。','入射角为15 deg。')])
def test_three_step_missing_conflict_unsupported_never_lock(tmp_path,text):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=setup(store);state['intake']=intake(text);store._save(state)
        with pytest.raises(WorkflowError):store.action(state['id'],data(state))
        result=store.get(state['id']);assert not result['approval'] and not result['job']
        store.action(state['id'],{'type':'pause','expected_revision':result['revision'],'reason':'Await independent materials'})
        assert store.get(state['id'])['intake']['result']
    finally:store.close()

def test_real_model_rejection_has_no_rule_fallback(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=setup(store);store.action(state['id'],data(state));state=store._load(state['id'])
        state['diagnostic_mode']='live';state['runs']=[{'run_id':'fixture'}];store._save(state)
        class Broker:
            def diagnose(self,path):return {'status':'REJECTED','patch':None,'issues':[],'reason':'TEST FIXTURE ONLY'}
        c.broker=Broker();c.wait_solver=lambda ident:store._load(ident)
        with patch('photonguard.repair_pipeline.verify_evidence',return_value=True),patch('photonguard.repair_pipeline.load',return_value={'status':'FAIL'}),patch('photonguard.repair_pipeline.propose_patch',side_effect=AssertionError('fallback forbidden')):
            c.run(state['id'],'initial')
        result=store._load(state['id']);assert result['pipeline']['status']=='NO_PATCH' and not result['proposal']
        assert result['diagnosis']['status']=='REJECTED'
    finally:store.close()

def test_new_materials_use_three_steps_without_invented_intent(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=False)
    try:
        store.pipeline_controller=ThreeStepPipeline(store)
        state=store.create('own')
        assert state['three_step'] and not state['approval'] and not state.get('intake')
        assert not state.get('repair_trial') and not state['candidate']
    finally:store.close()


def test_explanation_warning_requires_explicit_current_acknowledgement(tmp_path):
    store=WorkflowStore(tmp_path,allow_workers=True)
    try:
        state,c=awaiting(store);calls=[];c.launch=lambda *a:calls.append(a)
        state['repair_card']['explanation_audit_status']='UNSUPPORTED';store._save(state)
        request={'type':'approve-repair','expected_revision':state['revision'],'approve':True,'card_sha256':digest(state['repair_card'])}
        with patch('photonguard.approved_gui.source_manifest',return_value={'synthetic':True}):
            with pytest.raises(WorkflowError,match='模型说明'):store.action(state['id'],request)
            assert not calls
            request['acknowledge_explanation_warning']=True
            result=store.action(state['id'],request)
        assert len(calls)==1 and result['repair_permit']['explanation_warning_acknowledged']
    finally:store.close()

def test_claim_fact_table_tampering_rejected_before_action(evidence):
    base,request=model_request(evidence)
    first=next(iter(request['observations']['evidence_facts']['facts'].values()))
    first['json_pointer']='/policy/rt_absolute_tolerance'
    with pytest.raises(ValueError,match='BINDING'):
        validate_model_action(evidence,base,request,dict(decision='no_change',changes=[],rationale='x',evidence_ids=[],issues=[]),{})


@pytest.mark.parametrize('citations', [['check.task_parameters.status'], ['base.resolution'], [None], 'task_parameters'])
def test_fact_ids_are_not_action_check_ids(evidence, citations):
    base, request = model_request(evidence)
    action = dict(decision='no_change', changes=[], rationale='structured_claims',
                  evidence_ids=citations, issues=[], claims=[])
    with pytest.raises(ValueError, match='MODEL_CITATION_NAMESPACE'):
        validate_model_action(evidence, base, request, action, {})
    # Exact check IDs remain accepted; no implicit conversion of the response.
    action['evidence_ids'] = ['task_parameters']
    assert validate_model_action(evidence, base, request, action, {}) == (None, [])


def test_rejection_keeps_verified_claims_without_restoring_action(evidence):
    from photonguard.repair_diagnosis import retained_rejection
    _, request = model_request(evidence)
    good = dict(claim_type='measured_fact', fact_refs=['check.task_parameters.status'],
                operation='value', value='FAIL', unit='status')
    bad = {**good, 'value':'PASS'}
    action = dict(decision='propose_patch', changes=[{'path':['policy'], 'new':'bypass'}],
                  rationale='structured_claims', evidence_ids=['check.task_parameters.status'],
                  issues=[], claims=[good, bad])
    original = copy.deepcopy(action)
    result = retained_rejection(evidence, request, action, ValueError('MODEL_CITATION_NAMESPACE'))
    assert result['status'] == 'REJECTED' and result['patch'] is None
    assert not result['patch_policy_valid'] and result['reverification_status'] == 'NOT_RUN'
    assert result['explanation_audit_status'] == 'UNSUPPORTED'
    assert result['explanation_audit']['accepted'] == [good]
    assert result['explanation_audit']['findings'] == [{'claim_index':1, 'code':'CLAIM_VALUE_OR_DIRECTION'}]
    assert action == original


@pytest.mark.parametrize('error', [ValueError('secret-sentinel-do-not-emit'),
                                 KeyError('secret-sentinel-do-not-emit')])
def test_rejection_does_not_expose_arbitrary_exception_text(evidence, error):
    from photonguard.repair_diagnosis import retained_rejection
    _, request = model_request(evidence)
    result = retained_rejection(evidence, request, [], error)
    assert result['rejection_code'] == 'MODEL_ACTION_INVALID'
    assert 'secret-sentinel' not in json.dumps(result)
    assert result['explanation_audit_status'] == 'UNSUPPORTED'


def test_rejection_never_audits_a_tampered_fact_as_verified(evidence):
    from photonguard.repair_diagnosis import retained_rejection
    _, request = model_request(evidence)
    facts = request['observations']['evidence_facts']['facts']
    facts['check.task_parameters.status']['value'] = 'PASS'
    action = dict(rationale='structured_claims', issues=[], claims=[dict(
        claim_type='measured_fact', fact_refs=['check.task_parameters.status'],
        operation='value', value='PASS', unit='status')])
    result = retained_rejection(evidence, request, action, ValueError('MODEL_REQUEST_BINDING'))
    assert result['status'] == 'REJECTED' and result['explanation_audit']['accepted'] == []
    assert result['explanation_audit_status'] == 'UNSUPPORTED'
