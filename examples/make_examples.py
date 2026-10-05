"""Generate labeled development fixtures; these are not held-out test data."""
import copy,json
from pathlib import Path
root=Path(__file__).parent
base_task={"schema_version":1,"case_id":"film_n2","physics":{"dimensions":1,"angle_deg":0,"lossless":True,"dispersive":False,"isotropic":True,"mu":1,"n_incident":1,"n_exit":1},"units_um":1.0,"layers":[{"n":2.0,"thickness_um":0.30}],"wavelength_um":[1.30,1.70],"nfreq":41,"sources":[{"kind":"user-supplied plan","reference":"PhotonGuard initial implementation plan v0.1, section 6","note":"Development fixture confirmation, not a fabricated user study"}]}
base_candidate={"schema_version":1,"adapter":"film1d-v1","case_id":"film_n2","layers":[{"material_kind":"index","material_value":2.0,"thickness_um":.30}],"numerics":{"resolution":80,"after_sources":100,"pml_um":1.0,"air_um":3.0,"source_amplitude":1.0},"workflow":{"subtract_incident":True,"reference_amplitude":1.0,"reference_time_factor":1.0},"origin":{"kind":"synthetic-development-case","patch_round":0}}
cases=[]
def save(name,task,candidate,expected):
 task=copy.deepcopy(task);candidate=copy.deepcopy(candidate)
 task['case_id']=name;candidate['case_id']=name
 if name not in {'film_n2','epsilon_mismatch','stale_normalization','missing_subtraction','valid_shorter_reference'}:
  task['sources']=[{'kind':'synthetic development fixture','reference':f'examples/{name}/task.json','note':'Developer-defined numerical control, not user plan physical intent or a real user case'}]
 folder=root/name;folder.mkdir(exist_ok=True)
 for fn,data in [('task.json',task),('candidate.json',candidate)]:
  (folder/fn).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
 cases.append({'case_id':name,'expected_status':expected,'split':'development','fault_origin':'synthetic injection' if expected=='FAIL' else 'development control'})
save('film_n2',base_task,base_candidate,'PASS')
t=copy.deepcopy(base_task);c=copy.deepcopy(base_candidate);t['layers'][0]['n']=1.;c['layers'][0]['material_value']=1.;save('vacuum',t,c,'PASS')
t=copy.deepcopy(base_task);c=copy.deepcopy(base_candidate)
t['layers']=[{'n':1.45,'thickness_um':.213},{'n':2.1,'thickness_um':.167},{'n':1.7,'thickness_um':.281}]
c['layers']=[{'material_kind':'index','material_value':l['n'],'thickness_um':l['thickness_um']} for l in t['layers']];save('multilayer',t,c,'PASS')
c=copy.deepcopy(base_candidate);c['layers'][0].update(material_kind='epsilon',material_value=2.);save('epsilon_mismatch',base_task,c,'FAIL')
c=copy.deepcopy(base_candidate);c['workflow']['reference_amplitude']=.8;save('stale_normalization',base_task,c,'FAIL')
c=copy.deepcopy(base_candidate);c['workflow']['subtract_incident']=False;save('missing_subtraction',base_task,c,'FAIL')
t=copy.deepcopy(base_task);t['layers'][0]['n']=None;save('unknown_intent',t,base_candidate,'INCONCLUSIVE')
t=copy.deepcopy(base_task);t['physics']['angle_deg']=20;save('unsupported_angle',t,base_candidate,'UNSUPPORTED')

c=copy.deepcopy(base_candidate);c['workflow']['reference_time_factor']=.5;save('valid_shorter_reference',base_task,c,'PASS')
t=copy.deepcopy(base_task);c=copy.deepcopy(base_candidate)
t['layers']=[{'n':3.5,'thickness_um':1.8}]
c['layers']=[{'material_kind':'index','material_value':3.5,'thickness_um':1.8}]
c['numerics']['after_sources']=10;save('underresolved_high_index',t,c,'FAIL')
(root/'development_manifest.json').write_text(json.dumps(cases,indent=2)+'\n')
