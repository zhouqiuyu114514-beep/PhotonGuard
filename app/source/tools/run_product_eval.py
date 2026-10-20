"""Frozen real DeepSeek comparisons. Credential read once from stdin, never saved."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from photonguard.product_phase import ProductClient
from photonguard.novice_ai import run
from photonguard import workflow_intake as intake
from photonguard.workflow import write_once
from photonguard.core import digest

def main():
 p=argparse.ArgumentParser();p.add_argument('--phase',type=Path,required=True);p.add_argument('--binding',type=Path,required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 key=sys.stdin.readline().strip();client=ProductClient(ROOT,a.phase,a.binding,lambda:key)
 suite=json.loads(a.suite.read_text());a.output.mkdir(parents=True,exist_ok=False)
 write_once(a.output/'frozen-suite.json',suite)
 write_once(a.output/'run-start.json',{'suite_sha256':digest(suite),'binding':client.spec,'new_solver_calls':0,'human_participants':0})
 for c in suite['cases']:
  prepared=intake.prepare(c['id'],c['text'])
  write_once(a.output/(c['id']+'-R.json'),{'result':intake.review(prepared,'mock'),'model_calls':0,'solver_calls':0})
  for arm in c.get('arms',['A','G']):
   result=run(client,c['id'],prepared,arm=arm)
   write_once(a.output/(c['id']+'-'+arm+'.json'),result)
   print(json.dumps({'case':c['id'],'arm':arm,'status':result['status'],'requests':len(result.get('steps',[]))}),flush=True)
   if result['status']=='PROVIDER_FAILURE':return 1
 write_once(a.output/'complete.json',client.status());key=None

if __name__=='__main__':raise SystemExit(main())
