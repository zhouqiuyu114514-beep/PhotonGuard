"""Paired two-turn diagnosis of saved real evidence; no patch application."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from photonguard.product_phase import ProductClient,json_payload
from photonguard.repair_diagnosis import model_request,validate_model_action
from photonguard.backend import _strict_json
from photonguard.workflow import write_once
from photonguard.agent import propose_patch
from photonguard.core import load

def main():
 p=argparse.ArgumentParser();p.add_argument('--phase',type=Path,required=True);p.add_argument('--binding',type=Path,required=True);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 key=sys.stdin.readline().strip();client=ProductClient(ROOT,a.phase,a.binding,lambda:key)
 suite=json.loads(a.suite.read_text());a.output.mkdir(parents=True,exist_ok=False);write_once(a.output/'frozen-suite.json',suite)
 for item in suite['cases']:
  evidence=Path(item['evidence']);base,request=model_request(evidence)
  rule=propose_patch(load(evidence/'task.original.json'),load(evidence/'candidate.original.json'),load(evidence/'report.json'));write_once(a.output/(item['id']+'-R.json'),{'patch':rule,'new_solver_calls':0,'actual_model_calls':0})
  for arm in ('A','G'):
   payload=json_payload(request['prompt'],{k:request[k] for k in ('task','candidate','observations','allowed_actions')});steps=[]
   for turn in (1,2):
    response=client.complete(item['id']+'-'+arm+'-'+str(turn),payload);audit=response['audit']
    if audit['status']!='ASSISTANT_RETURNED':write_once(a.output/(item['id']+'-'+arm+'-failed.json'),response);return 1
    try:
     action=_strict_json(response['assistant']['content']);patch,issues=validate_model_action(evidence,base,request,action,{**audit,'requested_model':'deepseek-flash','actual_llm_calls':1})
     guard={'accepted':True,'patch':patch,'issues':issues}
    except (ValueError,TypeError,KeyError) as e:guard={'accepted':False,'reason':str(e)}
    steps.append({'response':response,'guard':guard})
    if turn==1:
     payload['messages'].append(response['assistant']);feedback={'instruction':'Review the same measurements and contract again. Return your final complete JSON; preserve uncertainty, no extra actions.'}
     if arm=='G':feedback['public_guard_feedback']=guard
     payload['messages'].append({'role':'user','content':json.dumps(feedback,ensure_ascii=False)})
   write_once(a.output/(item['id']+'-'+arm+'.json'),{'steps':steps,'new_solver_calls':0,'actual_patch_executed':False})
   print(json.dumps({'case':item['id'],'arm':arm,'guard_accepted':guard['accepted']}),flush=True)
 write_once(a.output/'complete.json',client.status());key=None
if __name__=='__main__':raise SystemExit(main())
