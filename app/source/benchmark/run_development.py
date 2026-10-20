"""Reproducible visible development experiment, not a held-out benchmark."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).parents[1]))
from photonguard.core import load,write_json,lock_task,digest,POLICY_HASH
from photonguard.runner import run_case,verify_evidence,code_fingerprint
from photonguard.agent import propose_patch,apply_patch

def main():
 root=Path(__file__).parents[1]
 manifest=load(root/'examples/development_manifest.json')
 batch=root/'benchmark'/('development-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
 batch.mkdir(exist_ok=False)
 write_json(batch/'frozen_manifest.json',{'split':'development-visible','cases':manifest,'policy_hash':POLICY_HASH,'source_sha256':code_fingerprint(),'warning':'No blind benchmark or runtime AI experiment has been performed'})
 results=[]
 for entry in manifest:
  name=entry['case_id'];folder=root/'examples'/name
  lock_task(folder/'task.json',folder/'task.lock.json')
  report,evidence=run_case(folder/'task.json',folder/'candidate.json',folder/'task.lock.json',root/'artifacts')
  record={**entry,'actual_status':report['status'],'evidence':str(evidence.relative_to(root)),'integrity_verified':verify_evidence(evidence),'resource_usage':report['resource_usage'],'repairs':[]}
  print(name,report['status'],flush=True)
  task=load(folder/'task.json');candidate=load(folder/'candidate.json')
  if entry['expected_status']=='FAIL':
   for round in range(1,3):
    patch=propose_patch(task,candidate,report)
    if patch is None:break
    # Explicitly approved synthetic demonstration fixes, not user-code auto-edits.
    write_json(batch/(name+f'.patch{round}.json'),patch)
    candidate=apply_patch(task,candidate,patch)
    candidate_path=batch/(name+f'.repaired{round}.json');write_json(candidate_path,candidate)
    report,repaired=run_case(folder/'task.json',candidate_path,folder/'task.lock.json',root/'artifacts')
    record['repairs'].append({'round':round,'status':report['status'],'evidence':str(repaired.relative_to(root)),'integrity_verified':verify_evidence(repaired),'task_hash_unchanged':report['task_hash']==digest(task),'resource_usage':report['resource_usage']})
    print('  repair',round,report['status'],flush=True)
    if report['status']=='PASS':break
  results.append(record)
  write_json(batch/'results.json',results)
 summary={'scope':'visible synthetic development cases only','case_count':len(results),'matched_expected_status':sum(r['actual_status']==r['expected_status'] for r in results),'fault_cases':sum(r['expected_status']=='FAIL' for r in results),'false_pass_fault_cases':sum(r['expected_status']=='FAIL' and r['actual_status']=='PASS' for r in results),'initial_pass_cases':sum(r['actual_status']=='PASS' for r in results),'faults_repaired_to_pass':sum(bool(r['repairs']) and r['repairs'][-1]['status']=='PASS' for r in results),'actual_llm_calls':0,'total_fdtd_runs':sum(r['resource_usage']['fdtd_runs']+sum(x['resource_usage']['fdtd_runs'] for x in r['repairs']) for r in results),'total_wall_seconds':sum(r['resource_usage']['wall_seconds']+sum(x['resource_usage']['wall_seconds'] for x in r['repairs']) for r in results),'policy_hash':POLICY_HASH,'not_established':['General Meep bug detection accuracy','AI incremental value','Real user usability','Protected evaluation performance']}
 write_json(batch/'summary.json',summary);print(json.dumps(summary,indent=2));print('Results:',batch)
 return 0 if summary['matched_expected_status']==len(results) and summary['faults_repaired_to_pass']==summary['fault_cases'] else 2
if __name__=='__main__':raise SystemExit(main())
