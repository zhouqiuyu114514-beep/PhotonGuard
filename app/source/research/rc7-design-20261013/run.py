"""One preregistered 8-situation x 3-noise-repeat study; no outcome-driven expansion."""
from pathlib import Path
import json,io,sys,time
import numpy as np
from photonguard.core import digest
from photonguard.experiments import inverse_models as m,inverse_profiles as engine,observation_group as ow,goal_design as old,baseline_design as new

CASES=[{'a':13.,'d':148.,'half':.45,'sd':.006},{'a':18.,'d':166.,'half':.65,'sd':.012},
 {'a':23.,'d':187.,'half':.9,'sd':.022},{'a':30.,'d':218.,'half':.5,'sd':.009},
 {'a':34.,'d':223.,'half':.85,'sd':.018},{'a':15.,'d':205.,'half':1.1,'sd':.012},
 {'a':27.,'d':155.,'half':.55,'sd':.02},{'a':37.,'d':195.,'half':.75,'sd':.006}]
PROTOCOL={'kind':'PREDECLARED_NUMERICAL_DEVELOPMENT','situations':CASES,'noise_seeds':[7301,7302,7303],'situations_count':8,'noise_repeats_per_situation':3,
 'arms':['fixed','rc6_goal','rc7_conservative'],'points_initial':81,'points_additional':81,'fit_runs_max':96,'profile_runs_max':24,'residual_calls_max':3600000,'total_seconds_max':1800,
 'stop_rule':'Stop in situation/seed/arm order on resource limit or failed initial fit; retain all started cases; no replacement seed or performance-based subset.',
 'target':{'slit_width_um':.5,'slit_separation_um':.1},'goal':'balanced','objective':'RC6 unchanged EQUAL_DATASET_TRAINING_COUNT linear loss in every arm',
 'new_policy':'conservative-v1: simple baseline default without declared independent-noise planning model; local alternatives and stability displayed. Ties by construction are not a new algorithm win.',
 'noise_coupling':'Within an arm independent Gaussian noise per observation. Between arms common ordered Gaussian draws at the same acquisition index; physical locations may differ. Fixed sequence before execution.',
 'validation':'Unused 101-point scan +/-4 mm, seed+20000; not given to recommendation or fitting.',
 'inference':'Report per-situation results and paired worst effects; 24 noise repetitions are not 24 distinct tasks. No significance or universal optimality claim.'}
C={'max_abs_x_mm':5.,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}

def observe(case,seed,x,stage):
 x=np.asarray(x);q=(x-.11)/(.000633*200);u=np.pi*case['a']*.001*q
 shape=np.where(u==0,1.,(np.sin(u)/np.where(u==0,1.,u))**2)*(1+np.cos(2*np.pi*case['d']*.001*q))/2
 y=(1. if stage==0 else .83)*shape+(.035 if stage==0 else .068)+np.random.default_rng(seed+stage*10000).normal(0,case['sd'],len(x))
 out=io.StringIO();np.savetxt(out,np.c_[x,y],delimiter=',',header='position_mm,intensity_relative',comments='');return out.getvalue(),y

def entry(raw,cfg,j,sd):
 ds=ow.parse(raw,m.SLIT,{'source_kind':'SYNTHETIC_TEACHING','source_name':'RC7 preregistered point-sampled observation'})
 return ow.group_entry(ds,cfg,f'scan-{j}.csv')|{'approved':True,'scale':sd,'scale_source':'KNOWN_MEASUREMENT_SD','observation':{'kind':'POINT_SAMPLE'}}

def main(out):
 out=Path(out);out.mkdir(exist_ok=False);save=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False,indent=2));save(out/'protocol.json',PROTOCOL)
 began=time.monotonic();calls=0;fits=0;profiles=0;rows=[]
 def run(groups,cfg,path,profile=False,reference=None):
  nonlocal calls,fits,profiles
  assert time.monotonic()-began<1800 and calls<3600000 and (profiles<24 if profile else fits<96)
  p=m.plan(groups,cfg,'profile' if profile else 'fit',parameter='slit_width_um' if profile else None,reference=reference);r=engine.run(p,reference=reference)
  calls+=r['resources']['actual_residual_calls'];profiles+=profile;fits+=not profile;save(path,r);return r
 for i,case in enumerate(CASES):
  for repeat,seed in enumerate(PROTOCOL['noise_seeds']):
   folder=out/f'situation-{i+1:02}-repeat-{repeat+1}';folder.mkdir();cfg=ow.defaults(m.SLIT);raw,_=observe(case,seed,np.linspace(-case['half'],case['half'],81),0);(folder/'initial.csv').write_text(raw);groups=[entry(raw,cfg,0,case['sd'])]
   fit=run(groups,cfg,folder/'initial-fit.json');assert fit.get('estimated_parameters'),'Predeclared stop on initial failure'
   profile=run(groups,cfg,folder/'profile.json',True,fit);profs={'slit_width_um':profile};goal={'target':'balanced','source':'USER_FORM','tolerances':PROTOCOL['target']}
   oldp=old.propose(groups,cfg,fit,profs,C,goal);newp=new.propose(groups,cfg,fit,profs,C,goal)
   save(folder/'rc6-proposal.json',oldp);save(folder/'rc7-proposal.json',newp)
   vx=np.linspace(-4,4,101);raw,vy=observe(case,seed,vx,2);(folder/'independent-validation.csv').write_text(raw);arms={}
   for arm,p in [('fixed',None),('rc6_goal',oldp),('rc7_conservative',newp)]:
    plan=next(v for v in p['plans'] if v['id']==p['recommended_id']) if p else {'id':'fixed','prediction_x_mm':np.linspace(-2,2,81).tolist(),'cost':{'points':81,'travel_mm':4.,'uniform_segments':1}}
    raw,_=observe(case,seed,plan['prediction_x_mm'],1);(folder/(arm+'.csv')).write_text(raw);joined=groups+[entry(raw,cfg,1,case['sd'])];r=run(joined,cfg,folder/(arm+'-fit.json'));params=r.get('estimated_parameters')
    item={'chosen':plan['id'],'cost':plan['cost'],'failed':not bool(params),'warnings':r['warnings'],'resources':r['resources'],'recommendation_kind':p['recommendation_kind'] if p else 'FIXED_REFERENCE'}
    if params:
     a=abs(params['slit_width_um']-case['a']);d=abs(params['slit_separation_um']-case['d']);names,_,_=m.layout(joined,cfg);pars=m.values([params[k] for k in names],names,cfg,1)
     item.update(a_error_um=a,d_error_um=d,joint_target_met=a<=.5 and d<=.1,prediction_rmse=float(np.sqrt(np.mean((m.predict(vx,pars,m.SLIT)-vy)**2))))
    arms[arm]=item
   rows.append({'situation':i+1,'noise_repeat':repeat+1,'seed':seed,'truth_for_evaluator_only':case,'arms':arms});save(out/'all-cases.json',rows);print('completed',len(rows),'residuals',calls,flush=True)
 summaries={}
 for arm in PROTOCOL['arms']:
  items=[r['arms'][arm] for r in rows]
  summaries[arm]={'noise_repetitions':len(items),'situations':8,'joint_target_met':sum(v.get('joint_target_met',False) for v in items),'failures':sum(v['failed'] for v in items),'finite_recommendation_coverage':sum(v['recommendation_kind'] in ('FINITE_CANDIDATE_GOAL_HEURISTIC','BASELINE_CONSERVATIVE','FIXED_REFERENCE') for v in items),
   'metrics':{k:{'median':float(np.median([v[k] for v in items if k in v])),'worst_paired_degradation_vs_fixed':max(r['arms'][arm][k]-r['arms']['fixed'][k] for r in rows if k in r['arms'][arm])} for k in ('a_error_um','d_error_um','prediction_rmse')},
   'per_situation':[{'situation':i,'joint_target_met':sum(r['arms'][arm].get('joint_target_met',False) for r in rows if r['situation']==i),'repeats':3} for i in range(1,9)]}
 summary={'status':'COMPLETE','protocol_sha256':digest(PROTOCOL),'summaries':summaries,'fit_runs':fits,'profile_runs':profiles,'actual_residual_calls':calls,'elapsed_seconds':time.monotonic()-began,'model_calls':0,'fdtd':0,'new_policy_ties_to_fixed_are_not_gains':True,'all_started_cases_retained':True};save(out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
