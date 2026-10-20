import copy
import numpy as np
import pytest
from test_inverse_journeys import data,store,act,planned,wait
from photonguard.experiments import inverse_models as m,inverse_profiles as engine,goal_design as gd,observation_group as ow,teaching_acquisition as ta
from photonguard.experiments.inverse_report import grounded

C={'max_abs_x_mm':5.,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}

def test_local_information_gain_and_fixed_nuisance():
    groups,cfg,_=data(span=.6);fit=engine.run(m.plan(groups,cfg));before=gd.information(groups,cfg,fit['estimated_parameters'])
    after=gd.information(groups,cfg,fit['estimated_parameters'],np.linspace(-3,3,81))
    assert all(after['scales'][k]<=before['scales'][k] for k in after['scales'])
    cfg['fixed']['amplitude']=1.;cfg['bounds'].pop('amplitude');cfg['fixed']['background']=.04;cfg['bounds'].pop('background')
    fixed=gd.information(groups,cfg,fit['estimated_parameters'],np.linspace(-3,3,81))
    assert fixed['scales']['slit_width_um']<=after['scales']['slit_width_um']

def test_goal_switch_nonuniform_and_no_truth():
    groups,cfg,_=data(span=.6);fit=engine.run(m.plan(groups,cfg));profile=engine.run(m.plan(groups,cfg,'profile',parameter='slit_width_um',reference=fit),reference=fit)
    proposals=[gd.propose(groups,cfg,fit,{'width':profile},C,{'target':g,'source':'USER_FORM'}) for g in ['width','separation','balanced']]
    assert all(len(p['plans'])==6 and p['resources']['model_calls']==0 for p in proposals)
    assert all(len(p['prediction_x_mm'])==81 and np.min(np.diff(p['prediction_x_mm']))>=.001 for p in proposals[0]['plans'])
    assert len({p['recommended_id'] for p in proposals})>=2
    assert all(p['schema'].endswith('v2') for p in proposals)
    assert 'SYNTHETIC_TEACHING' not in str(proposals[0]['candidate_parameters'])

def test_single_physical_candidate_is_local_not_fake_plurality():
    groups,cfg,_=data();fit=engine.run(m.plan(groups,cfg));fit['starts']=[]
    proposal=gd.propose(groups,cfg,fit,{},C)
    assert proposal['recommendation_kind']=='LOCAL_ONLY' and proposal['resources']['candidate_count']==1
    assert proposal['research_goal']['source']=='DEFAULT_BALANCED'
    a=copy.deepcopy(fit['estimated_parameters']);b=copy.deepcopy(a);b['amplitude@0']+=.1
    profile={'id':'nuisance','best_cost':fit['best_cost'],'warnings':[],'rows':[{'accepted':True,'cost':fit['best_cost'],'parameters':p} for p in [a,b]]}
    chosen,status=gd.candidates(groups,cfg,fit,{'x':profile});assert len(chosen)==1

def test_gaussian_five_locations_append_frozen_and_recovery(store):
    s=ow.create(store,{'model':m.GAUSSIAN,'teaching':True});s=wait(store,act(store,planned(store,s),'inverse_run',approve=True,plan_sha256=store.get(s['id'])['inverse_plan']['sha256']))
    assert s['status']=='COMPLETED'
    s=act(store,s,'inverse_measurement_plan',constraints={**C,'max_abs_x_mm':200.,'points':5,'min_step_mm':1.},research_goal={'target':'waist_position','source':'USER_FORM'})
    p=s['measurement_plan'];chosen=next(x for x in p['plans'] if x['id']==p['recommended_id'])
    child=act(store,s,'inverse_append',approve=True,teaching=True,proposal_id=chosen['id'],proposal_sha256=p['sha256'])
    assert child['groups'][-1]['dataset']['rows']==5 and not child['groups'][-1]['approved']
    assert np.allclose(child['groups'][-1]['dataset']['x_mm'],chosen['prediction_x_mm'])
    child=planned(store,child);child=wait(store,act(store,child,'inverse_run',approve=True,plan_sha256=child['inverse_plan']['sha256']))
    assert len(child['inverse_result']['data'])==2 and child['acquisition_expectation']['proposal_sha256']==p['sha256']
    assert store.get(s['inverse_root'])['inverse_ledger']['fit_runs_reserved']==2
    ow.verify(store,child)

def test_gaussian_position_derivative_vanishes_at_waist():
    groups,cfg,_=data(m.GAUSSIAN);fit=engine.run(m.plan(groups,cfg));p={**cfg['fixed'],'waist_radius_um':80.,'waist_z_mm':40.}
    derivative=(m.predict([40.],{**p,'waist_z_mm':40.001},m.GAUSSIAN)-m.predict([40.],{**p,'waist_z_mm':39.999},m.GAUSSIAN))/.002
    assert abs(derivative[0])<1e-10

def test_refinement_canonical_bounded_and_tamper():
    from photonguard.core import digest
    groups,cfg,_=data();fit=engine.run(m.plan(groups,cfg));p=m.plan(groups,cfg,'profile',parameter='slit_width_um',reference=fit,refinement=True)
    m.verify_plan(p);assert len(p['profile']['grid'])<=10 and p['budget']['max_residual_calls']==30000
    p['profile']['grid'][0]-=.1;p['sha256']=digest({k:v for k,v in p.items() if k!='sha256'})
    with pytest.raises(ValueError):m.verify_plan(p)

def test_goal_grounding_rejects_negation_and_wrong_number():
    grounded('goal.target','width','优先缝宽','优先缝宽')
    grounded('design.points',5,'新增5个位置','新增5个位置')
    with pytest.raises(ValueError):grounded('goal.target','width','优先缝宽','不要优先缝宽')
    with pytest.raises(ValueError):grounded('design.points',50,'新增5个位置','新增5个位置')

def test_independent_center_and_invalid_constraints():
    groups,cfg,_=data();fit=engine.run(m.plan(groups,cfg))
    with pytest.raises(ValueError):gd.propose(groups,cfg,fit,{},dict(C,registration_uncertainty_mm=.1))
    with pytest.raises(ValueError):gd.propose(groups,cfg,fit,{},C,{'target':'waist_radius','source':'USER_FORM'})
    with pytest.raises(ValueError):gd.propose(groups,cfg,fit,{},C,{'target':'prediction','source':'USER_FORM'})

def test_refinement_consumed_once_across_versions(store):
    from photonguard.workflow import WorkflowError
    groups,cfg,raw=data(span=5)
    s=ow.create(store,{'model':m.SLIT,'csv_text':raw,'source_name':'fixed fixture','source_kind':'SYNTHETIC_TEACHING'})
    s['inverse_settings']=cfg;store.save(s);s=planned(store,s);s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    s=act(store,s,'inverse_profile_plan',parameter='slit_width_um',grid_points=3);s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    refined=act(store,s,'inverse_profile_plan',parameter='slit_width_um',refinement=True);refined=wait(store,act(store,refined,'inverse_run',approve=True,plan_sha256=refined['inverse_plan']['sha256']))
    assert refined['status']=='COMPLETED';ledger=store.get(refined['inverse_root'])['inverse_ledger']
    assert ledger['refinements_reserved']==1 and ledger['profile_runs_reserved']==2 and ledger['residual_calls_reserved']==90000
    with pytest.raises(WorkflowError):act(store,refined,'inverse_profile_plan',parameter='slit_width_um',refinement=True)

def test_goal_switch_invalidates_old_proposal_and_retains_evidence(store,monkeypatch):
    import json
    from photonguard.experiments.inverse_report import legacy_guidance as guidance
    s=ow.create(store,{'model':m.SLIT,'teaching':True});s=planned(store,s);s=wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))
    s=act(store,s,'inverse_measurement_plan',constraints=C);old=s['measurement_plan']['sha256'];fixed=copy.deepcopy(s['inverse_settings'])
    class Client:
        def complete(self,*args):return {'assistant':{'content':json.dumps({'updates':[{'field':'goal.target','value':'width','quote':'优先缝宽','correction':False}],'focus':'measurement'})}}
    monkeypatch.setattr(store,'_model',lambda *args:Client())
    s=guidance(store,s,{'text':'优先缝宽','approve_data':True})
    assert not s.get('measurement_plan') and s['measurement_history'][0]['sha256']==old and s['inverse_settings']==fixed
    ow.verify(store,s)
