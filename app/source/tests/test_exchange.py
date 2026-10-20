"""Protocol tests use fake responses, never count as actual AI experiments."""
from pathlib import Path
import pytest
from photonguard.core import lock_task
from photonguard.runner import run_case
from photonguard.exchange import export_request,action_to_patch,save_exchange
ROOT=Path(__file__).parents[1]
@pytest.fixture
def evidence(tmp_path):
 folder=ROOT/'examples/epsilon_mismatch';lock=tmp_path/'lock.json';lock_task(folder/'task.json',lock)
 return run_case(folder/'task.json',folder/'candidate.json',lock,tmp_path/'runs',0)[1]
def test_export_no_labels_or_oracle(evidence):
 r=export_request(evidence)
 assert 'case_id' not in r['task'] and 'case_id' not in r['candidate']
 assert 'sources' not in r['task'] and 'origin' not in r['candidate']
 assert 'R_reference' not in str(r) and 'epsilon_mismatch' not in str(r)
def test_valid_action(evidence):
 r=export_request(evidence);a={'decision':'propose_patch','changes':[{'path':['layers',0,'material_value'],'new':4.0}],'rationale':'Restore confirmed n2','evidence_ids':['task_parameters']}
 p=action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt','model_identity':'TEST FIXTURE, NOT REAL AI','runtime_api_calls':0})
 assert p['changes'][0]['old']==2 and p['changes'][0]['new']==4
@pytest.mark.parametrize('path,value',[(['policy','tolerance'],1),(['layers',0,'material_value'],9),(['numerics','after_sources'],400)])
def test_forbidden_actions(evidence,path,value):
 r=export_request(evidence);a={'decision':'propose_patch','changes':[{'path':path,'new':value}],'rationale':'untrusted model','evidence_ids':[]}
 with pytest.raises(ValueError):action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt'})
def test_stale_request(evidence):
 r=export_request(evidence);r['policy_hash']='wrong';a={'decision':'no_change','changes':[],'rationale':'none','evidence_ids':[]}
 with pytest.raises(ValueError):action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt'})
def test_unknown_evidence(evidence):
 r=export_request(evidence);a={'decision':'no_change','changes':[],'rationale':'none','evidence_ids':['invented']}
 with pytest.raises(ValueError):action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt'})
def test_mutated_model_inputs(evidence):
 r=export_request(evidence);r['task']['layers'][0]['n']=3
 a={'decision':'no_change','changes':[],'rationale':'none','evidence_ids':[]}
 with pytest.raises(ValueError):action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt'})
def test_old_policy_evidence_cannot_be_restamped(evidence):
 import json,hashlib
 evidence.chmod(0o755)
 report=evidence/'report.json';report.chmod(0o644)
 data=json.loads(report.read_text());data['policy_hash']='old-development-policy';report.write_text(json.dumps(data))
 manifest=evidence/'manifest.json';manifest.chmod(0o644)
 m=json.loads(manifest.read_text());m['files']['report.json']=hashlib.sha256(report.read_bytes()).hexdigest();manifest.write_text(json.dumps(m))
 with pytest.raises(ValueError,match='Evidence policy'):export_request(evidence)
def test_material_decimal_rounding_is_canonicalized(tmp_path):
 from photonguard.core import load,write_json,lock_task
 task=load(ROOT/'examples/epsilon_mismatch/task.json');candidate=load(ROOT/'examples/epsilon_mismatch/candidate.json')
 task['layers'][0]['n']=2.35
 t=tmp_path/'task.json';c=tmp_path/'candidate.json';l=tmp_path/'lock.json'
 write_json(t,task);write_json(c,candidate);lock_task(t,l)
 e=run_case(t,c,l,tmp_path/'runs',0)[1];r=export_request(e)
 a={'decision':'propose_patch','changes':[{'path':['layers',0,'material_value'],'new':5.5225}],'rationale':'Restore n2.35','evidence_ids':['task_parameters']}
 p=action_to_patch(e,r,a,{'mode':'assistant_mediated_gpt'})
 assert p['changes'][0]['new']==2.35**2 and a['changes'][0]['new']==5.5225


@pytest.mark.parametrize('remaining',[0,1,9,True])
def test_exported_remaining_authority_cannot_be_modified(evidence,remaining):
 r=export_request(evidence);assert r['allowed_actions']['patch_rounds_used']==0
 assert r['allowed_actions']['patch_rounds_remaining']==2
 r['allowed_actions']['patch_rounds_remaining']=remaining
 a={'decision':'inconclusive','changes':[],'rationale':'Synthetic abstention','evidence_ids':[]}
 with pytest.raises(ValueError,match='action budget'):
  action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt'})

def test_exhausted_record_is_visible_and_cannot_request_third_patch(tmp_path):
 from photonguard.core import load,write_json
 from photonguard.agent import apply_patch
 folder=ROOT/'examples/epsilon_mismatch';task=load(folder/'task.json');candidate=load(folder/'candidate.json')
 # Synthetic protocol fixture; no solver calls and no claim of a real repair chain.
 candidate['origin']={'patch_round':2,'kind':'SYNTHETIC_PROTOCOL_FIXTURE'}
 t=tmp_path/'task.json';c=tmp_path/'candidate.json';l=tmp_path/'lock.json'
 write_json(t,task);write_json(c,candidate);lock_task(t,l)
 e=run_case(t,c,l,tmp_path/'runs',0)[1];r=export_request(e)
 assert r['allowed_actions']['patch_rounds_remaining']==0
 a={'decision':'propose_patch','changes':[{'path':['layers',0,'material_value'],'new':4.0}],'rationale':'Synthetic third repair','evidence_ids':['task_parameters']}
 with pytest.raises(ValueError,match='budget exhausted'):
  action_to_patch(e,r,a,{'mode':'assistant_mediated_gpt'})
 a.update(decision='inconclusive',changes=[])
 assert action_to_patch(e,r,a,{'mode':'assistant_mediated_gpt'}) is None


def test_action_budget_boolean_alias_is_rejected(evidence):
 r=export_request(evidence);r['allowed_actions']['maximum_changes']=True
 a={'decision':'inconclusive','changes':[],'rationale':'Synthetic abstention','evidence_ids':[]}
 with pytest.raises(ValueError,match='action budget'):
  action_to_patch(evidence,r,a,{'mode':'assistant_mediated_gpt'})
