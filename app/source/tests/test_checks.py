"""Unit fixtures below are synthetic and not solver evidence."""
import copy
from pathlib import Path
import pytest
import numpy as np
from tmm import coh_tmm
from photonguard.core import load,POLICY
from photonguard.checks import evaluate_raw,sensitivity
@pytest.fixture
def task():return load(Path(__file__).parents[1]/'examples/film_n2/task.json')
@pytest.fixture
def raw(task):
 f=np.linspace(1/1.7,1/1.3,task['nfreq'])
 rt=[coh_tmm('s',[1,2,1],[float('inf'),.3,float('inf')],0,1/x) for x in f]
 return {'frequency':f.tolist(),'reference_frequency':f.tolist(),'incident_flux':[1.]*len(f),'reference_reflection_plane_flux':[1.]*len(f),'target_reflection_flux':[-x['R'] for x in rt],'target_transmission_flux':[x['T'] for x in rt]}
def test_reference(task,raw):
 checks,rows=evaluate_raw(raw,task);assert all(c['status']=='PASS' for c in checks)
 assert max(abs(x['R']+x['T']-1) for x in rows)<1e-12
@pytest.mark.parametrize('field',['frequency','reference_frequency','incident_flux','target_reflection_flux','target_transmission_flux'])
def test_nan_stops(task,raw,field):
 raw[field][0]=float('nan');c,r=evaluate_raw(raw,task);assert r is None and c[0]['status']=='INCONCLUSIVE'
@pytest.mark.parametrize('value',[0,-1,1e-15,1e-8])
def test_weak_endpoint_not_dropped(task,raw,value):
 raw['incident_flux'][0]=value;c,r=evaluate_raw(raw,task);assert r is None and c[0]['status']=='INCONCLUSIVE'
def test_missing_endpoint(task,raw):
 raw['frequency'].pop();c,r=evaluate_raw(raw,task);assert c[0]['status']=='INCONCLUSIVE'
def test_wrong_grid(task,raw):
 raw['frequency'][0]+=.001;c,r=evaluate_raw(raw,task);assert c[0]['status']=='INCONCLUSIVE'
def test_no_clipping(task,raw):
 raw['target_reflection_flux'][0]=.2
 c,r=evaluate_raw(raw,task);assert r[0]['R']==-.2
 assert any(x['id']=='physical_bounds' and x['status']=='FAIL' for x in c)
def test_independent_reference(task,raw):
 task['layers'][0]['n']=1.41421356
 c,r=evaluate_raw(raw,task);assert any(x['id']=='independent_tmm' and x['status']=='FAIL' for x in c)
def test_skipped_sensitivity():assert sensitivity(None,None,'grid')['status']=='INCONCLUSIVE'
def test_closed_form_tmm():
 import math
 for n,d,lam in [(2,.3,1.55),(2,.19375,1.55),(2,.3875,1.55),(1,.3,1.55)]:
  f=(n*n-1)**2/(4*n*n);s=math.sin(2*math.pi*n*d/lam)**2
  expected=f*s/(1+f*s)
  got=coh_tmm('s',[1,n,1],[float('inf'),d,float('inf')],0,lam)
  assert abs(got['R']-expected)<1e-12
