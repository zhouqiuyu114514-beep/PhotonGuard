"""Study control flow tests use explicit synthetic model/solver callbacks only."""
import copy
import json
from pathlib import Path

import pytest

from photonguard.experiments import study
from photonguard.experiments.planner import build_plan

FIXTURES=Path(__file__).resolve().parents[1]/'research'/'multiscene-study'


def fixtures():
    return (study.read(FIXTURES/'formal-public.json'),study.read(FIXTURES/'private-oracle.json'),
            study.read(FIXTURES/'dialogue-cards.json'))


def fake_executor(oracle):
    def execute(plan,out_dir):
        truth=next(v for v in oracle.values() if v['reference_spec']['domain']==plan['domain'] and v['reference_spec']['goal']==plan['goal'] and v['reference_spec']['known_parameters']==plan['spec']['known_parameters'])
        rows=[]
        for candidate in plan['candidates']:
            expected=next(v for v in truth['candidates'] if v['variable_values']==candidate['changes'])
            row=copy.deepcopy(candidate)
            row.update(status='RUN_COMPLETED',all_checks_passed=True,engine='EXPLICIT_TEST_STUB',
                       goal={'value':expected['metric_value'],'met':expected['goal_met'],'metric':plan['goal']['metric']},
                       verification={'status':'RUN_COMPLETED','numerical_status':'NUMERICAL_PASS','goal_meep':{'met':expected['goal_met']}})
            rows.append(row)
        winners=[r['id'] for r in rows if r['changes'] in truth['acceptable_winner_variable_values']]
        return {'status':'RUN_COMPLETED','candidates':rows,'winner_id':winners[0],'ranking':winners,
                'resources':{'fast_evaluations':0,'actual_fdtd_runs':0,'test_stub':True}}
    return execute


def fake_model(oracle,cards,seen=None):
    def call(arm,identifier,turn,payload):
        if seen is not None:seen.append((arm,identifier,turn,copy.deepcopy(payload)))
        last=json.loads(payload['messages'][-1]['content'])
        if 'actual_tool_result' in last:
            result=last['actual_tool_result'];winner=next(c for c in result['candidates'] if c['id']==result['winner_id'])
            return {'action':'report','winner_id':winner['id'],'evidence_candidate_id':winner['id'],
                    'metric_value':winner['goal']['value'],'goal_met':winner['goal']['met'],
                    'text':'EXPLICIT TEST STUB: finite candidates under the stated assumptions.'}
        if turn==1 and identifier in cards:
            return {'action':'clarify','missing_fields':cards[identifier]['required_fields'],'questions':['请确认'+cards[identifier]['aliases'][0]]}
        return {'action':'run','spec':copy.deepcopy(oracle[identifier]['reference_spec'])}
    return call


def test_corpus_has_fixed_balanced_new_instances():
    tasks,oracle,cards=fixtures()
    assert len(tasks)==12 and len(study.read(FIXTURES/'development-public.json'))==4
    assert len({t['id'] for t in tasks})==12
    for domain in ('film','diffraction','gaussian'):
        assert {t['category'] for t in tasks if t['domain']==domain}=={'complete','missing','comparison','revision'}
    assert set(cards)=={'M04','M05','M06'}
    for task in tasks:
        plan=build_plan(oracle[task['id']]['reference_spec'],parent=task.get('parent'))
        assert len(plan['candidates'])==len(oracle[task['id']]['candidates'])
        if plan['goal']['operator'] not in ('minimize','maximize'):
            assert any(c['goal_met'] for c in oracle[task['id']]['candidates'])


def test_freeze_detects_mutation_and_cannot_overwrite(tmp_path):
    frozen=tmp_path/'frozen';study.freeze_suite(FIXTURES,frozen)
    study.verify_suite(frozen)
    with pytest.raises(FileExistsError):study.freeze_suite(FIXTURES,frozen)
    (frozen/'formal-public.json').write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):study.verify_suite(frozen)


@pytest.mark.parametrize('identifier',['M01','M05','M09','M11','M12'])
@pytest.mark.parametrize('arm',['A','G'])
def test_complete_control_flow_and_identical_public_observations(tmp_path,identifier,arm):
    tasks,oracle,cards=fixtures();task=next(t for t in tasks if t['id']==identifier);seen=[]
    trial=study.run_trial(task,arm,tmp_path/'run',fake_model(oracle,cards,seen),
                         public_tools=(FIXTURES/'public-tools.md').read_text(encoding='utf-8'),
                         dialogue_card=cards.get(identifier),build=build_plan,execute=fake_executor(oracle))
    assert trial['status']=='RUN_COMPLETED'
    assert trial['model_calls']==(3 if identifier in cards else 2)
    assert trial['actual_provider_attempts']==0
    score=study.score_trial(trial,oracle[identifier])
    assert score['end_to_end_goal_completed'],score
    assert not score['failed_components']
    for _,_,_,payload in seen:
        serialized=json.dumps(payload,ensure_ascii=False)
        assert 'private-oracle' not in serialized
        assert 'acceptable_winner_variable_values' not in serialized
        assert 'relative_metric_tolerance' not in serialized
    if identifier in cards:
        assert cards[identifier]['reply'] not in seen[0][3]['messages'][1]['content']


def test_cannot_execute_missing_fact_before_user_clarifies(tmp_path):
    tasks,oracle,cards=fixtures();task=next(t for t in tasks if t['id']=='M06');executed=[]
    def wrong(*args):return {'action':'run','spec':oracle['M06']['reference_spec']}
    trial=study.run_trial(task,'A',tmp_path/'run',wrong,public_tools='public',dialogue_card=cards['M06'],
                         build=build_plan,execute=lambda *args:executed.append(args))
    assert trial['status']=='CALL_LIMIT_STOP'
    assert not executed
    assert trial['attempted_run_before_required_clarification']
    assert not study.score_trial(trial,oracle['M06'])['clarification_correct']


def test_same_fact_card_does_not_leak_on_unrelated_question():
    _,_,cards=fixtures()
    assert study.clarification_reply({'action':'clarify','questions':['你喜欢什么颜色？']},cards['M06'],False) is None
    answer=study.clarification_reply({'questions':['束腰位置在哪里？']},cards['M06'],False)
    assert answer==cards['M06']['reply']
    assert study.clarification_reply({'questions':['束腰位置？']},cards['M06'],True) is None


def test_explicit_stop_is_recorded_without_retry_or_solver(tmp_path):
    tasks,_,_=fixtures()
    trial=study.run_trial(tasks[0],'G',tmp_path/'stop',lambda *args:{'action':'stop','reason':'Required data unavailable'},
                          public_tools='public',execute=lambda *args:pytest.fail('no solver on stop'))
    assert trial['status']=='EXPLICIT_STOP' and trial['model_calls']==1 and trial['solver_executions']==0


@pytest.mark.parametrize('identifier',['R01','R02','R03','R04','R05','R06'])
@pytest.mark.parametrize('arm',['A','G'])
def test_v2_regression_contract_is_executable_and_metric_source_is_explicit(tmp_path,identifier,arm):
    folder=FIXTURES.parent/'multiscene-regression-v2'
    tasks=study.read(folder/'formal-public.json');oracle=study.read(folder/'private-oracle.json');cards=study.read(folder/'dialogue-cards.json')
    task=next(t for t in tasks if t['id']==identifier)
    assert '此参数' not in task['text']
    underlying=fake_model(oracle,cards)
    def model(*args):
        answer=underlying(*args)
        if answer.get('action')=='report':answer['metric_source']='candidate.goal.value'
        return answer
    trial=study.run_trial(task,arm,tmp_path/'v2',model,public_tools=(folder/'public-tools.md').read_text(),
                          dialogue_card=cards.get(identifier),execute=fake_executor(oracle))
    score=study.score_trial(trial,oracle[identifier])
    assert score['end_to_end_goal_completed'],score
    trial['report']['metric_source']='candidate.verification.goal_meep.value'
    assert not study.score_trial(trial,oracle[identifier])['report_metric_source_correct']


def test_process_success_and_fabricated_report_are_not_goal_success(tmp_path):
    tasks,oracle,cards=fixtures();task=tasks[2]
    trial=study.run_trial(task,'G',tmp_path/'run',fake_model(oracle,cards),public_tools='public',execute=fake_executor(oracle))
    assert study.score_trial(trial,oracle[task['id']])['end_to_end_goal_completed']
    bad=copy.deepcopy(trial);bad['result']['candidates'][0]['all_checks_passed']=False
    assert not study.score_trial(bad,oracle[task['id']])['end_to_end_goal_completed']
    bad=copy.deepcopy(trial);bad['report']['evidence_candidate_id']='invented-candidate'
    assert not study.score_trial(bad,oracle[task['id']])['report_consistent']
    bad=copy.deepcopy(trial);bad['report']['metric_value']=0
    assert not study.score_trial(bad,oracle[task['id']])['report_consistent']


def test_failed_meep_not_relabelled_pass(tmp_path):
    tasks,oracle,cards=fixtures();task=tasks[0]
    trial=study.run_trial(task,'G',tmp_path/'run',fake_model(oracle,cards),public_tools='public',execute=fake_executor(oracle))
    trial['result']['candidates'][0]['verification']['numerical_status']='NUMERICAL_FAIL'
    score=study.score_trial(trial,oracle[task['id']])
    assert score['numeric_checks_passed']
    assert not score['independent_verification_passed']
    assert not score['end_to_end_goal_completed']


def test_private_constraint_audit_catches_changed_beam_for_plain_agent(tmp_path):
    tasks,oracle,cards=fixtures();task=tasks[-1]
    trial=study.run_trial(task,'A',tmp_path/'run',fake_model(oracle,cards),public_tools='public',execute=fake_executor(oracle))
    trial['plan']['spec']['known_parameters']['waist_radius_um']=300
    score=study.score_trial(trial,oracle[task['id']])
    assert not score['constraints_preserved']
    assert not score['end_to_end_goal_completed']


def test_provider_failure_stops_suite_no_retry_or_replacement(tmp_path):
    frozen=tmp_path/'frozen';study.freeze_suite(FIXTURES,frozen);calls=[]
    def failure(*args):calls.append(args);raise RuntimeError('simulated unavailable provider, no network')
    summary=study.run_suite(frozen,tmp_path/'results',failure,phase='formal',task_limit=6)
    assert len(calls)==1
    assert summary['status']=='STOPPED_RETAINED'
    assert len(summary['scores'])==24
    assert all(v['full_task_denominator']==12 for v in summary['totals'].values())
    assert all(v['selected_task_denominator']==6 for v in summary['totals'].values())
    assert sum(s['execution_status']=='NOT_RUN_BUDGET' for s in summary['scores'])==12


def test_offline_full_suite_cap_and_tie_are_retained(tmp_path):
    tasks,oracle,cards=fixtures();frozen=tmp_path/'frozen';study.freeze_suite(FIXTURES,frozen)
    summary=study.run_suite(frozen,tmp_path/'results',fake_model(oracle,cards),execute=fake_executor(oracle))
    assert summary['status']=='COMPLETED' and summary['tie']
    assert all(v['end_to_end_goal_completed']==12 for v in summary['totals'].values())
    assert all(v['model_calls']==27 for v in summary['totals'].values())
    assert all(v['actual_provider_attempts']==0 for v in summary['totals'].values())
    with pytest.raises(FileExistsError):
        study.run_suite(frozen,tmp_path/'results',fake_model(oracle,cards),execute=fake_executor(oracle))
