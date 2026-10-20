"""Eight-FDTD canonical positive example, independent of API credentials."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from photonguard.novice import draft,source_for,TEMPLATE_TEXT
from photonguard.core import digest,POLICY_HASH
from photonguard.runner import run_case,verify_evidence

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 task=draft('portable-core-example','teaching',TEMPLATE_TEXT)['task'];source,preview=source_for(task)
 lock={'schema_version':1,'case_id':task['case_id'],'task_sha256':digest(task),'policy_sha256':POLICY_HASH,'confirmation':'Explicit invocation of documented synthetic example','actor_type':'SIMULATED'}
 for name,value in [('task.json',task),('candidate.json',preview['candidate']),('task.lock.json',lock)]:
  (a.out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2))
 (a.out/'template.py.txt').write_text(source)
 report,path=run_case(a.out/'task.json',a.out/'candidate.json',a.out/'task.lock.json',a.out/'evidence',8)
 assert verify_evidence(path)
 result={'status':report['status'],'evidence':str(path.resolve()),'actual_fdtd':report['resource_usage']['fdtd_runs'],'model_calls':0,'human_participants':0}
 (a.out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));return 0 if report['status']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
