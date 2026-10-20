import copy,json
from pathlib import Path
from photonguard.experiments import case_study as study
from photonguard.experiments.case_adaptation import adapt
from photonguard.experiments.optics import evaluate
from photonguard.experiments.goals import assess,rank

def calculated(request):
    plan=adapt(request,mode='specified')['plan'];rows=[]
    for p in plan['candidates']:
        row={**p,**evaluate(plan['domain'],p['parameters']),'status':'RUN_COMPLETED'};row['goal']=assess(row,plan['goal']);rows.append(row)
    result={'plan_sha256':plan['sha256'],'candidates':rows,'winner_id':rank(rows,plan['goal'])[0],'resources':{'fast_evaluations':len(rows),'actual_fdtd_runs':0,'output_bytes':100,'fdtd_attempts_reserved':0}}
    return {'id':'step-1','domain':plan['domain'],'spec':plan['spec'],'plan':plan,'result':result}

def request():return {'case_id':'G04','parameters':{'wavelength_nm':700,'waist_radius_um':520,'waist_z_mm':-20,'screen_distance_mm':110},'values':[90,110,140],'goal':{'metric':'screen_radius_um','operator':'<=','target':20}}

def test_correct_unmet_goal_is_completed_judgment_not_design_success():
    r=calculated(request());c=next(c for c in r['result']['candidates'] if c['id']==r['result']['winner_id'])
    t={'id':'C07','arm':'A','status':'REPORTED','runs':[r],'final_record':r,'report':{'record':'last','winner_id':c['id'],'metric_source':'candidate.goal.value','metric_value':c['goal']['value'],'goal_met':False,'text':'目录内未达标；不代表全局无解。'},'model_calls':2,'actual_provider_attempts':0,'resources':{},'invalid_questions':0}
    oracle={'requests':[request()],'expected_run_count':1,'stop':None,'restore':False}
    s=study.score_trial(t,oracle);assert s['task_completed'] and s['correctly_reported_unmet_goal'] and s['design_goal_met'] is False
    # Raw-tool callers need not copy the library's optional plotting extent;
    # an unused FDTD allowance is not an independent Gaussian validation.
    r['spec']['known_parameters'].pop('z_max_mm',None)
    r['spec']['resource_budget']['max_meep_validations']=1
    assert study.score_trial(t,oracle)['task_completed']
    r['spec']['known_parameters']['waist_z_mm']=0
    assert not study.score_trial(t,oracle)['task_completed']
    r['spec']['known_parameters']['waist_z_mm']=-20
    t['report']['metric_value']+=1;assert not study.score_trial(t,oracle)['task_completed']

def test_stop_and_incomplete_record_are_distinct_from_design_success():
    t={'id':'C09','arm':'G','status':'EXPLICIT_STOP','stop_reason':'束腰位置未知，不能计算','runs':[],'model_calls':1,'actual_provider_attempts':0,'resources':{},'invalid_questions':0}
    oracle={'requests':[],'expected_run_count':0,'stop':'missing_waist_z','restore':False}
    s=study.score_trial(t,oracle);assert s['correct_stop'] and s['task_completed'] and s['design_goal_met'] is None
    t['stop_reason']='费用太贵';assert not study.score_trial(t,oracle)['task_completed']

def test_two_arms_receive_identical_library_and_public_tools(tmp_path):
    payloads=[]
    def call(arm,ident,turn,payload):
        payloads.append(copy.deepcopy(payload));return {'action':'stop','reason':'束腰位置未知'}
    task={'id':'C09','request':'真实高斯束腰位置未知','followups':[]}
    for arm in ('A','G'):study.run_trial(task,arm,tmp_path/arm,call)
    assert payloads[0]['messages'][1]==payloads[1]['messages'][1]
    first=json.loads(payloads[0]['messages'][1]['content']);assert len(first['cases'])==4
    assert 'private-oracle' not in json.dumps(payloads)

def test_incomplete_calculation_is_retained_as_failure():
    r=calculated(request());r['result']['candidates'][0].pop('goal')
    t={'id':'C07','arm':'G','status':'CALL_LIMIT_STOP','runs':[r],'model_calls':3,'actual_provider_attempts':0,'resources':{},'invalid_questions':0}
    s=study.score_trial(t,{'requests':[request()],'expected_run_count':1,'stop':None,'restore':False})
    assert not s['task_completed']
