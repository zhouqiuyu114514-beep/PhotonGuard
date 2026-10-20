"""Offline developer probe. Synthetic same-physics data, not a blinded benchmark.
Only reads the supplied source and writes to a separate review directory.
No API, FFT, Meep, MPB, user workspace, or production approvals are used.
"""
from pathlib import Path
import json, hashlib, sys, time, io, csv
import numpy as np
import scipy
ROOT=Path('/mnt/data/pg_rc3_review_20261012/input')
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
from photonguard.experiments import inference
from photonguard.core import digest
m=json.loads((ROOT/'MANIFEST.json').read_text())
verified=[]
for name,meta in m['files'].items():
 data=(ROOT/name).read_bytes()
 if len(data)!=meta['bytes'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:
  raise ValueError(name)
 verified.append(name)
settings=json.loads((ROOT/'source/photonguard/observation_library/catalog.json').read_text())[0]['settings']
# Independent formula expression under the SAME ideal physical model.
# This probes implementation and coverage only, not independent model validity.
def synth(x,d,shift,amplitude,background):
 k=633e-6*200
 t=np.pi*20e-3*(x-shift)/k
 envelope=np.ones_like(t); mask=np.abs(t)>1e-12
 envelope[mask]=(np.sin(t[mask])/t[mask])**2
 return background+amplitude*.5*envelope*(1+np.cos(2*np.pi*d*1e-3*(x-shift)/k))
cases=[
 ('P01_in_model',120,-.18,.7,.06,3.,.003,False),
 ('P02_in_model',150,.24,1.2,.02,3.,.004,False),
 ('P03_in_model',210,-.24,.6,.12,3.,.004,False),
 ('P04_in_model',240,.17,1.4,-.02,3.,.005,False),
 ('P05_narrow_scan',180,.03,.9,.03,.3,.004,False),
 ('P06_flat',180,0.,0.,.2,3.,0.,True),
]
rows=[]
for i,(name,d,shift,amp,bg,half,noise,flat) in enumerate(cases):
 x=np.linspace(-half,half,401)
 y=synth(x,d,shift,amp,bg)+np.random.default_rng(62012+i).normal(0,noise,len(x))
 s=io.StringIO();w=csv.writer(s);w.writerow(['position_mm','intensity_relative']);w.writerows(zip(x,y));raw=s.getvalue()
 rawsha=hashlib.sha256(raw.encode()).hexdigest()
 ds={'questions':[],'x_mm':x.tolist(),'intensity':y.tolist(),'rows':len(x),'raw_sha256':rawsha,
     'sha256':digest({'raw_sha256':rawsha,'unit':'mm','source':'SYNTHETIC_REVIEW_PROBE'})}
 p=inference.plan(ds,settings)
 t0=time.perf_counter();r=inference.fit(ds,p);elapsed=time.perf_counter()-t0
 (OUT/(name+'.csv')).write_text(raw)
 (OUT/(name+'.result.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2))
 rows.append({'case':name,'generating_d_um':d,'truth_identifiable_in_case':not flat,'generating_shift_mm':shift,
              'status':r['status'],'warnings':r['warnings'],'usable_for_forward':r['usable_for_forward'],
              'estimated':r.get('estimated_parameters'),'abs_d_error_um':abs(r['estimated_parameters']['slit_separation_um']-d) if not flat and r.get('estimated_parameters') else None,
              'holdout':r.get('metrics',{}).get('holdout'),'actual_residual_calls':r['resources']['actual_residual_calls'],
              'elapsed_seconds':elapsed,'starts':r['resources']['starts_attempted']})
summary={'scope':'Development probes; independent expression of SAME model; not real measurements, blind tests, or AI evaluation.',
 'source_commit':m['source_commit'],'verified_manifest_items':len(verified),
 'python':sys.version,'numpy':np.__version__,'scipy':scipy.__version__,
 'new_fit_calls':len(rows),'new_fft_calls':0,'new_fdtd_calls':0,'new_mpb_calls':0,'new_model_calls':0,
 'production_modified':False,'cases':rows}
(OUT/'readonly_probe_results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
for r in rows: print(r['case'],r['status'],r['estimated']['slit_separation_um'] if r['estimated'] else None,r['warnings'],r['actual_residual_calls'])
print('manifest',len(verified))
