import hashlib,json,copy
from pathlib import Path
import pytest
from photonguard.core import load,write_json,lock_task,digest
from photonguard.runner import verify_evidence,run_case
ROOT=Path(__file__).parents[1]
def minimal_evidence(tmp):
 (tmp/'data.txt').write_text('raw')
 write_json(tmp/'manifest.json',{'files':{'data.txt':hashlib.sha256(b'raw').hexdigest()}})
def test_hash_tamper(tmp_path):
 minimal_evidence(tmp_path);assert verify_evidence(tmp_path)
 (tmp_path/'data.txt').write_text('new');assert not verify_evidence(tmp_path)
def test_extra_manifest_detected(tmp_path):
 minimal_evidence(tmp_path);(tmp_path/'raw').mkdir();write_json(tmp_path/'raw/manifest.json',{})
 assert not verify_evidence(tmp_path)
def test_missing_manifest(tmp_path):assert not verify_evidence(tmp_path)
def test_symlink_rejected(tmp_path):
 minimal_evidence(tmp_path);(tmp_path/'shortcut').symlink_to(tmp_path/'data.txt');assert not verify_evidence(tmp_path)
def run_fixture(tmp_path,name,budget=0):
 folder=ROOT/'examples'/name;lock=tmp_path/'lock.json';lock_task(folder/'task.json',lock)
 return run_case(folder/'task.json',folder/'candidate.json',lock,tmp_path/'artifacts',budget)
def test_budget_cannot_pass(tmp_path):
 r,p=run_fixture(tmp_path,'film_n2');assert r['status']=='INCONCLUSIVE'
 assert r['resource_usage']['fdtd_runs']==0 and verify_evidence(p)
 assert not p.stat().st_mode & 0o222
@pytest.mark.parametrize('name,status',[('unknown_intent','INCONCLUSIVE'),('unsupported_angle','UNSUPPORTED')])
def test_stop_without_solver(tmp_path,name,status):
 r,p=run_fixture(tmp_path,name);assert r['status']==status and r['resource_usage']['fdtd_runs']==0
 assert verify_evidence(p)
def test_known_failure_survives_budget(tmp_path):
 r,p=run_fixture(tmp_path,'epsilon_mismatch');assert r['status']=='FAIL'
 assert any(c['status']=='INCONCLUSIVE' for c in r['checks'])
def test_lock_tamper_stops(tmp_path):
 folder=ROOT/'examples/film_n2';lock=tmp_path/'lock.json';lock_task(folder/'task.json',lock)
 t=load(folder/'task.json');t['layers'][0]['n']=3;changed=tmp_path/'changed.json';write_json(changed,t)
 r,p=run_case(changed,folder/'candidate.json',lock,tmp_path/'artifacts')
 assert r['status']=='FAIL' and r['resource_usage']['fdtd_runs']==0
