import copy
import io
import time
import zipfile
import numpy as np
import pytest
from photonguard.core import digest
from photonguard.workflow import WorkflowStore, WorkflowError
from photonguard.experiments.service import store_for
from photonguard.experiments import inverse_models as m, inverse_profiles as prof, observation_group as ow
from photonguard.experiments import gaussian_inference as gi, measurement_plan as mp, teaching_acquisition as ta

def data(model=m.SLIT, span=5, count=81, seed=8):
    cfg=ow.defaults(model);x=np.linspace(-span,span,count) if model==m.SLIT else np.linspace(-60,140,count)
    if model==m.SLIT:
        q=(x-.12)/(.000633*200);u=np.pi*.02*q;y=np.where(u==0,1.,np.sin(u)/np.where(u==0,1.,u))**2*(1+np.cos(2*np.pi*.18*q))/2+.04
        header='position_mm,intensity_relative';sigma=.01
    else:
        y=1000*np.sqrt(.08**2+((x-40)*.000633/(np.pi*.08))**2);header='z_mm,radius_1e2_um';sigma=.5
    y+=np.random.default_rng(seed).normal(0,sigma,len(x));raw=header+'\n'+'\n'.join(f'{a},{b}' for a,b in zip(x,y))
    ds=ow.parse(raw,model,{'source_kind':'SYNTHETIC_TEACHING','source_name':'frozen development case'})
    group=[ow.group_entry(ds,cfg,'scan-0.csv')];group[0]['approved']=True
    return group,cfg,raw

@pytest.fixture
def store(tmp_path):
    owner=WorkflowStore(tmp_path/'store',allow_workers=True)
    yield store_for(owner)
    owner.close()

def act(store,s,kind,**kw):return store.action(s['id'],{'type':kind,'expected_revision':s['revision'],**kw})

def planned(store,s):
    cfg=s['inverse_settings'];entries=[{'conditions':m.physical(cfg),'scale':g['scale'],'scale_source':g['scale_source'],'approved':True} for g in s['groups']]
    return act(store,s,'inverse_plan',settings=cfg,entries=entries)

def wait(store,s):
    for _ in range(400):
        s=store.get(s['id'])
        if s['status']!='RUNNING' and s['id'] not in store.running:return s
        time.sleep(.05)
    raise AssertionError('worker not complete')

def test_model_roles_keep_known_parameters_and_reject_unknown_scale():
    group,cfg,_=data();cfg['fixed']['slit_width_um']=20.;cfg['bounds'].pop('slit_width_um');p=m.plan(group,cfg)
    assert p['parameter_roles']['slit_width_um']=='USER_CONFIRMED_FIXED'
    assert 'slit_width_um' not in m.layout(group,cfg)[0]
    cfg['bounds']['wavelength_nm']=[500,700]
    with pytest.raises(ValueError):m.plan(group,cfg)

@pytest.mark.parametrize('bad',['relative_phase_rad','focal_length_mm','measurement_plane'])
def test_unknown_required_physics_not_fitted(bad):
    group,cfg,_=data();cfg['fixed'].pop(bad)
    with pytest.raises(ValueError):m.plan(group,cfg)

def test_profiles_and_narrow_coverage_are_not_unique_and_split_not_changed():
    group,cfg,_=data(span=.6);p=m.plan(group,cfg);r=prof.run(p)
    assert not r['usable_for_forward'] and 'INSUFFICIENT_WIDTH_COVERAGE' in r['warnings']
    pp=m.plan(group,cfg,'profile',parameter='slit_width_um',grid_points=21,reference=r);pr=prof.run(pp,reference=r)
    assert len(pr['rows'])==21 and len(pr['starts'])<=42 and pr['confidence_interval'] is None
    assert pr['data_use']==r['data_use'] and pr['resources']['actual_residual_calls']<=30000
    assert len(pr['components'])>=1 and 'MULTIPLE_PROFILE_CANDIDATES' in pr['warnings']
    assert not ow.can_adopt({'inverse_result':r,'inverse_profiles':{'slit_width_um':pr}})

def test_disjoint_components_do_not_bridge_failure():
    rows=[{'value':i,'accepted':a} for i,a in enumerate([True,True,False,True,False,True])]
    assert prof.components(rows)==[[0,1],[3],[5]]

def test_failed_profile_points_preserved(monkeypatch):
    group,cfg,_=data();r=prof.run(m.plan(group,cfg));p=m.plan(group,cfg,'profile',parameter='slit_width_um',grid_points=3,reference=r)
    import scipy.optimize
    def fail(*a,**kw):raise ValueError('frozen failure')
    monkeypatch.setattr(scipy.optimize,'least_squares',fail);result=prof.run(p,reference=r)
    assert len(result['rows'])==3 and all(not x['success'] for x in result['rows'])
    assert 'UNRESOLVED_PROFILE_POINTS' in result['warnings'] and not result['usable_for_forward']

def test_canonical_plan_rejects_rehashed_split_or_budget():
    group,cfg,_=data();p=m.plan(group,cfg)
    p['splits'][0]['holdout_indices']=[1];p['sha256']=digest({k:v for k,v in p.items() if k!='sha256'})
    with pytest.raises(ValueError):m.verify_plan(p)

def test_joint_independent_brightness_and_centers_raw_retained():
    group,cfg,raw=data(span=5);second=copy.deepcopy(group[0]);second['dataset']['intensity']=[.72*v+.08 for v in second['dataset']['intensity']]
    second['dataset']['sha256']=digest({k:v for k,v in second['dataset'].items() if k!='sha256'});group.append(second);cfg['registration']='INDEPENDENT'
    before=copy.deepcopy(group);r=prof.run(m.plan(group,cfg))
    assert group==before and len(r['data'])==2
    p=r['estimated_parameters'];assert abs(p['amplitude@1']/p['amplitude@0']-.72)<.02
    assert abs(p['background@1']-(.72*p['background@0']+.08))<.002
    assert {'center_shift_mm@0','center_shift_mm@1'}<=set(p)

def test_measurement_plan_equal_points_no_fft_and_q_equivalence():
    group,cfg,_=data(span=.6);r=prof.run(m.plan(group,cfg));pr=prof.run(m.plan(group,cfg,'profile',parameter='slit_width_um',reference=r),reference=r)
    constraints={'max_abs_x_mm':5,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}
    design=mp.propose(group,cfg,r,{'slit_width_um':pr},constraints)
    assert len(design['plans'])==3 and {p['points'] for p in design['plans']}=={81} and design['resources']['candidate_count']<=12
    assert design['resources']['fft_calls']==0 and design['resources']['model_calls']==0
    names,_,_=m.layout(group,cfg);pars=m.values([r['estimated_parameters'][k] for k in names],names,cfg)
    x=np.linspace(-3,3,51);a=m.predict(x,pars,m.SLIT);p2=pars|{'focal_length_mm':400,'center_shift_mm':2*pars['center_shift_mm']}
    assert np.allclose(a,m.predict(2*x,p2,m.SLIT),atol=1e-12)

def test_frozen_simulator_does_not_receive_fit_and_is_repeatable(tmp_path):
    commitment=ta.create(tmp_path,'object',m.SLIT)
    kw=dict(model=m.SLIT,acquisition_index=1,lower=-5,upper=5,points=81)
    a=ta.acquire(tmp_path,'object',commitment['commitment_sha256'],**kw);b=ta.acquire(tmp_path,'object',commitment['commitment_sha256'],**kw)
    assert a==b and 'geometry' not in commitment
    with pytest.raises(TypeError):ta.acquire(tmp_path,'object',commitment['commitment_sha256'],fitted_parameters=[1,2],**kw)
    with pytest.raises(ValueError):ta.acquire(tmp_path,'object',commitment['commitment_sha256'],**(kw|{'acquisition_index':3}))

def test_gaussian_single_plane_and_width_conventions():
    raw='z_mm,radius_1e2_um\n0,128.6451';ds=gi.parse_csv(raw,source_kind='USER_PROVIDED',source_name='one plane');cfg=ow.defaults(m.GAUSSIAN);g=ow.group_entry(ds,cfg,'one.csv');g['approved']=True
    with pytest.raises(ValueError,match='单平面'):m.plan([g],cfg)
    with pytest.raises(ValueError):gi.parse_csv('z_mm,FWHM_um\n0,120',source_kind='USER_PROVIDED',source_name='unknown convention')
    raw='z_mm,diameter_1e2_um,diameter_sd_um\n0,200,2'
    with pytest.raises(ValueError):gi.parse_csv(raw,source_kind='USER_PROVIDED',source_name='diameter')
    d=gi.parse_csv(raw,source_kind='USER_PROVIDED',source_name='diameter',diameter_conversion=True)
    assert d['radius_um']==[100] and d['sd_um']==[1] and d['conversion']=='EXPLICIT_DIAMETER_DIVIDE_TWO'

def test_gaussian_direct_radius_fit_and_short_scan_guard():
    group,cfg,_=data(m.GAUSSIAN,count=21);r=prof.run(m.plan(group,cfg));assert r['usable_for_forward'],r['warnings']
    assert abs(r['estimated_parameters']['waist_radius_um']-80)<1 and abs(r['estimated_parameters']['waist_z_mm']-40)<1
    ds=group[0]['dataset'];x=np.linspace(39,41,101);ds.update(x_mm=x.tolist(),rows=len(x),radius_um=gi.predict(x,80,40,633).tolist());ds['sha256']=digest({k:v for k,v in ds.items() if k!='sha256'})
    r=prof.run(m.plan(group,cfg));assert not r['usable_for_forward'] and 'INSUFFICIENT_CAUSTIC_COVERAGE' in r['warnings']

def test_worker_approval_export_and_shared_root_budget(store):
    s=ow.create(store,{'model':m.GAUSSIAN,'teaching':True});s=planned(store,s)
    with pytest.raises(WorkflowError):act(store,s,'inverse_run',approve=False,plan_sha256=s['inverse_plan']['sha256'])
    s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    assert s['status']=='COMPLETED' and s['inverse_result']['usable_for_forward'];ow.verify(store,s)
    with zipfile.ZipFile(io.BytesIO(store.export_family(s['id']))) as z:
        assert not any('private-teaching' in name or 'object.json' in name for name in z.namelist())
        assert any(name.endswith('scan-0.csv') for name in z.namelist())
    child=act(store,s,'inverse_revise');root=store.get(s['id']);root['inverse_ledger']['fit_runs_reserved']=4;store.save(root)
    child=planned(store,child)
    with pytest.raises(WorkflowError,match='累计额度'):act(store,child,'inverse_run',approve=True,plan_sha256=child['inverse_plan']['sha256'])

def test_gaussian_forward_converts_global_waist_and_keeps_three_lenses(store):
    group,cfg,raw=data(m.GAUSSIAN,count=21);s=ow.create(store,{'model':m.GAUSSIAN,'csv_text':raw,'source_kind':'SYNTHETIC_TEACHING','source_name':'known test'})
    s['inverse_settings']=cfg;store.save(s);s=planned(store,s);s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    child=act(store,s,'inverse_forward',approve_estimate=True,geometry={'lens_z_mm':180.,'screen_distance_mm':100.,'z_max_mm':200.,'focal_lengths_mm':[75.,100.,150.],'target_radius_um':300.})
    assert len(child['plan']['candidates'])==3
    assert child['spec']['known_parameters']['waist_z_mm']==pytest.approx(s['inverse_result']['estimated_parameters']['waist_z_mm']-180)
    assert child['spec']['parameter_sources']['waist_z_mm']['source_kind']=='MODEL_ESTIMATE'

def test_missing_scipy_new_plan_keeps_old_forward_catalog(store,monkeypatch):
    s=planned(store,ow.create(store,{'model':m.GAUSSIAN,'teaching':True}));original=ow.importlib.util.find_spec
    monkeypatch.setattr(ow.importlib.util,'find_spec',lambda name:None if name=='scipy' else original(name))
    with pytest.raises(WorkflowError,match='SciPy'):act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256'])
    assert {r['domain'] for r in store.bootstrap()['case_library']}=={'film','diffraction','gaussian'}

@pytest.mark.parametrize('field,value,quote,text',[
 ('bounds.slit_width_um',[8,45],'缝宽8到45微米','如果缝宽8到45微米'),
 ('fixed.waist_radius_um',80,'束腰半径80微米','束腰半径80微米不是已知条件'),
 ('fixed.focal_length_mm',200,'屏幕距离200mm','屏幕距离200mm'),
])
def test_ai_grounding_does_not_borrow_or_invent_facts(field,value,quote,text):
    from photonguard.experiments.inverse_report import grounded
    with pytest.raises(ValueError):grounded(field,value,quote,text)

def test_profile_child_preserves_comparison_origin_and_no_raw_replacement(store):
    group,cfg,raw=data()
    s=ow.create(store,{'model':m.SLIT,'csv_text':raw,'source_kind':'SYNTHETIC_TEACHING','source_name':'source'})
    s['comparison_origin']={'record_id':'prior','profiles':{'a':{'components':[[17,18],[21]]}}};store.save(s)
    child=ow.revise(store,s,keep_results=True)
    assert child['comparison_origin']==s['comparison_origin']
    assert (store.folder(child['id'])/'scan-0.csv').read_bytes()==raw.encode()

def test_numerical_recipe_only_training_points_and_keeps_fixed_values(store):
    group,cfg,raw=data(span=.6)
    s=ow.create(store,{'model':m.SLIT,'csv_text':raw,'source_kind':'SYNTHETIC_TEACHING','source_name':'source'})
    s['inverse_settings']['fixed']['center_shift_mm']=.12;store.save(s)
    s=act(store,s,'inverse_recipe')
    assert s['inverse_settings']['fixed']['center_shift_mm']==.12 and 'center_shift_mm' not in s['inverse_settings']['bounds']
    assert s['numerical_recipe']['holdout_used'] is False and s['numerical_recipe']['training_count']==64
    assert 'slit_width_um' not in s['inverse_settings']['bounds'] and 'focal_length_mm' not in s['inverse_settings']['fixed']

def test_exact_localized_enum_and_quoted_bounds_adapter(store):
    import json
    class Client:
        def preflight(self):pass
        def complete(self,*args):
            return {'assistant':{'content':json.dumps({'updates':[
                {'id':'U1','field':'fixed.m2','value':1,'quote':'M²=1','correction':False},
                {'id':'U2','field':'fixed.propagation','value':'FREE_SPACE','quote':'自由传播','correction':False},
                {'id':'U3','field':'bounds.waist_radius_um','value':[20,180],'quote':'束腰半径20到180微米','correction':False}], 'focus':'parameters','suggestions':[]})}}
    _,_,raw=data(m.GAUSSIAN,count=21)
    s=ow.create(store,{'model':m.GAUSSIAN,'csv_text':raw,'source_kind':'SYNTHETIC_TEACHING','source_name':'source'})
    store.owner.product_client=Client()
    s=act(store,s,'inverse_ai',text='M²=1，自由传播，束腰半径20到180微米。',approve_data=True)
    assert s['inverse_ai']['status']=='ACCEPTED' and s['inverse_settings']['fixed']['propagation']=='FREE_SPACE'
    assert s['inverse_settings']['bounds']['waist_radius_um']==[20,180]
    assert s['status']=='DRAFT' and not s.get('inverse_plan')

def test_declared_sd_weights_and_nonphysical_radius_rejected():
    group,cfg,_=data(m.GAUSSIAN,count=21)
    ds=group[0]['dataset'];ds['sd_um']=[.5]*21;ds['sha256']=digest({k:v for k,v in ds.items() if k!='sha256'})
    r=prof.run(m.plan(group,cfg));assert r['weighting']['scales'][0]['effective_source']=='CSV_DECLARED_MEASUREMENT_SD'
    ds['radius_um'][0]=-1;ds['sha256']=digest({k:v for k,v in ds.items() if k!='sha256'})
    with pytest.raises(ValueError):m.plan(group,cfg)

def test_equivalent_single_plane_gaussian_family():
    radius=float(gi.predict([0],80,40,633)[0])
    for w in (50.,80.,110.):
        zr=np.pi*(w*.001)**2/.000633;z0=zr*np.sqrt((radius/w)**2-1)
        assert float(gi.predict([0],w,z0,633)[0])==pytest.approx(radius)

def test_profile_rejects_reference_from_another_dataset():
    group,cfg,_=data(span=.6);reference=prof.run(m.plan(group,cfg))
    changed=copy.deepcopy(group);ds=changed[0]['dataset'];ds['intensity'][1]+=.01;ds['sha256']=digest({k:v for k,v in ds.items() if k!='sha256'})
    p=m.plan(changed,cfg,'profile',parameter='slit_width_um',grid_points=3,reference=reference)
    with pytest.raises(ValueError,match='数据或设置'):prof.run(p,reference=reference)

def test_profile_better_solution_blocks_stale_adoption_and_candidate_costs():
    group,cfg,_=data(span=.6);reference=prof.run(m.plan(group,cfg))
    reference['best_cost']+=1000
    p=m.plan(group,cfg,'profile',parameter='slit_width_um',grid_points=5,reference=reference)
    profile=prof.run(p,reference=reference)
    assert 'REFERENCE_OUTSIDE_PROFILE_SET' in profile['warnings']
    assert not ow.can_adopt({'inverse_result':reference,'inverse_profiles':{'slit_width_um':profile}})

@pytest.mark.parametrize('fixed_keys',[['amplitude'],['background'],['amplitude','background']])
def test_measurement_alignment_never_frees_known_brightness(fixed_keys):
    group,cfg,_=data(span=.6)
    for key in fixed_keys:
        cfg['fixed'][key]=1. if key=='amplitude' else .04;cfg['bounds'].pop(key)
    fit=prof.run(m.plan(group,cfg))
    profile=prof.run(m.plan(group,cfg,'profile',parameter='slit_width_um',reference=fit),reference=fit)
    constraints={'max_abs_x_mm':5,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}
    design=mp.propose(group,cfg,fit,{'slit_width_um':profile},constraints)
    assert design['alignment_roles']['amplitude_free']==('amplitude' not in fixed_keys)
    assert design['alignment_roles']['background_free']==('background' not in fixed_keys)
