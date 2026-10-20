"""Frozen new-case 2x2 design study. Truth and future arrays stay in evaluator."""
from pathlib import Path
import json,io,sys,time,copy
import numpy as np
from photonguard.core import digest
from photonguard.experiments import inverse_models as m,inverse_profiles as engine,observation_group as ow,goal_design as gd

PROTOCOL={'kind':'PREDECLARED_DEVELOPMENT_NOT_BLIND','cases':[{'a':16.,'d':158.,'seed':1701,'sd':.008,'half':.5},{'a':24.,'d':196.,'seed':1702,'sd':.015,'half':.7},{'a':29.,'d':207.,'seed':1703,'sd':.008,'half':.5},{'a':19.,'d':172.,'seed':1704,'sd':.015,'half':.7}],
 'arms':['uniform_legacy','uniform_goal','mixed_legacy','mixed_goal','fixed_extension'],
 'tolerances':{'slit_width_um':.5,'slit_separation_um':.1},'goal':'balanced','points':81,
 'stress_cases':['blur','background_drift','registration_error'],'fit_runs_max':27,'profile_runs_max':4,'residual_calls_max':930000,
 'rule':'Same actual joint candidate pool and scale; 2x2 crosses 3 versus 6 templates and pairwise-disagreement versus goal score. Fixed baseline +/-2 mm. No LLM inside scoring.',
 'independent_validation':'101 unused observations +/-4 mm, common future seed. Neither truth nor future arrays passed to planner.',
 'limitations':['synthetic development cases, not blind or instrument evidence','same point count, movement/segments differ','linear local scale is not confidence interval']}
C={'max_abs_x_mm':5.,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}

def observe(case,x,stage=0,stress=None):
 x=np.asarray(x);center=.09 if stress!='registration_error' else .23;q=(x-center)/(.000633*200)
 shape=np.sinc(case['a']*.001*q)**2*np.cos(np.pi*case['d']*.001*q)**2
 if stress=='blur':
  curves=[]
  for dx in np.linspace(-.08,.08,9):
   qq=(x+dx-center)/(.000633*200);curves.append(np.sinc(case['a']*.001*qq)**2*np.cos(np.pi*case['d']*.001*qq)**2)
  shape=np.mean(curves,axis=0)
 y=(1. if stage==0 else .85)*shape+(.04 if stage==0 else .065)
 if stress=='background_drift':y+=.04*x
 y+=np.random.default_rng(case['seed']+stage*10000).normal(0,case['sd'],len(x))
 out=io.StringIO();np.savetxt(out,np.c_[x,y],delimiter=',',header='position_mm,intensity_relative',comments='');return out.getvalue(),y

def entry(raw,cfg,sd,j):
 ds=ow.parse(raw,m.SLIT,{'source_kind':'SYNTHETIC_TEACHING','source_name':'Frozen RC6 numerical case'})
 return ow.group_entry(ds,cfg,f'scan-{j}.csv')|{'approved':True,'scale':sd,'scale_source':'KNOWN_MEASUREMENT_SD'}

def main(folder):
 folder=Path(folder);folder.mkdir(exist_ok=False);(folder/'protocol.json').write_text(json.dumps(PROTOCOL,indent=2));rows=[];calls=0;fits=0
 def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
 def run(groups,cfg,path,**kw):
  nonlocal calls,fits
  plan=m.plan(groups,cfg,**kw);result=engine.run(plan,reference=kw.get('reference'));calls+=result['resources']['actual_residual_calls'];fits+=kw.get('operation','fit')=='fit';save(path,result);assert calls<=PROTOCOL['residual_calls_max'];return result
 for index,case in enumerate(PROTOCOL['cases']):
  out=folder/f'case-{index+1:02}';out.mkdir();cfg=ow.defaults(m.SLIT);raw,_=observe(case,np.linspace(-case['half'],case['half'],81));(out/'initial.csv').write_text(raw);groups=[entry(raw,cfg,case['sd'],0)]
  fit=run(groups,cfg,out/'initial-fit.json');profile=run(groups,cfg,out/'profile.json',operation='profile',parameter='slit_width_um',reference=fit)
  truth_x=np.linspace(-4,4,101);vr,vy=observe(case,truth_x,2);(out/'independent-validation.csv').write_text(vr);arms={}
  for arm in PROTOCOL['arms']:
   if arm=='fixed_extension':proposal=None;chosen={'id':'fixed_extension','prediction_x_mm':np.linspace(-2,2,81).tolist(),'cost':{'points':81,'travel_mm':4.,'uniform_segments':1,'exposures':81,'data_groups':1}}
   else:
    proposal=gd.propose(groups,cfg,fit,{'width':profile},C,{'target':'balanced','source':'USER_FORM','tolerances':PROTOCOL['tolerances']},mixed=arm.startswith('mixed'),scoring='legacy' if arm.endswith('legacy') else 'goal')
    chosen=next(p for p in proposal['plans'] if p['id']==proposal['recommended_id']);save(out/(arm+'-proposal.json'),proposal)
   raw,_=observe(case,chosen['prediction_x_mm'],1);(out/(arm+'.csv')).write_text(raw);joined=groups+[entry(raw,cfg,case['sd'],1)];result=run(joined,cfg,out/(arm+'-fit.json'));p=result.get('estimated_parameters')
   item={'chosen':chosen['id'],'cost':chosen['cost'],'recommendation_kind':proposal['recommendation_kind'] if proposal else 'FIXED_BASELINE','warnings':result['warnings'],'failed':not bool(p),'resources':result['resources']}
   if p:
    names,_,_=m.layout(joined,cfg);pars=m.values([p[k] for k in names],names,cfg,1);a=abs(p['slit_width_um']-case['a']);d=abs(p['slit_separation_um']-case['d'])
    item.update(a_error_um=a,d_error_um=d,joint_target_met=a<=.5 and d<=.1,prediction_rmse=float(np.sqrt(np.mean((m.predict(truth_x,pars,m.SLIT)-vy)**2))))
   arms[arm]=item
  rows.append({'case':index+1,'truth_for_evaluator_only':case,'arms':arms});save(folder/'all-cases.json',rows);print('case',index+1,'calls',calls,flush=True)
 stress=[]
 for name in PROTOCOL['stress_cases']:
  case=PROTOCOL['cases'][0];cfg=ow.defaults(m.SLIT)
  if name=='registration_error':cfg['fixed']['center_shift_mm']=.09;cfg['bounds'].pop('center_shift_mm')
  raw,_=observe(case,np.linspace(-4,4,81),1,name);(folder/(name+'.csv')).write_text(raw);r=run([entry(raw,cfg,case['sd'],0)],cfg,folder/(name+'-fit.json'))
  stress.append({'case':name,'warnings':r['warnings'],'usable_for_forward':r['usable_for_forward'],'caveat':'diagnostics may miss mismatch; no causal diagnosis or uniqueness certification'})
 metrics={}
 for arm in PROTOCOL['arms']:
  vals=[row['arms'][arm] for row in rows];base=[row['arms']['fixed_extension'] for row in rows]
  metrics[arm]={'cases':len(vals),'finite_recommendation_coverage':sum(v['recommendation_kind']=='FINITE_CANDIDATE_GOAL_HEURISTIC' for v in vals),'local_only':sum(v['recommendation_kind']=='LOCAL_ONLY' for v in vals),'joint_target_met':sum(v.get('joint_target_met',False) for v in vals),'failed':sum(v['failed'] for v in vals),
   'errors':{k:{'median':float(np.median([v[k] for v in vals if k in v])),'worst_paired_degradation_vs_fixed':max(v[k]-b[k] for v,b in zip(vals,base) if k in v and k in b)} for k in ['a_error_um','d_error_um','prediction_rmse']}}
 summary={'protocol_sha256':digest(PROTOCOL),'metrics':metrics,'stress':stress,'actual_residual_calls':calls,'fit_runs':fits,'profile_runs':4,'model_calls':0,'all_cases_retained':True};save(folder/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
