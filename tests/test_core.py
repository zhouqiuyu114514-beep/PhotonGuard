import copy
from pathlib import Path
import pytest
from photonguard.core import *
from photonguard.agent import apply_patch,propose_patch,UnconfiguredModelBackend
from photonguard.checks import static_checks,aggregate
ROOT=Path(__file__).parents[1]
@pytest.fixture
def task():return load(ROOT/'examples/film_n2/task.json')
@pytest.fixture
def candidate():return load(ROOT/'examples/film_n2/candidate.json')
def test_valid(task,candidate):
 assert task_problem(task) is None and candidate_problem(candidate) is None
 assert consistency(task,candidate)
def test_intent_not_inferred(task,candidate):
 task['layers'][0]['n']=None
 assert task_problem(task)['status']=='INCONCLUSIVE'
def test_epsilon_legal_without_wrong_intent(task,candidate):
 candidate['layers'][0].update(material_kind='epsilon',material_value=2.)
 assert not consistency(task,candidate)
 task['layers'][0]['n']=2**.5
 assert consistency(task,candidate)
@pytest.mark.parametrize('key,value',[('angle_deg',20),('dimensions',2),('lossless',False),('dispersive',True),('isotropic',False),('n_exit',1.5),('mu',2),('dimensions',True)])
def test_scope(task,key,value):
 task['physics'][key]=value;assert task_problem(task)['status']=='UNSUPPORTED'
@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,-1,0,10])
def test_invalid_index(task,value):
 task['layers'][0]['n']=value;assert task_problem(task)
@pytest.mark.parametrize('field',['numerics','workflow'])
@pytest.mark.parametrize('bad',[None,[],42,'bad'])
def test_malformed_candidate(candidate,field,bad):
 candidate[field]=bad;assert candidate_problem(candidate)['status']=='UNSUPPORTED'
def test_unknown_fields(task,candidate):
 task['ignore_policy']=True;candidate['shell']='rm';assert task_problem(task);assert candidate_problem(candidate)
def test_lock(tmp_path,task):
 p=tmp_path/'t.json';l=tmp_path/'lock.json';write_json(p,task);lock=lock_task(p,l)
 assert verify_lock(task,lock)
 task['layers'][0]['n']=3;assert not verify_lock(task,lock)
def test_half_time_not_false_failure(task,candidate):
 candidate['workflow']['reference_time_factor']=.5
 assert aggregate(static_checks(task,candidate))=='PASS'
def test_patch_task_unchanged(task,candidate):
 candidate['layers'][0].update(material_kind='epsilon',material_value=2.)
 r={'task_hash':digest(task),'candidate_hash':digest(candidate),'status':'FAIL','run_id':'test'}
 patch=propose_patch(task,candidate,r);h=digest(task)
 fixed=apply_patch(task,candidate,patch)
 assert digest(task)==h and fixed['layers'][0]['material_value']==4
 assert candidate['layers'][0]['material_value']==2
 patch['changes'][0]['new']=25
 with pytest.raises(ValueError):apply_patch(task,candidate,patch)
def test_patch_cannot_change_policy(task,candidate):
 p={'task_hash':digest(task),'candidate_hash':digest(candidate),'policy_hash':POLICY_HASH,'changes':[{'path':['policy','rt_absolute_tolerance'],'new':1,'old':.01}]}
 with pytest.raises(ValueError):apply_patch(task,candidate,p)
def test_model_honesty(task,candidate):
 with pytest.raises(RuntimeError,match='No LLM call'):UnconfiguredModelBackend().diagnose(task,candidate,{})
def test_status_priority():
 assert aggregate([{'status':'FAIL'},{'status':'INCONCLUSIVE'}])=='FAIL'
