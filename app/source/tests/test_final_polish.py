"""Offline artificial-state regression. No API, fits or optical worker launches."""
import copy
import json
from contextlib import contextmanager
from pathlib import Path
import threading
import importlib.util
import pytest
from test_inverse_journeys import store,act,data,planned,wait
from test_research_advice import receive
from photonguard.core import digest
from photonguard.workflow import WorkflowError
from photonguard.experiments import observation_group as ow,inverse_models as m
from photonguard.experiments import research_advice as ra,research_actions as actions,advice_contract as contract,task_view,inverse_report,executor


def artificial_plan(store,all_blocked=False):
    _,cfg,raw=data(m.SLIT,count=21)
    s=ow.create(store,{'model':m.SLIT,'csv_text':raw,'source_name':'ARTIFICIAL UNIT TEST ONLY'})
    s['inverse_settings']=cfg;s=planned(store,s)
    s.update(status='COMPLETED',inverse_result={'id':'ARTIFICIAL_NOT_COMPUTED','estimated_parameters':{},'warnings':[],
        'resources':{'actual_residual_calls':0,'local_optimizations':0},'data':[]},
        acquisition_constraints={'points':61,'max_abs_x_mm':4},decision_preferences={'max_travel_mm':3,'max_points':61})
    plan={'plans':[{'id':'baseline','label':'基础扫描','role':'BASELINE','cost':{'points':61,'travel_mm':1},'execution_allowed':not all_blocked},
                   {'id':'medium','cost':{'points':61,'travel_mm':4.5},'execution_allowed':False,'selection_reason':'超出声明的移动上限，不能执行。'}],
          'decision_preferences':s['decision_preferences'],'constraints':s['acquisition_constraints'],'baseline_id':'baseline'}
    plan['sha256']=digest(plan);s['measurement_plan']=plan;store.save(s);return s


def prepare(store,s):
    a=task_view.advice(s);return act(store,s,'inverse_research_prepare',suggestion_sha256=a['suggestion_sha256'],action_id=a['primary']['id'])


def test_feasibility_uses_saved_flag_and_binds_prompt_to_current_version(store,monkeypatch):
    s=artificial_plan(store);before=copy.deepcopy(s);availability=actions.proposal_availability(s)
    assert s==before and availability['currently_feasible_proposal_ids']==['baseline']
    blocked=availability['blocked_proposals'][0]
    assert blocked['id']=='medium' and blocked['measurements'][0]['value']==4.5 and blocked['measurements'][0]['unit']=='mm'
    assert blocked['declared_limits'][0]['value']==3
    assert availability['input_binding']==actions.binding(s)
    class Client:
        def complete(self,*args):return {'assistant':{'content':json.dumps(contract.fixture())}}
    monkeypatch.setattr(store,'_model',lambda *args:Client())
    out=ra.guide(store,s,{'text':'在当前资源内决定下一步','approve_data':True})
    p=next((store.folder(s['id'])/'ai-requests').glob('*/public-input.json'));public=json.loads(p.read_text())
    e=next(v for v in public['evidence_catalog'] if v['id']=='E3')
    assert e['currently_feasible_proposal_ids']==['baseline'] and e['input_binding']['proposal_sha256']==s['measurement_plan']['sha256']
    assert out['inverse_ledger']==before['inverse_ledger']


def test_blocked_primary_preserved_with_program_options_not_substituted(store):
    s=receive(store,artificial_plan(store),contract.fixture('propose_followup',proposal='medium'),'只在当前条件内选下一次')
    a=task_view.advice(s);assert a['primary']['proposal_id']=='medium' and not a['primary']['ready']
    assert a['source']=='MODEL_EXPLICIT_SELECTION' and a['feasible_alternatives'][0]['source']=='PROGRAM_FEASIBILITY_LIST'
    assert a['feasible_alternatives'][0]['id']=='baseline'
    with pytest.raises(WorkflowError):prepare(store,s)
    exported=inverse_report.summary(s).decode();assert '这项主建议当前不能准备' in exported and '程序列出的可行备选' in exported
    assert not s.get('task_plan') and s['inverse_ledger']['acquisitions_reserved']==0


def test_one_feasible_can_prepare_but_not_run_without_separate_approval(store):
    s=receive(store,artificial_plan(store),contract.fixture('propose_followup',proposal='baseline'),'在当前条件内选下一步')
    assert task_view.advice(s)['primary']['ready'];out=prepare(store,s)
    assert task_view.summary(out)['state']=='WAITING_DATA' and not out.get('task_plan')
    assert out['inverse_ledger']['acquisitions_reserved']==0 and out['inverse_ledger']['fit_runs_reserved']==0
    with pytest.raises(WorkflowError):act(store,out,'inverse_append',approve=False)


def test_no_feasible_plan_keeps_limits_and_allows_stop(store):
    s=artificial_plan(store,all_blocked=True);before=copy.deepcopy(s['decision_preferences'])
    s=receive(store,s,contract.fixture('propose_followup',proposal='medium'),'在原限制内继续')
    a=task_view.advice(s);assert not a['feasible_alternatives'] and '没有可行备选' in a['feasible_alternatives_note']
    with pytest.raises(WorkflowError):prepare(store,s)
    s=receive(store,s,contract.fixture('stop'),'现在停止');s=prepare(store,s)
    assert task_view.summary(s)['state']=='STOPPED' and not task_view.advice(s)['feasible_alternatives']
    assert s['decision_preferences']==before and s['inverse_ledger']['fit_runs_reserved']==0


def test_discussion_of_blocked_proposal_is_readonly_not_execution(store):
    s=receive(store,artificial_plan(store),contract.fixture('explain',proposal='medium'),'只讨论如果放宽行程会如何，不执行')
    assert task_view.advice(s)['primary']['ready'];out=prepare(store,s)
    assert out['research_origin']['status']=='READ_ONLY_REVIEWED'
    assert out['decision_preferences']['max_travel_mm']==3 and not out.get('task_plan')
    assert out['inverse_ledger']['acquisitions_reserved']==0


def test_changed_constraints_reject_old_reply_and_old_qualification(store):
    s=artificial_plan(store);ctx=ra.capture(store,s,'选择baseline')
    latest=receive(store,s,{'updates':[{'id':'U1','field':'preference.max_travel_mm','value':2,'quote':'最大行程2毫米','correction':False}],
        **{k:v for k,v in contract.fixture('explain').items() if k!='updates'}},'最大行程2毫米')
    assert not latest.get('measurement_plan')
    before=copy.deepcopy(latest);out=ra.receive(store,s,'选择baseline',{'assistant':{'content':json.dumps(contract.fixture('propose_followup',proposal='baseline'))}},ctx)
    assert out==before and not actions.proposal_availability(out)['currently_feasible_proposal_ids']


def test_atomic_lock_contention_starts_no_worker_and_keeps_reserved_budget(store,monkeypatch):
    # Real lock, no optical process. Main thread holds; worker thread cannot acquire.
    _,cfg,raw=data(m.GAUSSIAN,count=9)
    s=ow.create(store,{'model':m.GAUSSIAN,'csv_text':raw,'source_name':'OFFLINE LOCK TEST'})
    s['inverse_settings']=cfg;s=planned(store,s);raw_before=(store.folder(s['id'])/'scan-0.csv').read_bytes()
    monkeypatch.setattr(ow.subprocess,'run',lambda *a,**kw:pytest.fail('Worker must not launch during lock contention'))
    with executor.solver_mutex():
        out=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    assert out['status']=='FAILED' and out['inverse_failure_type']=='SolverBusyError' and out['inverse_worker_started'] is False
    assert '本次未启动计算' in task_view.summary(out)['pause_reason']
    assert out['inverse_ledger']['fit_runs_reserved']==1 and out['inverse_ledger']['actual_residual_calls']==0
    assert (store.folder(s['id'])/'scan-0.csv').read_bytes()==raw_before
    assert not (store.folder(s['id'])/'inverse-execution/worker.log').exists()
    child=act(store,out,'inverse_revise');child=planned(store,child)
    assert child['status']=='PLANNED' and child['inverse_plan']['sha256']==s['inverse_plan']['sha256']
    assert store.get(out['id'])['status']=='FAILED' and ow.root_record(store,child)['inverse_ledger']['fit_runs_reserved']==1
    assert child['groups']==out['groups'] and not child.get('inverse_approved_sha256')


def sequence_module():
    spec=importlib.util.spec_from_file_location('development_sequence',Path(__file__).parents[1]/'tools/run_development_sequence.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_development_sequence_stops_on_busy_without_dispatch(monkeypatch):
    sequence=sequence_module()
    @contextmanager
    def busy():raise executor.SolverBusyError('busy');yield
    monkeypatch.setattr(sequence,'solver_mutex',busy)
    monkeypatch.setattr(sequence.subprocess,'run',lambda *a,**kw:pytest.fail('Busy stage must not dispatch'))
    assert sequence.run([{'name':'regression','kind':'solver_regression','argv':['not-started']}])==2


def test_development_sequence_failure_does_not_start_following_journey(monkeypatch):
    from types import SimpleNamespace
    sequence=sequence_module();seen=[]
    monkeypatch.setattr(sequence.subprocess,'run',lambda argv,**kw:(seen.append(argv) or SimpleNamespace(returncode=3)))
    stages=[{'name':'check','kind':'read_only','argv':['first']},{'name':'journey','kind':'user_journey','argv':['second']}]
    assert sequence.run(stages)==3 and seen==[['first']]
