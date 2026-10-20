import copy,json,hashlib
from pathlib import Path
import pytest
from photonguard.experiments import observation_dialogue as od,observation_workflow as ow,inference as inf,observations as obs
from photonguard.experiments.inference_report import explanation
from photonguard.workflow import WorkflowError
from test_observation_analysis import store,act,sample

TEXT='双缝透镜焦平面截线，波长633nm，透镜焦距200mm，两缝等宽20μm且同相。位置是毫米，缝距估计在90到270微米。其余拟合设置给一个建议。'
def op(field,value,quote,correction=False):return dict(field=field,value=value,quote=quote,correction=correction)
OPS=[op('fixed.measurement_plane','FOURIER_FOCAL_PLANE','双缝透镜焦平面截线'),op('fixed.wavelength_nm',633,'波长633nm'),op('fixed.focal_length_mm',200,'透镜焦距200mm'),op('fixed.slit_width_um',20,'两缝等宽20μm'),op('fixed.relative_phase_rad',0,'同相'),op('position_unit','mm','位置是毫米'),op('bounds.slit_separation_um',[90,270],'缝距估计在90到270微米')]
def proposal(ops=OPS,recipe='training_scale_v1',focus='overview'):return dict(updates=copy.deepcopy(ops),recipe=recipe,focus=focus)
def record():
 d,_=sample();return {'id':'f'*32,'revision':1,'status':'DRAFT','observation':d,'fit_settings':{},'questions':[]}
def install(r,d):return {**r,'fit_settings':d['settings'],'observation':d['dataset'],'observation_facts':d['facts'],'questions':d['questions']}

def test_a01_a04_a05_text_to_plan_and_numerical_sources():
 d=od.apply_proposal(record(),TEXT,proposal());assert not d['questions']
 assert inf.plan(d['dataset'],d['settings'])
 assert d['settings']['bounds']['slit_separation_um']==[90,270]
 assert d['facts']['fixed.focal_length_mm']['source_kind']=='USER_TEXT'
 assert d['facts']['bounds.amplitude']['source_kind']=='NUMERICAL_SUGGESTION'
 assert d['recipe']['training_count']==320 and not d['recipe']['holdout_used']

def test_a02_missing_focal_and_supplement_preserves_other_facts():
 d=od.apply_proposal(record(),TEXT,proposal([p for p in OPS if p['field']!='fixed.focal_length_mm']))
 assert d['missing']==['focal_length_mm']
 r=install(record(),d);d2=od.apply_proposal(r,'补充透镜焦距200mm',proposal([OPS[2]],None))
 assert not d2['questions'] and d2['settings']['fixed']['wavelength_nm']==633

@pytest.mark.parametrize('field,value,quote,text',[
 ('fixed.focal_length_mm',200,'屏幕距离200mm，焦距未知','屏幕距离200mm，焦距未知'),
 ('fixed.focal_length_mm',200,'焦距200mm','如果焦距200mm，会怎样？'),
 ('fixed.focal_length_mm',200,'焦距200mm','焦距200mm不对'),
 ('fixed.relative_phase_rad',0,'同相','并非同相'),
 ('fixed.measurement_plane','FOURIER_FOCAL_PLANE','透镜焦平面','不是透镜焦平面'),
 ('fixed.wavelength_nm',532,'波长633nm','波长633nm'),
 ('fixed.focal_length_mm',200,'焦距20mm','焦距20mm'),
 ('fixed.wavelength_nm',633,'633nm','633nm'),
 ('position_unit','m','位置是毫米','位置是毫米'),
 ('fixed.relative_phase_rad',0,'相位0.2rad','相位0.2rad'),
 ('fixed.relative_phase_rad',0,'同相','不同相'),
])
def test_grounding_rejects_borrowed_negative_and_hypothetical_facts(field,value,quote,text):
 with pytest.raises(ValueError):od.grounded(field,value,quote,text)

def test_a03_plane_and_phase_not_implicitly_supplied():
 d=od.apply_proposal(record(),TEXT,proposal([p for p in OPS if p['field'] not in ('fixed.measurement_plane','fixed.relative_phase_rad')]))
 assert set(d['missing'])=={'measurement_plane','relative_phase_rad'}
 assert not d['settings']['fixed'].get('measurement_plane')

def test_a06_conflict_explicit_correction_and_unknown():
 r=install(record(),od.apply_proposal(record(),TEXT,proposal()))
 d=od.apply_proposal(r,'焦距210mm',proposal([op('fixed.focal_length_mm',210,'焦距210mm')],None))
 assert d['facts']['fixed.focal_length_mm']['status']=='conflict' and d['questions']
 r=install(r,d);d=od.apply_proposal(r,'更正透镜焦距210mm',proposal([op('fixed.focal_length_mm',210,'透镜焦距210mm',True)],None))
 assert not d['questions'] and d['settings']['fixed']['focal_length_mm']==210
 d=od.apply_proposal(install(r,d),'焦距不确定，撤回',proposal([op('fixed.focal_length_mm',None,'焦距不确定',True)],None))
 assert 'focal_length_mm' in d['missing']

def test_recipe_uses_training_only_and_preserves_explicit_configuration():
 d,_=sample();p1,_,_=od.numerical_recipe(d,{})
 bad=copy.deepcopy(d)
 for i in range(0,len(bad['intensity']),5):bad['intensity'][i]=1e8;bad['x_mm'][i]=1e8
 p2,_,_=od.numerical_recipe(bad,{})
 assert p1==p2
 cfg={'bounds':{'center_shift_mm':[-.2,.2],'slit_separation_um':[110,160]},'loss':'linear','f_scale':.025}
 p,_,_=od.numerical_recipe(d,cfg)
 assert p['bounds']['center_shift_mm']==[-.2,.2] and p['bounds']['slit_separation_um']==[110,160]
 assert p['loss']=='linear' and p['f_scale']==.025

PROBES=Path(__file__).resolve().parents[1]/'research/observation-review-20261012'
@pytest.mark.parametrize('ident,truth',[('P01_in_model',120),('P02_in_model',150),('P03_in_model',210),('P04_in_model',240),('P05_narrow_scan',None),('P06_flat',None)])
def test_known_review_probes_preserve_source_and_diagnostics(ident,truth):
 m=json.loads((PROBES/'SOURCE.json').read_text());raw=(PROBES/(ident+'.csv')).read_bytes()
 assert hashlib.sha256(raw).hexdigest()==m['files'][ident+'.csv']['sha256']
 d=obs.parse_csv(raw.decode(),source_name=ident,source_kind='SYNTHETIC_TEACHING');_,s=sample()
 r=inf.fit(d,inf.plan(d,s))
 if truth is not None:assert r['usable_for_forward'] and abs(r['estimated_parameters']['slit_separation_um']-truth)<.1
 else:assert not r['usable_for_forward'] and 'INSUFFICIENT_INFORMATION' in r['warnings']

def test_new_recipe_handles_changed_example_and_narrow_scan():
 for ident,usable in [('P02_in_model',True),('P05_narrow_scan',False)]:
  r=record();r['observation']=obs.parse_csv((PROBES/(ident+'.csv')).read_text(),source_name=ident)
  d=od.apply_proposal(r,TEXT,proposal());result=inf.fit(d['dataset'],inf.plan(d['dataset'],d['settings']))
  assert result['usable_for_forward'] is usable
  if usable:assert abs(result['estimated_parameters']['slit_separation_um']-150)<.1

def test_a09_explanation_current_numbers_no_improvement_claim():
 d,s=sample('OBS02');r=inf.fit(d,inf.plan(d,s));record=dict(id='e'*32,observation=d,fit_settings=s,fit_result=r)
 text=explanation(record,'outliers')
 assert '401' in text and '320' in text and '81' in text and 'soft_l1' in text and '不能给出改善百分比' in text
 assert '不是独立实验' in text and '相近质量' not in text
 text=explanation(record,'parameters');assert '633' in text and '180.009' in text and '不是四参数全空间搜索' in text

def test_ai_draft_no_auto_compute_or_facts_from_false_answer(store):
 s=ow.create(store,{'csv_text':(ow.SAMPLES/'OBS01.csv').read_text(),'source_name':'uploaded synthetic'})
 class Client:
  def preflight(self):pass
  def complete(self,*args):return {'assistant':{'content':json.dumps(proposal())},'audit':{'status':'ASSISTANT_RETURNED','live_dispatch':False}}
 store.owner.product_client=Client()
 with pytest.raises(WorkflowError):act(store,s,'fit_wizard',text=TEXT,approve_data=False)
 s=act(store,s,'fit_wizard',text=TEXT,approve_data=True)
 assert s['status']=='PLANNED' and s['fit_ai_guidance']['status']=='ACCEPTED'
 assert not s.get('fit_approved_sha256') and s['analysis_ledger']['fit_runs_reserved']==0
 old=copy.deepcopy(s['fit_settings'])
 s=act(store,s,'fit_wizard',text='屏幕距离200mm，焦距未知',approve_data=True)
 assert s['fit_ai_guidance']['status']=='NEEDS_REVIEW' and s['fit_settings']==old

def test_a11_explicit_budget_candidate_selection_keeps_grid_and_ledger(store):
 from test_case_recovery import completed
 s=completed(store);s['estimate_origin']={'source_kind':'MODEL_ESTIMATE','record_id':'b'*32}
 # Permit a single candidate by remaining output, without changing the grid.
 from photonguard.experiments.case_workflow import budget_preview
 preview=budget_preview(store,s,s['plan']);one=(preview['estimated_output_bytes']-1024**2)//3
 s['exploration_ledger']['used_output_bytes']=s['exploration_ledger']['output_limit_bytes']-(one+2*1024**2)
 store.save(s);ledger=copy.deepcopy(s['exploration_ledger'])
 request={'case_id':'D02','bounds':{'min':120,'max':230},'goal':{'metric':'fringe_period_mm','operator':'near','target':.8,'tolerance':.02}}
 c=act(store,s,'explore_case',new_exploration=True,case_id='D02',request=request)
 assert c['status']=='NEEDS_INFORMATION' and c['budget_preview']['allowed_candidates']==1
 choice=c['candidate_choice'];value=choice['values'][1]
 with pytest.raises(WorkflowError):act(store,c,'choose_observation_candidate',approve_selection=False,choice_sha256=choice['sha256'],slit_separation_um=value)
 c=act(store,c,'choose_observation_candidate',approve_selection=True,choice_sha256=choice['sha256'],slit_separation_um=value)
 assert c['status']=='PLANNED' and len(c['plan']['candidates'])==1
 assert c['spec']['known_parameters']['grid_size']==s['spec']['known_parameters']['grid_size']
 assert store.get(s['id'])['exploration_ledger']==ledger and not c.get('approved_plan_sha256')

def test_later_text_changes_create_version_and_manual_override_stays_current(store):
 s=ow.create(store,{'sample_id':'OBS01'});s=act(store,s,'fit_plan',settings=s['fit_settings'])
 s['fit_approved_sha256']=s['fit_plan']['sha256'];s['status']='FAILED';s['analysis_ledger']['fit_runs_reserved']=1;store.save(s)
 class Client:
  def preflight(self):pass
  def complete(self,*args):return {'assistant':{'content':json.dumps(proposal([op('fixed.focal_length_mm',210,'焦距210mm',True)],None))},'audit':{'status':'ASSISTANT_RETURNED','live_dispatch':False}}
 store.owner.product_client=Client();old=copy.deepcopy(s)
 c=act(store,s,'fit_wizard',text='更正焦距210mm',approve_data=True)
 assert c['id']!=s['id'] and c['parent_id']==s['id'] and c['observation_root']==s['id']
 assert store.get(s['id'])['fit_settings']==old['fit_settings'] and store.get(s['id'])['analysis_ledger']['fit_runs_reserved']==1
 settings=copy.deepcopy(c['fit_settings']);settings['fixed']['focal_length_mm']=220
 c=act(store,c,'fit_plan',settings=settings)
 d=od.apply_proposal(c,'请解释下一步',proposal([],None,'next_step'))
 assert d['settings']['fixed']['focal_length_mm']==220 and d['facts']['fixed.focal_length_mm']['source_kind']=='USER_FORM'

def test_unknown_coordinate_unit_needs_statement_and_never_relabels_pixels():
 raw=(ow.SAMPLES/'OBS01.csv').read_text().replace('position_mm','position')
 r=record();r['observation']=obs.parse_csv(raw,source_name='unlabeled')
 d=od.apply_proposal(r,TEXT,proposal());assert not d['questions'] and d['dataset']['raw_sha256']==r['observation']['raw_sha256']
 assert d['dataset']['sha256']!=r['observation']['sha256'] and d['dataset']['position_unit']=='mm'
 r['observation']=obs.parse_csv(raw.replace('position,','pixel,'),source_name='pixel')
 d=od.apply_proposal(r,TEXT,proposal());assert d['questions'] and d['dataset']['x_mm'] is None

def test_single_source_version_metadata():
 import tomllib,photonguard
 cfg=tomllib.loads((Path(__file__).resolve().parents[1]/'pyproject.toml').read_text())
 assert 'version' in cfg['project']['dynamic'] and 'version' not in cfg['project']
 assert cfg['tool']['setuptools']['dynamic']['version']['attr']=='photonguard.__version__'
 assert photonguard.__version__==json.loads((Path(__file__).resolve().parents[1]/'release/claims.json').read_text())['version']

def test_explicit_nonzero_phase_is_recorded_as_inapplicable_not_silently_zero():
 r=install(record(),od.apply_proposal(record(),TEXT,proposal()))
 d=od.apply_proposal(r,'更正相位差1rad',proposal([op('fixed.relative_phase_rad',1,'相位差1rad',True)],None))
 assert d['settings']['fixed']['relative_phase_rad']==1 and any('相位' in q for q in d['questions'])

def test_source_binding_preserves_unicode_review_names(tmp_path,monkeypatch):
 import subprocess
 from photonguard import approved_gui as gui
 def git(*args):return subprocess.check_output(['git','-C',str(tmp_path),*args],text=True).strip()
 git('init','-q');names=['下一版验收条件.json','quoted"file.json','line\nbreak.json']
 for name in names:(tmp_path/name).write_text('{}')
 git('add','.');git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture')
 monkeypatch.setattr(gui,'FROZEN_BASE',git('rev-parse','HEAD'))
 manifest=gui.source_manifest(tmp_path)
 assert set(manifest['files'])==set(names)
