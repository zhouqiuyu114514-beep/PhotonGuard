"""Frozen numerical comparison; same-model synthetic data, not an LLM ablation."""
from pathlib import Path
import copy, io, json, sys, time, hashlib
import numpy as np
from photonguard.core import digest
from photonguard.experiments import inverse_models as m, inverse_profiles as engine, measurement_plan as planner, observation_group as group
PROTOCOL={
 'kind':'PREDECLARED_SYNTHETIC_NUMERICAL_DEVELOPMENT_NOT_BLIND',
 'geometry':[{'a':14.,'d':150.},{'a':20.,'d':180.},{'a':32.,'d':215.}],
 'noise_sd':[.005,.02],'initial_half_ranges':[.4,.8],'seeds':[410,411],
 'new_points_per_strategy':81,'initial_points':81,'fixed_extension_half_range':2.,
 'constraints':{'max_abs_x_mm':5.,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.},
 'comparison':['repeat','fixed_extension','candidate_selected'],
 'fit_runs_max':96,'profile_runs_max':24,'residual_calls_max':3600000,
 'rule':'Per case fit + width profile; planner sees only public candidates, not truth. Same follow-up seed/noise/exposure and point count for all strategies. Keep failures and ties.',
 'independent_validation':'One separate 101-point frozen scan [-4,4], unused by fitting/planning.',
 'limitations':['same ideal physics','not a proof of optimality','no LLM advantage claim','known development suite'],
}
def observe(geom,sd,seed,half,acquisition=0,points=81):
    x=np.linspace(-half,half,points);q=(x-.12)/(.000633*200);u=np.pi*geom['a']*.001*q
    shape=(np.sin(u)/np.where(u==0,1.,u))**2*(1+np.cos(2*np.pi*geom['d']*.001*q))/2
    shape[u==0]=1.
    y=(1. if acquisition==0 else .82)*shape+(.04 if acquisition==0 else .07)+np.random.default_rng(seed).normal(0,sd,len(x))
    out=io.StringIO();np.savetxt(out,np.c_[x,y],delimiter=',',header='position_mm,intensity_relative',comments='')
    return out.getvalue(),x,y
def entry(raw,cfg,index,sd):
    ds=group.parse(raw,m.SLIT,{'source_kind':'SYNTHETIC_TEACHING','source_name':'Frozen numerical development scan '+str(index)})
    g=group.group_entry(ds,cfg,'scan-'+str(index)+'.csv');g.update(approved=True,scale=sd,scale_source='KNOWN_MEASUREMENT_SD');return g
def main(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    (out/'protocol.json').write_text(json.dumps(PROTOCOL,indent=2))
    runs=[];began=time.monotonic();calls=0;opts=0
    for geom in PROTOCOL['geometry']:
      for sd in PROTOCOL['noise_sd']:
       for half in PROTOCOL['initial_half_ranges']:
        for seed in PROTOCOL['seeds']:
         ident=len(runs)+1;folder=out/f'case-{ident:02}';folder.mkdir()
         cfg=group.defaults(m.SLIT);cfg['scale']=sd
         raw,_,_=observe(geom,sd,seed,half);(folder/'initial.csv').write_text(raw)
         scans=[entry(raw,cfg,0,sd)];fit=engine.run(m.plan(scans,cfg))
         profile=engine.run(m.plan(scans,cfg,'profile',parameter='slit_width_um',reference=fit),reference=fit)
         local=[fit,profile];row={'id':ident,'geometry_for_audit_only':geom,'sd':sd,'seed':seed,'half_range':half,'strategies':{},'initial_warning':fit['warnings']}
         try:
          recommendation=planner.propose(scans,cfg,fit,{'slit_width_um':profile},PROTOCOL['constraints'])
          chosen=next(p for p in recommendation['plans'] if p['id']==recommendation['recommended_id']);chosen_half=max(abs(v) for v in chosen['range_mm'])
          row['proposal']={k:recommendation[k] for k in ('recommended_id','resources','limitations')};row['scores']={p['id']:p['score'] for p in recommendation['plans']}
         except ValueError as exc:
          recommendation=None;chosen_half=None;row['proposal_failure']=str(exc)
         vraw,vx,vy=observe(geom,sd,seed+20000,4.,1,101);(folder/'independent-validation.csv').write_text(vraw)
         for strategy,h in [('repeat',half),('fixed_extension',2.),('candidate_selected',chosen_half)]:
          if h is None:row['strategies'][strategy]={'failed':True,'reason':'no public candidate plan'};continue
          newraw,_,_=observe(geom,sd,seed+10000,h,1);(folder/(strategy+'.csv')).write_text(newraw)
          joined=scans+[entry(newraw,cfg,1,sd)];result=engine.run(m.plan(joined,cfg));local.append(result)
          p=result.get('estimated_parameters');item={'status':result['status'],'warnings':result['warnings'],'resources':result['resources'],'failed':p is None,'unresolved':not result['usable_for_forward']}
          if p:
           names,_,_=m.layout(joined,cfg);pars=m.values([p[k] for k in names],names,cfg,1)
           item.update(a_error_um=abs(p['slit_width_um']-geom['a']),d_error_um=abs(p['slit_separation_um']-geom['d']),
             independent_validation_rmse=float(np.sqrt(np.mean((m.predict(vx,pars,m.SLIT)-vy)**2))))
          row['strategies'][strategy]=item
          (folder/(strategy+'-result.json')).write_text(json.dumps(result,ensure_ascii=False))
         (folder/'initial-result.json').write_text(json.dumps(fit,ensure_ascii=False));(folder/'width-profile.json').write_text(json.dumps(profile,ensure_ascii=False))
         if recommendation:(folder/'measurement-plan.json').write_text(json.dumps(recommendation,ensure_ascii=False))
         calls+=sum(r['resources']['actual_residual_calls'] for r in local);opts+=sum(r['resources']['local_optimizations'] for r in local);assert calls<=PROTOCOL['residual_calls_max']
         runs.append(row);(out/'all-cases.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2))
         print('completed',ident,'calls',calls,flush=True)
    summary={}
    for strategy in PROTOCOL['comparison']:
     items=[r['strategies'][strategy] for r in runs];ok=[r for r in items if not r['failed']]
     summary[strategy]={'cases':len(items),'failures':sum(r['failed'] for r in items),'unresolved':sum(r.get('unresolved',True) for r in items),
       **{k:float(np.median([r[k] for r in ok])) if ok else None for k in ('a_error_um','d_error_um','independent_validation_rmse')}}
    for metric in ('a_error_um','d_error_um','independent_validation_rmse'):
     comparisons={'wins':0,'ties':0,'losses':0,'unavailable':0}
     for r in runs:
      a,b=r['strategies']['candidate_selected'],r['strategies']['fixed_extension']
      if metric not in a or metric not in b:comparisons['unavailable']+=1
      elif abs(a[metric]-b[metric])<1e-10:comparisons['ties']+=1
      else:comparisons['wins' if a[metric]<b[metric] else 'losses']+=1
     summary['selected_vs_fixed_'+metric]=comparisons
    receipt={'protocol_sha256':digest(PROTOCOL),'summary':summary,'actual_residual_calls':calls,'local_optimizations':opts,'model_calls':0,'fft_calls':0,'fdtd_calls':0,'elapsed_seconds':time.monotonic()-began,'all_cases_retained':True,'claim':'numerical same-model synthetic comparison; not LLM benefit'}
    (out/'summary.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=='__main__':main(sys.argv[1])
