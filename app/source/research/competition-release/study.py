"""Bounded, preregistered three-arm competition evaluation; no automatic retries.

The plain assistant gets the same public contract and observations, without
PhotonGuard semantic/evidence feedback or final evidence rejection. All arms
retain the same locked-task numeric sandbox and solver budget.
"""
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
import argparse,copy,hashlib,json,sys,time

def configure(args):
 global R,M,L,P,B
 R=args.source.resolve();M=args.project.resolve();L=M/'local-validation/competition-release-20261010';P=M/'local-validation/product-phase-26cny';B=P/'competition-release-20261010'
 sys.path.insert(0,str(R))

def read(p):return json.loads(Path(p).read_text())
def write(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(v,f,ensure_ascii=False,indent=2)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def facts(n,d,lo=1230,hi=1870,points=27):
 from photonguard.novice import TEMPLATE_TEXT
 return TEMPLATE_TEXT.replace('膜层折射率为2。',f'膜层折射率为{n}。').replace('膜厚为300 nm。',f'膜厚为{d} nm。').replace('1300 nm',f'{lo} nm').replace('1700 nm',f'{hi} nm').replace('点数为41',f'点数为{points}')

def freeze():
 from photonguard.approved_gui import source_manifest
 from photonguard.product_phase import bind,ProductLedger
 from photonguard.novice import normalize,draft,source_for
 from photonguard import workflow_intake as intake
 from photonguard.script_import import preview_bytes,validate_provenance
 from photonguard.core import digest,POLICY_HASH
 # Previously exercised cases are explicitly development; not unseen evidence.
 dev=M/'local-validation/compound-study-20261009'
 write(L/'development-index.json',{'count':8,'intake_tasks':4,'diagnosis_tasks':4,'previously_used_for_development':True,'files':{str(p.relative_to(M)):sha(p) for p in [dev/'protocol.json',dev/'private-oracle.json',dev/'score.json']},'not_retested_or_counted_as_new':True})
 rows=[];oracle=[]
 for i in range(1,9):
  base=facts(1.85,455,1210,1830,27);text=base;expected=copy.deepcopy(intake.rule_candidate(intake.prepare('base',base)['view'])['fields']);can=True;category='complete'
  if i==2:text=text.replace('膜厚为455 nm。','本次测得这层薄膜厚 455 纳米。');category='paraphrase_thickness'
  if i==3:text=text.replace('膜层折射率为1.85。','这层薄膜的折射率测得是 1.85。');category='paraphrase_index'
  if i==4:text=text.replace('膜厚为455 nm。','膜厚为0.455 um。')+'\n已作废的旧记录：膜厚为640 nm。';category='units_and_obsolete'
  if i==5:text=text.replace('膜厚为455 nm。','膜厚尚未测得。');expected['film_thickness'].update(status='unknown',value=None,unit=None);can=False;category='missing'
  if i==6:text+='\n第二份尚未裁定的独立测量：膜厚为495 nm。';expected['film_thickness'].update(status='conflict',value=None,unit=None);can=False;category='conflict'
  if i==7:text=text.replace('真空波长上界为1830 nm。','真空波长上界尚未决定。')+'\n教学示例：真空波长上界为1740 nm。';expected['wavelength_max'].update(status='unknown',value=None,unit=None);can=False;category='example_not_fact'
  if i==8:text=text.replace('入射角为0 deg。','入射角为9 deg。');expected['incidence_angle'].update(value='9');can=False;category='out_of_scope'
  ident=f'I{i:02}';normalized,mapping=normalize(text);prepared=intake.prepare(ident,normalized)
  rows.append({'id':ident,'text':text,'prepared':prepared,'normalization':mapping});oracle.append({'id':ident,'fields':expected,'confirmable':can,'category':category})
 write(L/'intake-public.json',rows)
 diagnoses=[];truth=[]
 configs=[('D01',1.9,360,'material'),('D02',2.05,420,'thickness'),('D03',1.75,480,'amplitude'),('D04',2.15,390,'subtraction'),('D05',1.65,440,None),('D06',2.0,510,None),('D07',1.95,465,'material'),('D08',2.1,355,'thickness')]
 for ident,n,d,fault in configs:
  task=draft(ident,'specified',facts(n,d))['task'];source,_=source_for(task);expected=[]
  if fault=='material':source=source.replace('mp.Medium(index=n)','mp.Medium(epsilon=n)');expected=[{'path':['layers',0,'material_value'],'new':n*n}]
  if fault=='thickness':source=source.replace('d = '+repr(d/1000),'d = 0.29');expected=[{'path':['layers',0,'thickness_um'],'new':d/1000}]
  if fault=='amplitude':
   source=source.replace('ref = mp.Simulation','refsource = mp.Source(pulse, component=mp.Ex, center=mp.Vector3(0, 0, -d/2-2), amplitude=0.7)\nref = mp.Simulation').replace('sources=[source]','sources=[refsource]',1);expected=[{'path':['workflow','reference_amplitude'],'new':1.0}]
  if fault=='subtraction':source=source.replace('target.load_minus_flux_data(rflux, incident_data)\n','');expected=[{'path':['workflow','subtract_incident'],'new':True}]
  candidate=preview_bytes(source.encode(),ident+'.py')['candidate'];validate_provenance(candidate,task)
  exhausted=ident in ('D07','D08')
  if exhausted:candidate['origin']['patch_round']=2
  folder=L/'inputs'/ident;folder.mkdir(parents=True)
  write(folder/'task.json',task);write(folder/'candidate.json',candidate);(folder/'candidate.py').write_text(source)
  write(folder/'task.lock.json',{'schema_version':1,'case_id':task['case_id'],'task_sha256':digest(task),'policy_sha256':POLICY_HASH,'confirmation':'Owner continuation and frozen simulated evaluation','actor_type':'SIMULATED'})
  diagnoses.append({'id':ident,'files':{p.name:sha(p) for p in folder.iterdir()}})
  truth.append({'id':ident,'expected_changes':[] if exhausted else expected,'goal':'STOP_EXHAUSTED' if exhausted else 'COMPLETE','synthetic_pre_exhausted_budget_fixture':exhausted})
 write(L/'private-oracle.json',{'intake':oracle,'diagnosis':truth})
 protocol={'version':1,'frozen_at':datetime.now(timezone.utc).isoformat(),'source':source_manifest(R),'development_tasks':8,'frozen_tasks':16,'intake_tasks':8,'diagnosis_tasks':8,'diagnoses':diagnoses,'public_sha256':sha(L/'intake-public.json'),'private_oracle_sha256':sha(L/'private-oracle.json'),'arms':['R','A','G'],'model':'deepseek-flash','temperature':0,'max_output_tokens':4096,'model_rounds_per_decision':2,'max_model_requests':64,'max_fdtd':256,'max_new_patch_rounds_per_case':1,'max_fdtd_per_validation':8,'same_public_facts_prompt_and_tools':True,'baseline_difference':'A receives neutral self-review and no PG semantic/evidence rejection; G receives PG feedback and final evidence checks. All share locked-task apply_patch and resource limits. A is also audited after the experiment, never retrospectively blocked.','intake_solver_calls':0,'holdout_description':'New parameter/expression instances in familiar synthetic task families, not independent external or unseen-domain sample','human_participants':0,'retry':False,'replacement':False,'tune_after_holdout':False,'development_cases_not_pooled':True,'price_verified_at':datetime.now(timezone.utc).isoformat(),'price_source':'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/','price_peak_cny_per_million':[2,8]}
 write(L/'protocol.json',protocol);write(L/'finance-before.json',ProductLedger(P).snapshot());write(L/'execution-ledger.json',{'model_reserved':0,'physical':[],'completed':[]})
 B.mkdir();bind(R,P,B/'binding.json','Frozen 16-case competition study; 64 requests, max 256 FDTD, cumulative original budget; no LN research')
 print(json.dumps({'frozen':16,'development':8,'source':protocol['source']['git_commit']}))

def check_binding():
 from photonguard.approved_gui import source_manifest
 p=read(L/'protocol.json');assert source_manifest(R)==p['source'];assert sha(L/'intake-public.json')==p['public_sha256'];assert sha(L/'private-oracle.json')==p['private_oracle_sha256'];return p

def physical(ident,task,candidate,lock,parent):
 from photonguard.runner import run_case,verify_evidence
 from photonguard.workflow import atomic_json
 ledger=read(L/'execution-ledger.json');assert ident not in [x['id'] for x in ledger['physical']];assert sum(x['reserved'] for x in ledger['physical'])+8<=256
 record={'id':ident,'reserved':8,'status':'STARTED'};ledger['physical'].append(record);atomic_json(L/'execution-ledger.json',ledger);start=time.monotonic()
 report,path=run_case(task,candidate,lock,parent,8);assert verify_evidence(path)
 record.update(status='COMPLETED',evidence=str(path),actual=report['resource_usage']['fdtd_runs'],verdict=report['status'],seconds=time.monotonic()-start);atomic_json(L/'execution-ledger.json',ledger)
 print(json.dumps({'physical':ident,'verdict':report['status']}),flush=True);return path

def initial():
 protocol=check_binding()
 for entry in protocol['diagnoses']:
  f=L/'inputs'/entry['id'];assert all(sha(f/k)==v for k,v in entry['files'].items());physical(entry['id']+'-initial',f/'task.json',f/'candidate.json',f/'task.lock.json',L/'initial'/entry['id'])
 write(L/'initial-complete.json',{'cases':8})

def plain_intake(raw):
 from photonguard import workflow_intake as intake
 from photonguard.backend import _strict_json
 obj=_strict_json(raw);fields=obj['fields'];assert set(fields)==set(intake.semantic.KEYS)
 can=obj['review_status']=='REVIEW_REQUIRED' and all(f['status']=='proposed' for f in fields.values()) and not intake.scope_problems(obj)
 return {'accepted':True,'result':{'normalized_response':obj,'confirmable':can},'checks':'JSON structure and common numeric/scope execution sandbox only; no evidence validation'}

def diagnosis_guard(arm,evidence,base,request,action,audit):
 from photonguard.repair_diagnosis import validate_model_action
 from photonguard.agent import apply_patch
 from photonguard.core import digest,POLICY_HASH
 patch=None
 if arm=='G':patch,_=validate_model_action(evidence,base,request,action,audit)
 else:
  assert action['decision'] in ('propose_patch','no_change','inconclusive','unsupported')
  if action['decision']=='propose_patch':
   assert len(action['changes'])==1;change=copy.deepcopy(action['changes'][0]);candidate=read(evidence/'candidate.original.json');task=read(evidence/'task.original.json');old=candidate
   for key in change['path']:old=old[key]
   change['old']=old;patch={'schema_version':1,'backend':'plain_assistant','actual_llm_calls':2,'task_hash':digest(task),'candidate_hash':digest(candidate),'policy_hash':POLICY_HASH,'based_on_run':read(evidence/'report.json')['run_id'],'changes':[change],'rationale':'Unverified plain assistant proposal','requires_explicit_approval':True}
  else:assert action['changes']==[]
 if patch:apply_patch(read(evidence/'task.original.json'),read(evidence/'candidate.original.json'),patch)
 return {'accepted':True,'patch':patch,'decision':action['decision']}

def evaluate():
 from photonguard.product_phase import ProductClient,json_payload
 from photonguard import workflow_intake as intake,novice_ai
 from photonguard.repair_diagnosis import model_request
 from photonguard.backend import _strict_json
 from photonguard.workflow import atomic_json
 from photonguard.agent import propose_patch,apply_patch
 check_binding();assert (L/'initial-complete.json').exists()
 key=sys.stdin.readline().strip();assert key;client=ProductClient(R,P,B/'binding.json',lambda:key)
 def call(ident,payload):
  ledger=read(L/'execution-ledger.json');assert ledger['model_reserved']<64;ledger['model_reserved']+=1;atomic_json(L/'execution-ledger.json',ledger)
  result=client.complete(ident,payload);assert result['audit']['status']=='ASSISTANT_RETURNED','Transport failed: no retry';return result
 for case in read(L/'intake-public.json'):
  ident=case['id'];prepared=case['prepared'];out=L/'results'/ident
  write(out/'R.json',{'guard':{'accepted':True,'result':intake.review(prepared,'mock')},'model_calls':0})
  for arm in ('A','G'):
   payload=novice_ai.request(prepared['view']);steps=[]
   for turn in (1,2):
    result=call(f'{ident}-{arm}-{turn}',payload);raw=result['assistant']['content']
    try:guard=plain_intake(raw) if arm=='A' else novice_ai.review(prepared['view'],raw)
    except (ValueError,TypeError,KeyError,AssertionError,IndexError) as e:guard={'accepted':False,'reason':type(e).__name__+':'+str(e)}
    steps.append({'response':result,'guard':guard})
    if turn==1:
     payload['messages'].append(result['assistant']);feedback={'instruction':'再核对同一份原始资料、单位与公共合同，输出最终完整 JSON；不要猜缺项。'}
     if arm=='G':feedback['public_validator_feedback']=guard
     payload['messages'].append({'role':'user','content':json.dumps(feedback,ensure_ascii=False)})
   write(out/(arm+'.json'),{'steps':steps,'guard':guard,'model_calls':2,'posthoc_pg_audit':novice_ai.review(prepared['view'],raw)})
  print(json.dumps({'intake_completed':ident}),flush=True)
 for entry in read(L/'protocol.json')['diagnoses']:
  ident=entry['id'];f=L/'inputs'/ident;initial_path=Path(next(x['evidence'] for x in read(L/'execution-ledger.json')['physical'] if x['id']==ident+'-initial'));task=read(f/'task.json');candidate=read(f/'candidate.json');report=read(initial_path/'report.json');base,request=model_request(initial_path)
  for arm in ('R','A','G'):
   out=L/'results'/ident/arm;out.mkdir(parents=True);steps=[]
   if arm=='R':
    patch=propose_patch(task,candidate,report);guard={'accepted':True,'patch':patch,'decision':'propose_patch' if patch else 'no_change' if report['status']=='PASS' else 'inconclusive'}
   else:
    payload=json_payload(request['prompt'],{k:request[k] for k in ('task','candidate','observations','allowed_actions')})
    for turn in (1,2):
     result=call(f'{ident}-{arm}-{turn}',payload)
     try:action=_strict_json(result['assistant']['content']);guard=diagnosis_guard(arm,initial_path,base,request,action,result['audit'])
     except (ValueError,TypeError,KeyError,AssertionError,IndexError) as e:guard={'accepted':False,'reason':type(e).__name__+':'+str(e),'patch':None}
     steps.append({'response':result,'guard':guard})
     if turn==1:
      payload['messages'].append(result['assistant']);feedback={'instruction':'Review the same measurements, common contract and remaining budget; return final complete JSON. No task-specific answer is provided.'}
      if arm=='G':feedback['public_guard_feedback']=guard
      payload['messages'].append({'role':'user','content':json.dumps(feedback,ensure_ascii=False)})
   write(out/'decision.json',{'steps':steps,'guard':guard});final=initial_path
   if guard.get('patch'):
    updated=apply_patch(task,candidate,guard['patch']);write(out/'candidate.json',updated);write(out/'execution-authority.json',{'actor':'SIMULATED','authority':'Owner continue plus preregistered one-repair budget','task_is_immutable':True})
    final=physical(ident+'-'+arm,f/'task.json',out/'candidate.json',f/'task.lock.json',out/'artifacts')
   write(out/'result.json',{'id':ident,'arm':arm,'guard':guard,'initial':str(initial_path),'final':str(final),'final_verdict':read(final/'report.json')['status'],'budget_stop_after_this_step':True})
  print(json.dumps({'diagnosis_completed':ident}),flush=True)
 write(L/'evaluation-complete.json',{'ledger':read(L/'execution-ledger.json'),'finance':client.ledger.snapshot(),'human_participants':0})

def comparable(key,f):
 from photonguard import workflow_intake as intake
 if f['status']!='proposed':return (f['status'],None,None)
 v=f['value']
 if key in ('film_thickness','wavelength_min','wavelength_max'):v=intake.semantic.number(intake.semantic.shift(v,intake.semantic.LENGTH[f['unit']]))
 elif key not in ('spatial_dimension','lossless','isotropic','nondispersive'):v=Decimal(str(v))
 return ('proposed',v,type(v) is bool)

def score():
 from photonguard.product_phase import ProductLedger
 assert (L/'evaluation-complete.json').exists();truth=read(L/'private-oracle.json');rows=[]
 for case in truth['intake']:
  for arm in ('R','A','G'):
   saved=read(L/'results'/case['id']/(arm+'.json'));guard=saved['guard'];obj=guard.get('result',{}).get('normalized_response',{});can=bool(guard.get('accepted') and guard.get('result',{}).get('confirmable'));correct=False
   try:correct=all(comparable(k,v)==comparable(k,obj['fields'][k]) for k,v in case['fields'].items())
   except (ValueError,KeyError,TypeError):pass
   rows.append({'id':case['id'],'section':'intake','arm':arm,'configuration_correct':correct,'success':correct and can==case['confirmable'],'completed_configuration':correct and can,'expected_completion':case['confirmable'],'false_permission':can and (not case['confirmable'] or not correct),'correct_stop':not case['confirmable'] and not can and correct,'blocked':not can,'rejected':not guard.get('accepted')})
 for case in truth['diagnosis']:
  for arm in ('R','A','G'):
   saved=read(L/'results'/case['id']/arm/'result.json');g=saved['guard'];patch=g.get('patch');changes=[{'path':c['path'],'new':c['new']} for c in patch['changes']] if patch else [];correct=changes==case['expected_changes'];passed=saved['final_verdict']=='PASS';stop=case['goal']=='STOP_EXHAUSTED' and not patch and g.get('accepted',False) and g.get('decision') in ('inconclusive','unsupported') and not passed
   rows.append({'id':case['id'],'section':'diagnosis','arm':arm,'configuration_correct':correct,'success':stop if case['goal']=='STOP_EXHAUSTED' else correct and passed,'completed':passed and correct,'expected_completion':case['goal']=='COMPLETE','false_permission':bool(patch and not correct),'correct_stop':stop,'blocked':not passed,'rejected':not g.get('accepted')})
 summary={}
 for section in ('intake','diagnosis'):
  summary[section]={}
  for arm in ('R','A','G'):
   selected=[r for r in rows if r['section']==section and r['arm']==arm];summary[section][arm]={k:sum(bool(x.get(k)) for x in selected) for k in ('configuration_correct','success','completed_configuration','completed','false_permission','correct_stop','blocked','rejected')};summary[section][arm]['cases']=8
 ledger=read(L/'execution-ledger.json');before=read(L/'finance-before.json');after=ProductLedger(P).snapshot();audits=[read(p)['audit'] for p in (B/'requests').glob('*/result.json')]
 assert len(audits)==64 and all(x['live_dispatch'] and x['status']=='ASSISTANT_RETURNED' for x in audits)
 write(L/'score.json',{'summary':summary,'rows':rows,'real_model_calls':len(audits),'actual_fdtd':sum(x['actual'] for x in ledger['physical']),'shared_initial_fdtd':sum(x['actual'] for x in ledger['physical'] if x['id'].endswith('initial')),'by_arm_new_fdtd':{arm:sum(x['actual'] for x in ledger['physical'] if x['id'].endswith('-'+arm)) for arm in ('R','A','G')},'new_accounted_cny':str(Decimal(after['reserved_cny'])-Decimal(before['reserved_cny'])),'remaining_cny':str(Decimal('30.422906000037')-Decimal(after['reserved_cny'])),'human_participants':0,'source':read(L/'protocol.json')['source']['git_commit'],'no_replacement_no_retuning':True})
 print(json.dumps(read(L/'score.json'),ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['freeze','initial','evaluate','score']);p.add_argument('--source',type=Path,required=True);p.add_argument('--project',type=Path,required=True);args=p.parse_args();configure(args);globals()[args.stage]()
