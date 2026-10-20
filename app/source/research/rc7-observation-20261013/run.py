"""Frozen 6 development + 6 check scenarios; 24 bounded fits, no model API.

Generator uses scalar trigonometry, analysis uses NumPy sinc/cos. They still
share the same ideal geometry/known intensity averaging model: this is a
synthetic engineering check, not a blind instrument validation.
"""
import copy
import json
import math
import sys
import time
from pathlib import Path
import numpy as np
from photonguard.core import digest
from photonguard.experiments import inverse_models as m, inverse_profiles as engine
from photonguard.experiments import observation_group as ow, observations
from photonguard.experiments.observation_contract import INDEPENDENT

DEVELOPMENT=[
 {'kind':'point','a':18.,'d':163.,'sd':.004,'half':3.7,'kernel_half':0.,'seed':7311,'nonuniform':False},
 {'kind':'point','a':27.,'d':202.,'sd':.007,'half':4.3,'kernel_half':0.,'seed':7312,'nonuniform':True},
 {'kind':'calibrated_average','a':18.,'d':163.,'sd':.004,'half':3.7,'kernel_half':.10,'seed':7313,'nonuniform':False},
 {'kind':'calibrated_average','a':27.,'d':202.,'sd':.007,'half':4.3,'kernel_half':.14,'seed':7314,'nonuniform':True},
 {'kind':'local_confounded','a':18.,'d':163.,'sd':.004,'half':.45,'kernel_half':.10,'seed':7315,'nonuniform':False},
 {'kind':'local_confounded','a':27.,'d':202.,'sd':.007,'half':.35,'kernel_half':.14,'seed':7316,'nonuniform':True},
]
CHECK=[
 {'kind':'point','a':22.,'d':184.,'sd':.005,'half':3.3,'kernel_half':0.,'seed':8411,'nonuniform':True},
 {'kind':'point','a':31.,'d':218.,'sd':.009,'half':4.6,'kernel_half':0.,'seed':8412,'nonuniform':False},
 {'kind':'calibrated_average','a':22.,'d':184.,'sd':.005,'half':3.3,'kernel_half':.07,'seed':8413,'nonuniform':True},
 {'kind':'calibrated_average','a':31.,'d':218.,'sd':.009,'half':4.6,'kernel_half':.18,'seed':8414,'nonuniform':False},
 {'kind':'local_confounded','a':22.,'d':184.,'sd':.005,'half':.55,'kernel_half':.07,'seed':8415,'nonuniform':True},
 {'kind':'local_confounded','a':31.,'d':218.,'sd':.009,'half':.30,'kernel_half':.18,'seed':8416,'nonuniform':False},
]
PROTOCOL={
 'schema':'photonguard.rc7-observation-study.v1','study_kind':'PREDECLARED_SYNTHETIC_DEVELOPMENT_AND_FROZEN_CHECK_NOT_BLIND',
 'development_cases':DEVELOPMENT,'check_cases':CHECK,'fit_runs_max':24,'profile_runs_max':0,
 'residual_calls_max':720000,'fits_per_scenario':2,'arms':['point_model','calibrated_kernel_model'],
 'points':101,'validation_points':127,'fit_loss':'linear','weighting':INDEPENDENT,
 'rules':['Both arms see exactly the same fitting observations, bounds, loss, starting grid and residual budget.',
          'Known kernel is returned by a separate teaching calibration observation before fitting; it is never inferred from geometry truth or residuals.',
          'Held-out independent teaching scan generated after both fits; not used for arm selection, fitting, tuning or threshold changes.',
          '6 development then 6 different check scenarios. All 12 conditions are frozen before the first fit; all outputs including failures retained.',
          'No additional fits after a negative result; no automatic blur diagnosis; local single-frequency equivalence is shown separately without fitting.'],
 'limitations':['Ideal synthetic physics is shared by generator and analyzer; no real instrument claim.',
                'Known discrete physical-coordinate kernel only; no unknown PSF recovery or general coherent aberrations.',
                'A point control uses independently declared delta kernel; this prevents manufacturing a blur alarm, not a test of every incorrect kernel.',
                'Local confounded cases are narrow full-envelope scans. The exact single-frequency identity is a separate algebraic evidence file.',
                'Interleaved fit holdout remains the same acquisition and is not independent instrument evidence.'],
 'sources':['https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html'],
}


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


class IndependentTeachingObject:
    def __init__(self,case):
        self.case=copy.deepcopy(case)
        width=case['kernel_half']
        self.offsets=[0.] if width==0 else np.linspace(-width,width,13).tolist()
        masses=[1.] if width==0 else [1+min(i,12-i) for i in range(13)]
        self.weights=[v/sum(masses) for v in masses]

    def calibration_observation(self):
        return {'kind':'CALIBRATED_INTENSITY_AVERAGE','kernel':{
            'offsets_mm':list(self.offsets),'weights':list(self.weights),
            'source':'TEACHING_GENERATOR','reference':'Independent teaching calibration impulse-mass observation; instrument response fixed before fitting'},
            }

    def observe(self,x,stage):
        c=self.case;rng=np.random.default_rng(c['seed']+10000*stage);values=[]
        for coordinate in x:
            shape=0.
            for offset,weight in zip(self.offsets,self.weights):
                q=(float(coordinate)-offset-.09)/(.000633*200)
                arg=math.pi*c['a']*.001*q
                envelope=(math.sin(arg)/arg)**2 if abs(arg)>1e-14 else 1.
                # Algebraically equal geometry, independently implemented evaluation.
                shape+=weight*envelope*(1+math.cos(2*math.pi*c['d']*.001*q))/2
            values.append(.9*shape+.055+rng.normal(0,c['sd']))
        raw='position_mm,intensity_relative\n'+'\n'.join(f'{float(a):.17g},{float(b):.17g}' for a,b in zip(x,values))+'\n'
        return raw,np.asarray(values)


def local_identity():
    x=np.linspace(-1.,1.,301);offsets=np.linspace(-.1,.1,13);weights=np.asarray([1+min(i,12-i) for i in range(13)],dtype=float);weights/=sum(weights)
    nu=184/(633*.001*200);A=.9;B=.055;H=float(np.sum(weights*np.cos(2*np.pi*nu*offsets)))
    Aprime=A*H;Bprime=B+A*(1-H)/2;errors=[]
    for phi in (0.,.7,1.6):
        observed=sum(w*(A/2*(1+np.cos(2*np.pi*nu*(x-d)+phi))+B) for d,w in zip(offsets,weights))
        absorbed=Aprime/2*(1+np.cos(2*np.pi*nu*x+phi))+Bprime
        errors.append({'phase_rad':phi,'maximum_absolute_difference':float(np.max(np.abs(observed-absorbed)))})
    return {'type':'ALGEBRAIC_SINGLE_FREQUENCY_IDENTITY_NOT_FIT','frequency_per_mm':nu,'response_H':H,
            'original':{'amplitude':A,'background':B},'equivalent_unblurred':{'amplitude':Aprime,'background':Bprime},
            'phase_checks':errors,'decision':'INDISTINGUISHABLE_WITH_FREE_AMPLITUDE_BACKGROUND; REQUEST_INDEPENDENT_CALIBRATION_OR_STOP',
            'scope':'Exactly constant local envelope, symmetric normalized kernel; full varying envelope need not be indistinguishable.',
            'fit_runs':0,'model_calls':0}


def main(destination):
    folder=Path(destination);folder.mkdir(parents=True,exist_ok=False);save(folder/'protocol.json',PROTOCOL)
    began=time.monotonic();fit_count=0;calls=0;rows=[]
    for phase,cases in [('development',DEVELOPMENT),('check',CHECK)]:
        save(folder/(phase+'-frozen-before-execution.json'),{'cases':cases,'protocol_sha256':digest(PROTOCOL),'fit_runs_before_phase':fit_count,'no_retuning':True})
        for index,case in enumerate(cases,1):
            out=folder/f'{phase}-{index:02}';out.mkdir();obj=IndependentTeachingObject(case)
            calibration=obj.calibration_observation();save(out/'public-independent-calibration.json',calibration)
            uniform=np.linspace(-1,1,101);xx=case['half']*(np.sign(uniform)*abs(uniform)**1.35 if case['nonuniform'] else uniform)
            raw,_=obj.observe(xx,0);(out/'initial.csv').write_text(raw,encoding='utf-8')
            cfg=ow.defaults(m.SLIT);cfg['weighting']=INDEPENDENT;cfg['scale']=case['sd'];cfg['scale_source']='KNOWN_MEASUREMENT_SD'
            dataset=observations.parse_csv(raw,source_kind='SYNTHETIC_TEACHING',source_name='Frozen RC7 observation applicability scenario')
            base={'dataset':dataset,'conditions':m.physical(cfg),'scale':case['sd'],'scale_source':'KNOWN_MEASUREMENT_SD','raw_file':'initial.csv','approved':True,
                  'noise':{'sigma':case['sd'],'independent':True,'source':'TEACHING_GENERATOR','reference':'Separate seeded independent Gaussian draws at each declared physical location','acquisition_id':f'{phase}-{index}-initial'}}
            results={}
            for arm in PROTOCOL['arms']:
                if fit_count>=24:raise RuntimeError('Frozen study fit budget exhausted')
                group=copy.deepcopy(base);group['observation']={'kind':'POINT_SAMPLE'} if arm=='point_model' else copy.deepcopy(calibration)
                plan=m.plan([group],cfg);save(out/(arm+'-plan.json'),plan)
                # Reserve each requested fit before it starts; failure stays charged.
                fit_count+=1;save(folder/'running-ledger.json',{'fit_runs_reserved':fit_count,'actual_residual_calls':calls,'current':f'{phase}-{index}/{arm}'})
                result=engine.run(plan);calls+=result['resources']['actual_residual_calls'];save(out/(arm+'-result.json'),result)
                if calls>PROTOCOL['residual_calls_max']:raise RuntimeError('Frozen residual budget exceeded')
                results[arm]=(group,result)
            vx=np.linspace(-4.8,4.8,127);validation_raw,vy=obj.observe(vx,1);(out/'independent-teaching-validation.csv').write_text(validation_raw,encoding='utf-8')
            row={'phase':phase,'scenario':index,'kind':case['kind'],'evaluator_only_geometry':case,'calibration_sha256':digest(calibration),'arms':{}}
            for arm,(group,result) in results.items():
                item={'failed':not bool(result.get('estimated_parameters')),'warnings':result['warnings'],'status':result['status'],'resources':result['resources'],'calibration_used':result['observation_assessment'][0]['calibrated_kernel_used']}
                if result.get('estimated_parameters'):
                    pars=result['estimated_parameters'];names,_,_=m.layout([group],cfg);full=m.values([pars[k] for k in names],names,cfg)
                    predicted=m.predict_observation(vx,full,m.SLIT,group)
                    item.update(width_error_um=abs(pars['slit_width_um']-case['a']),separation_error_um=abs(pars['slit_separation_um']-case['d']),
                                training_rmse=result['data'][0]['training_rmse'],independent_teaching_rmse=float(np.sqrt(np.mean((predicted-vy)**2))))
                row['arms'][arm]=item
            rows.append(row);save(folder/'all-cases.json',rows);print(phase,index,'fits',fit_count,'calls',calls,flush=True)
    identity=local_identity();save(folder/'single-frequency-indistinguishable.json',identity)
    aggregate={}
    for kind in ('point','calibrated_average','local_confounded'):
        subset=[r for r in rows if r['kind']==kind];comparisons={}
        for metric in ('width_error_um','separation_error_um','independent_teaching_rmse'):
            differences=[r['arms']['calibrated_kernel_model'][metric]-r['arms']['point_model'][metric] for r in subset if metric in r['arms']['point_model'] and metric in r['arms']['calibrated_kernel_model']]
            comparisons[metric]={'paired_differences_calibrated_minus_point':differences,'improved':sum(d<-1e-10 for d in differences),'worse':sum(d>1e-10 for d in differences),'ties':sum(abs(d)<=1e-10 for d in differences),'worst_paired_degradation':max(differences,default=None)}
        aggregate[kind]={'scenarios':len(subset),'comparisons':comparisons}
    summary={'protocol_sha256':digest(PROTOCOL),'development_scenarios':6,'check_scenarios':6,'fit_runs':fit_count,'profile_runs':0,
             'actual_residual_calls':calls,'local_optimizations':sum(a['resources']['local_optimizations'] for r in rows for a in r['arms'].values()),
             'model_calls':0,'fft_calls':0,'fdtd_calls':0,'elapsed_seconds':time.monotonic()-began,'all_cases_retained':True,'aggregate':aggregate,
             'conclusion':'Known calibration is applied to physical coordinates. Paired synthetic effects are scenario-specific; low residual alone does not diagnose or exclude averaging. Local exact single frequency remains indistinguishable with free A/B.',
             'not_claimed':['general blur detection','recovered unknown PSF','instrument accuracy','confidence interval','AI numerical advantage']}
    save(folder/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main(sys.argv[1])
