"""Workbench service authorization, lineage and evidence tests. No paid calls."""
import copy
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import zipfile

import pytest

from photonguard.experiments import service
from photonguard.experiments.planner import templates
from photonguard.workflow import WorkflowError


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs):self.target=target;self.args=args
    def start(self):self.target(*self.args)


class FakeClient:
    """Provider-shaped fake; audit explicitly says no live dispatch."""
    def __init__(self, answer=None):self.answer=answer;self.requests=[];self.preflights=0;self.error=None
    def status(self):return {'live_enabled':False,'model':'TEST_DOUBLE','reason':'unit test; no provider'}
    def preflight(self):self.preflights+=1
    def complete(self, ident, payload):
        self.requests.append((ident,copy.deepcopy(payload)))
        if self.error:raise self.error
        return {'audit':{'status':'ASSISTANT_RETURNED','live_dispatch':False},
                'assistant':{'content':json.dumps(self.answer)}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(service.threading,'Thread',ImmediateThread)
    owner=SimpleNamespace(root=tmp_path,csrf='test-csrf',allow_workers=True,simulation_context=None,
                          product_client=None,lock=threading.RLock())
    return service.ExperimentStore(owner)


def make_plan(store):
    state=store.create({'kind':'teaching','template_id':'gaussian-catalog'})
    return store.action(state['id'],{'type':'plan','expected_revision':state['revision'],'mode':'rules'})


def fake_result(plan):
    first=plan['candidates'][0]
    return {'status':'RUN_COMPLETED','plan_sha256':plan['sha256'],
            'candidates':[dict(first,status='RUN_COMPLETED',all_checks_passed=True,
                               goal={'metric':'screen_radius_um','operator':'minimize','value':40.0,'unit':'um','met':None})],
            'winner_id':first['id'],'resources':{'model_calls':0,'actual_fdtd_runs':0}}


def run_fake(store, state, monkeypatch, execute=None):
    def normal(plan,out):
        Path(out).mkdir(parents=True)
        (Path(out)/'plan.json').write_text(json.dumps(plan))
        return fake_result(plan)
    monkeypatch.setattr(service,'execute_plan',execute or normal)
    store.action(state['id'],{'type':'run','expected_revision':state['revision'],
                            'approve':True,'plan_sha256':state['plan']['sha256']})
    return store.get(state['id'])


def specification():
    raw=copy.deepcopy(next(x['spec'] for x in templates() if x['domain']=='gaussian'))
    raw['context_kind']='specified'
    quote='633 nm; 500 um; 0 mm; 100 mm; 150 mm; 200 mm; 250 mm'
    for value in raw['parameter_sources'].values():value['quote']=quote
    return raw


def events(store, ident):
    return [json.loads(p.read_text()) for p in (store.folder(ident)/'events').glob('*.json')]


def test_local_plan_has_no_invented_real_ai_evidence(store):
    state=make_plan(store)
    assert state['status']=='PLANNED'
    assert state['model_calls']==0
    assert store.bootstrap()['ai']['live_enabled'] is False
    drafts=[e['value'] for e in events(store,state['id']) if e['kind']=='PLAN_DRAFT']
    assert drafts[-1]['actual_model_calls']==0
    assert drafts[-1].get('raw_response') is None


@pytest.mark.parametrize('change',[{'approve':False},{'approve':1},{'plan_sha256':'0'*64},{'expected_revision':0}])
def test_run_requires_current_explicit_plan_approval(store,monkeypatch,change):
    state=make_plan(store)
    monkeypatch.setattr(service,'execute_plan',lambda *a:pytest.fail('unauthorized execution'))
    request={'type':'run','approve':True,'plan_sha256':state['plan']['sha256'],'expected_revision':state['revision']}
    request.update(change)
    with pytest.raises(WorkflowError):store.action(state['id'],request)
    assert store.get(state['id'])['status']=='PLANNED'


@pytest.mark.parametrize('blocked_mode',['offline','simulation'])
def test_offline_and_simulated_context_cannot_start_new_solver(store,monkeypatch,blocked_mode):
    state=make_plan(store)
    if blocked_mode=='offline':store.owner.allow_workers=False
    else:store.owner.simulation_context={'actor':'SIMULATED'}
    monkeypatch.setattr(service,'execute_plan',lambda *a:pytest.fail('solver forbidden'))
    with pytest.raises(WorkflowError) as error:
        store.action(state['id'],{'type':'run','approve':True,'plan_sha256':state['plan']['sha256'],'expected_revision':state['revision']})
    assert error.value.status==403


def test_tampered_candidate_is_rejected_before_execution(store,monkeypatch):
    state=make_plan(store)
    state['plan']['candidates'][0]['parameters']['waist_radius_um']=900
    store.save(state)
    monkeypatch.setattr(service,'execute_plan',lambda *a:pytest.fail('tampered plan execution'))
    with pytest.raises(WorkflowError,match='校验'):
        store.action(state['id'],{'type':'run','approve':True,'plan_sha256':state['plan']['sha256'],'expected_revision':state['revision']})


def test_completed_version_cannot_be_run_or_overwritten_again(store,monkeypatch):
    state=run_fake(store,make_plan(store),monkeypatch)
    assert state['status']=='COMPLETED'
    for request in [{'type':'run','approve':True,'plan_sha256':state['plan']['sha256']},
                    {'type':'save','text':'change existing case'},{'type':'plan','mode':'rules'}]:
        with pytest.raises(WorkflowError):
            store.action(state['id'],dict(request,expected_revision=state['revision']))
    assert store.get(state['id'])==state


def test_revision_creates_child_preserving_parent_and_locked_beam(store):
    original=make_plan(store);before=copy.deepcopy(original)
    revised=copy.deepcopy(original['spec'])
    revised['goal']={'metric':'screen_radius_um','operator':'<=','target':50,'unit':'um'}
    child=store.action(original['id'],{'type':'revise','expected_revision':original['revision'],
                                     'text':json.dumps(revised),'mode':'rules'})
    assert child['id']!=original['id']
    assert child['family_id']==original['id'] and child['parent_id']==original['id']
    assert child['status']=='PLANNED'
    assert child['spec']['known_parameters']==original['spec']['known_parameters']
    assert store.get(original['id'])==before


def test_revision_that_changes_locked_input_stops_without_overwriting_parent(store):
    original=make_plan(store);before=copy.deepcopy(original)
    revised=copy.deepcopy(original['spec']);revised['known_parameters']['waist_radius_um']=900
    child=store.action(original['id'],{'type':'revise','expected_revision':original['revision'],
                                     'text':json.dumps(revised),'mode':'rules'})
    assert child['status']=='NEEDS_INFORMATION' and child['plan'] is None
    assert child['questions']
    assert store.get(original['id'])==before


@pytest.mark.parametrize('action',['create','save','revise'])
def test_credential_shaped_user_data_is_never_persisted(store,action):
    secret='sk-'+'SyntheticSecretForUnitTestOnly12345'
    original=make_plan(store)
    if action=='create':request=lambda:store.create({'kind':'specified','text':'key '+secret})
    else:request=lambda:store.action(original['id'],{'type':action,'expected_revision':original['revision'],'text':'key '+secret,'mode':'rules'})
    with pytest.raises(WorkflowError):request()
    assert all(secret.encode() not in p.read_bytes() for p in store.root.rglob('*') if p.is_file())


@pytest.mark.parametrize('mode',['no_approval','simulation','no_client'])
def test_paid_planning_cannot_start_without_available_authorized_context(store,mode):
    client=FakeClient({'spec':specification(),'questions':[]});store.owner.product_client=client
    state=store.create({'kind':'specified','text':json.dumps(specification())})
    request={'type':'plan','mode':'live','approve_data':True,'expected_revision':state['revision']}
    if mode=='no_approval':request['approve_data']=False
    elif mode=='simulation':store.owner.simulation_context={'actor':'SIMULATED'}
    else:store.owner.product_client=None
    with pytest.raises(WorkflowError):store.action(state['id'],request)
    assert client.requests==[]


def test_interactive_revisions_can_continue_beyond_the_evaluation_call_cap(store):
    spec=specification();client=FakeClient({'spec':spec,'questions':[]});store.owner.product_client=client
    state=store.create({'kind':'specified','text':json.dumps(spec)})
    state=store.action(state['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':state['revision']})
    assert state['status']=='PLANNED'
    child=store.action(state['id'],{'type':'revise','mode':'live','approve_data':True,'expected_revision':state['revision'],'text':json.dumps(spec)})
    assert child['status']=='PLANNED'
    child=store.action(child['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':child['revision']})
    assert len(client.requests)==3
    assert store.get(state['id'])['family_model_calls']==3
    child=store.action(child['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':child['revision']})
    assert len(client.requests)==4 and client.preflights==4
    assert store.get(state['id'])['family_model_calls']==4
    assert all(e['value']['actual_model_calls']==0 for ident in [state['id'],child['id']] for e in events(store,ident) if e['kind']=='PLAN_DRAFT')


def test_bad_model_draft_is_preserved_as_stopped_not_run(store):
    client=FakeClient({'spec':None,'questions':['What is the waist position?']});store.owner.product_client=client
    state=store.create({'kind':'specified','text':'Unknown waist position.'})
    result=store.action(state['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':state['revision']})
    assert result['status']=='NEEDS_INFORMATION' and result['plan'] is None
    assert result['questions']==['What is the waist position?']
    assert result['model_calls']==1
    assert any(e['kind']=='PLAN_DRAFT' for e in events(store,state['id']))


def test_worker_failure_retains_original_plan_input_and_partial_evidence(store,monkeypatch):
    original=make_plan(store)
    def crash(plan,out):
        Path(out).mkdir(parents=True);(Path(out)/'worker.log').write_text('diagnostic evidence')
        raise ValueError('Synthetic worker failure')
    failed=run_fake(store,original,monkeypatch,crash)
    assert failed['status']=='FAILED'
    assert failed['plan']==original['plan'] and failed['text']==original['text']
    assert 'Synthetic worker failure' in failed['error']
    assert not store.running
    assert (store.folder(original['id'])/'execution/worker.log').read_text()=='diagnostic evidence'


@pytest.mark.parametrize('kind',['save','plan'])
def test_failed_approved_version_cannot_have_original_context_overwritten(store,monkeypatch,kind):
    original=make_plan(store)
    def crash(plan,out):
        Path(out).mkdir(parents=True);(Path(out)/'worker.log').write_text('partial')
        raise ValueError('failed after launch')
    failed=run_fake(store,original,monkeypatch,crash)
    with pytest.raises(WorkflowError):
        store.action(failed['id'],{'type':kind,'expected_revision':failed['revision'],'text':'overwrite old context','mode':'rules'})
    assert store.get(failed['id'])['plan']==original['plan']


def test_model_transport_error_has_a_retained_safe_failure_receipt(store):
    client=FakeClient();client.error=ValueError('Synthetic transport stopped');store.owner.product_client=client
    state=store.create({'kind':'specified','text':'Incomplete stated facts.'})
    try:
        store.action(state['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':state['revision']})
    except (ValueError,WorkflowError):pass
    after=store.get(state['id'])
    assert after['text']==state['text'] and after['model_calls']==1
    recorded=[e for e in events(store,state['id']) if any(word in e['kind'] for word in ['FAIL','ERROR'])]
    assert recorded or after.get('error'), 'Model dispatch failure needs a durable receipt, not only data approval.'
    assert len(client.requests)==1


def test_explanation_rejects_nonexistent_candidate_instead_of_inventing_results(store,monkeypatch):
    state=run_fake(store,make_plan(store),monkeypatch)
    store.owner.product_client=FakeClient({'candidate_ids':['not-a-calculated-candidate'],'next_step':'review_assumptions'})
    result=store.action(state['id'],{'type':'explain','approve_data':True,'expected_revision':state['revision']})
    assert result['explanation']['status']=='REJECTED'
    assert result['result']==state['result']


def test_restart_marks_interrupted_job_failed_without_automatic_retry(store,monkeypatch):
    state=make_plan(store);state['status']='RUNNING';store.save(state)
    monkeypatch.setattr(service,'execute_plan',lambda *a:pytest.fail('restart must not rerun'))
    restored=service.ExperimentStore(store.owner).get(state['id'])
    assert restored['status']=='FAILED'
    assert restored['plan']==state['plan']
    assert '中断' in restored['error']


def test_export_preserves_case_events_and_hash_manifest(store):
    state=make_plan(store)
    with zipfile.ZipFile(io.BytesIO(store.export(state['id']))) as archive:
        manifest=json.loads(archive.read('EXPORT_MANIFEST.json'))
        assert manifest['case_id']==state['id']
        assert 'case.json' in manifest['files']
        assert any(name.startswith('events/') for name in manifest['files'])
        assert json.loads(archive.read('case.json'))['plan']==state['plan']

def test_numeric_worker_receives_no_provider_credentials_or_untrusted_pythonpath(monkeypatch,tmp_path):
    from contextlib import nullcontext
    from photonguard.experiments import executor
    from photonguard.experiments.planner import build_plan
    spec=specification();spec['allowed_variables']['focal_length_mm']=[100]
    plan=build_plan(spec)
    monkeypatch.setenv('DEEPSEEK_API_KEY','synthetic-provider-key')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-other-provider-key')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','synthetic-cloud-secret')
    monkeypatch.setenv('PYTHONPATH','/untrusted/user/modules')
    monkeypatch.setattr(executor,'solver_mutex',lambda:nullcontext())
    seen=[]
    def fake_process(command,**kwargs):
        seen.append(kwargs['env'])
        Path(command[-1]).write_text(json.dumps({'metrics':{'screen_radius_um':40},'data':{},
                                               'all_checks_passed':True,'resources':{'fast_evaluations':1}}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(executor.subprocess,'run',fake_process)
    result=executor.execute_plan(plan,tmp_path/'fake-execution')
    assert result['status']=='RUN_COMPLETED' and len(seen)==1
    assert result['resources']['output_bytes']==sum(p.stat().st_size for p in (tmp_path/'fake-execution').rglob('*') if p.is_file())
    manifest=json.loads((tmp_path/'fake-execution/manifest.json').read_text())
    assert 'manifest.json' not in manifest['files']
    environment=seen[0]
    assert not {'DEEPSEEK_API_KEY','OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY'} & set(environment)
    assert '/untrusted/user/modules' not in environment['PYTHONPATH']
    for path in (tmp_path/'fake-execution').rglob('*'):
        if path.is_file():assert b'synthetic-provider-key' not in path.read_bytes()


def test_failed_numerical_candidate_explanation_cannot_claim_target_achievement(store,monkeypatch):
    state=run_fake(store,make_plan(store),monkeypatch)
    failed=state['result']['candidates'][0]
    failed['all_checks_passed']=False
    failed['goal']['met']=True
    failed['goal']['operator']='<='
    failed['goal']['target']=50
    store.save(state)
    store.owner.product_client=FakeClient({'candidate_ids':[failed['id']],'next_step':'review_assumptions'})
    result=store.action(state['id'],{'type':'explain','approve_data':True,'expected_revision':state['revision']})
    explanation=result['explanation']
    assert explanation['status']=='REJECTED' or ('未通过' in explanation['text'] and '达到目标。' not in explanation['text'])

def test_explanation_transport_failure_keeps_computation_and_failure_receipt(store,monkeypatch):
    state=run_fake(store,make_plan(store),monkeypatch)
    client=FakeClient();client.error=ValueError('Synthetic explanation transport stopped')
    store.owner.product_client=client
    try:
        store.action(state['id'],{'type':'explain','approve_data':True,'expected_revision':state['revision']})
    except (ValueError,WorkflowError):pass
    after=store.get(state['id'])
    assert after['result']==state['result'] and after['model_calls']==1
    receipts=[e for e in events(store,state['id']) if any(word in e['kind'] for word in ['FAIL','ERROR'])]
    assert receipts or after.get('explanation',{}).get('status') in ('FAILED','REJECTED')
    assert len(client.requests)==1


def test_supplement_preserves_original_facts_and_invalidates_old_plan(store):
    original=make_plan(store);original['error']='old error';store.save(original)
    client=FakeClient();store.owner.product_client=client
    result=store.action(original['id'],{'type':'supplement','expected_revision':original['revision'],'text':'屏幕位置请再核对。'})
    assert result['text']==original['text']+'\n\n补充资料：\n屏幕位置请再核对。'
    assert result['status']=='DRAFT' and result['plan'] is None and result['spec'] is None
    assert 'error' not in result and not client.requests
    receipt=next(e for e in events(store,original['id']) if e['kind']=='FACTS_SUPPLEMENTED')
    assert receipt['value']['original_text']==original['text']
    with pytest.raises(WorkflowError):
        store.action(result['id'],{'type':'run','expected_revision':result['revision'],'approve':True,'plan_sha256':original['plan']['sha256']})


@pytest.mark.parametrize('data',[
    {'text':'位置0 mm','mode':'live'},
    {'text':'位置0 mm','mode':'unknown'},
    {'text':'  '},
    {'text':'a'*24000},
    {'text':'sk-'+'x'*32},
])
def test_invalid_supplement_does_not_change_saved_facts(store,data):
    state=make_plan(store)
    with pytest.raises(WorkflowError):
        store.action(state['id'],{'type':'supplement','expected_revision':state['revision'],**data})
    assert store.get(state['id'])==state


def test_approved_failed_case_cannot_be_supplemented(store):
    state=make_plan(store);state.update(status='FAILED',approved_plan_sha256=state['plan']['sha256']);store.save(state)
    with pytest.raises(WorkflowError):
        store.action(state['id'],{'type':'supplement','expected_revision':state['revision'],'text':'新参数'})
    assert store.get(state['id'])['text']==state['text']


def test_supplement_continues_one_family_and_does_not_run_solver(store,monkeypatch):
    monkeypatch.setattr(service,'execute_plan',lambda *a:pytest.fail('planning must not run a solver'))
    spec=specification()
    client=FakeClient({'spec':None,'questions':['请补充束腰位置。']});store.owner.product_client=client
    state=store.create({'kind':'specified','text':'原资料待补充。'})
    state=store.action(state['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':state['revision']})
    client.answer={'spec':spec,'questions':[]}
    state=store.action(state['id'],{'type':'supplement','mode':'live','approve_data':True,'text':json.dumps(spec),'expected_revision':state['revision']})
    assert state['status']=='PLANNED' and state['family_model_calls']==2 and state['result'] is None
    assert state['text'].startswith('原资料待补充。')
    state=store.action(state['id'],{'type':'plan','mode':'live','approve_data':True,'expected_revision':state['revision']})
    continued=store.action(state['id'],{'type':'supplement','mode':'live','approve_data':True,'text':'其余资料不变。','expected_revision':state['revision']})
    assert continued['status']=='PLANNED'
    assert continued['text'].endswith('其余资料不变。') and len(client.requests)==4
    assert continued['family_id']==state['family_id'] and continued['family_model_calls']==4


@pytest.mark.parametrize('error_type',[WorkflowError,ValueError])
def test_financial_preflight_still_stops_dispatch_and_retains_supplement(store,error_type):
    state=make_plan(store);client=FakeClient();store.owner.product_client=client
    def no_funds():raise error_type('累计预算不足，未发送请求')
    client.preflight=no_funds
    result=store.action(state['id'],{'type':'supplement','mode':'live','approve_data':True,'text':'其余资料不变。','expected_revision':state['revision']})
    assert result['status']=='NEEDS_INFORMATION' and '累计预算不足' in result['error']
    assert result['text'].endswith('其余资料不变。') and client.requests==[]
    assert result['model_calls']==0


def test_failed_ai_after_supplement_keeps_both_inputs_and_never_retries(store):
    state=make_plan(store);client=FakeClient();client.error=ValueError('synthetic transport failure');store.owner.product_client=client
    result=store.action(state['id'],{'type':'supplement','mode':'live','approve_data':True,'text':'补充束腰位置为0 mm。','expected_revision':state['revision']})
    assert result['status']=='NEEDS_INFORMATION'
    assert result['text'].startswith(state['text']) and result['text'].endswith('补充束腰位置为0 mm。')
    assert len(client.requests)==1 and result['result'] is None


def test_grounded_explanation_keeps_fast_and_independent_values_separate(store,monkeypatch):
    state=run_fake(store,make_plan(store),monkeypatch)
    c=state['result']['candidates'][0]
    c['goal'].update(metric='reflectance',value=.91,unit='fraction',source={'label':'TMM实际采样'})
    c['verification']={'numerical_status':'NUMERICAL_PASS','goal_meep':{'value':.909}}
    store.save(state)
    store.owner.product_client=FakeClient({'candidate_ids':[c['id']],'next_step':'review_assumptions'})
    result=store.action(state['id'],{'type':'explain','approve_data':True,'expected_revision':state['revision']})
    text=result['explanation']['text']
    assert result['explanation']['status']=='GROUNDED_IN_ACTUAL_RESULTS'
    assert '0.91 fraction（TMM实际采样）' in text
    assert '独立Meep值为 0.909' in text


def test_direct_goal_revision_needs_no_ai_and_preserves_original_physics(store,monkeypatch):
    original=run_fake(store,make_plan(store),monkeypatch)
    goal={'metric':'screen_radius_um','operator':'<=','target':45,'unit':'um'}
    child=store.action(original['id'],{'type':'revise_goal','expected_revision':original['revision'],'goal':goal})
    assert child['status']=='PLANNED' and child['result'] is None and child['model_calls']==0
    assert child['parent_id']==original['id']
    assert child['spec']['known_parameters']==original['spec']['known_parameters']
    assert child['spec']['allowed_variables']==original['spec']['allowed_variables']
    assert child['plan']['sha256']!=original['plan']['sha256']
    assert child['plan']['goal']==goal and store.get(original['id'])==original
    with pytest.raises(WorkflowError):
        store.action(child['id'],{'type':'run','expected_revision':child['revision'],'approve':True,'plan_sha256':original['plan']['sha256']})


def test_invalid_direct_goal_creates_no_empty_revision_record(store):
    state=make_plan(store);before=list(store.root.iterdir())
    with pytest.raises(ValueError):
        store.action(state['id'],{'type':'revise_goal','expected_revision':state['revision'],'goal':{'metric':'unsupported','operator':'minimize'}})
    assert list(store.root.iterdir())==before
    with pytest.raises(WorkflowError):
        store.action(state['id'],{'type':'revise_goal','expected_revision':state['revision'],'goal':state['spec']['goal'],'known_parameters':{}})


def test_csv_export_checks_saved_execution_before_disclosing_a_comparison(store):
    from photonguard.core import digest
    state=make_plan(store);result=fake_result(state['plan']);state.update(status='COMPLETED',result=result);store.save(state)
    folder=store.folder(state['id'])/'execution';folder.mkdir()
    raw=json.dumps(result).encode();(folder/'result.json').write_bytes(raw)
    import hashlib
    (folder/'manifest.json').write_text(json.dumps({'files':{'result.json':hashlib.sha256(raw).hexdigest()}}))
    assert b'screen_radius_um' in store.export_table(state['id'])
    with zipfile.ZipFile(io.BytesIO(store.export(state['id']))) as archive:
        manifest=json.loads(archive.read('EXPORT_MANIFEST.json'))
        assert {'tables/candidates.csv','tables/curves.csv','tables/report.json'}<=set(manifest['files'])
        for name,h in manifest['files'].items():assert hashlib.sha256(archive.read(name)).hexdigest()==h
    (folder/'result.json').write_text('{}')
    with pytest.raises(WorkflowError,match='证据'):store.export_table(state['id'])
