import copy
import pytest
from photonguard.experiments.decision_preferences import decide,preferences,apply
from photonguard.experiments import inverse_models as m


def fixture():
    prefs=preferences({'model':m.SLIT},{'mode':'CONDITIONAL_EXPLORATION','target_scales':{'slit_width_um':1.,'slit_separation_um':1.},'protected_scale_increase':{'slit_separation_um':.1}})
    def plan(id,a,d,travel=4):return {'id':id,'cost':{'points':71,'travel_mm':travel,'uniform_segments':1},'scenario_ids':['h1','h2'],
        'scales_by_scenario':[{'slit_width_um':x,'slit_separation_um':y} for x,y in zip(a,d)]}
    return prefs,[plan('baseline',[2,3],[1,1]),plan('good',[1,2],[1.05,1.08]),plan('harm',[.5,1],[1.3,1.2])]


def test_paired_protection_and_hand_calculated_net_gain():
    p,plans=fixture();d=decide(plans,'baseline',p,['slit_width_um'])
    assert d['selected']=='good';assert d['audit'][0]['worst_paired_proxy_gain']==1
    assert d['audit'][0]['worst_scale_increase']['slit_separation_um']==pytest.approx(.08)
    assert 'PROTECTED_PARAMETER_PROXY' in d['audit'][1]['reasons']


def test_unit_rescaling_preserves_choice_and_gain():
    p,plans=fixture();expected=decide(plans,'baseline',p,['slit_width_um'])
    for k in p['target_scales']:p['target_scales'][k]*=1000
    for k in p['protected_scale_increase']:p['protected_scale_increase'][k]*=1000
    for q in plans:
        for row in q['scales_by_scenario']:
            for k in row:row[k]*=1000
    result=decide(plans,'baseline',p,['slit_width_um'])
    assert result['selected']==expected['selected']
    assert result['audit'][0]['net_proxy_gain']==expected['audit'][0]['net_proxy_gain']


def test_hard_cost_missing_data_and_missing_baseline():
    p,plans=fixture();p['max_travel_mm']=3
    assert decide(plans,'baseline',p,['slit_width_um'])['selected'] is None
    p['max_travel_mm']=None;plans[1]['scales_by_scenario'][0]['slit_width_um']=None
    assert decide(plans,'baseline',p,['slit_width_um'])['selected']=='baseline'
    assert decide(plans,None,p,['slit_width_um'])['status']=='NO_COMPARABLE_BASELINE'
    plans[0]['scales_by_scenario'][0]['slit_width_um']=None
    assert decide(plans,'baseline',p,['slit_width_um'])['status']=='BASELINE_PROXY_UNAVAILABLE'


def test_baseline_first_strict_gain_threshold_and_scenario_pairing():
    p,plans=fixture();p['mode']='BASELINE_FIRST'
    assert decide(plans,'baseline',p,['slit_width_um'])['selected']=='baseline'
    p['mode']='CONDITIONAL_EXPLORATION';p['minimum_proxy_gain']=1
    assert decide(plans,'baseline',p,['slit_width_um'])['selected']=='baseline'
    plans[1]['scenario_ids'].reverse()
    with pytest.raises(ValueError):decide(plans,'baseline',p,['slit_width_um'])


def test_candidates_need_not_have_same_winner_across_scenarios():
    p,plans=fixture();plans[2]['scales_by_scenario']=[{'slit_width_um':.5,'slit_separation_um':1},{'slit_width_um':2.5,'slit_separation_um':1}]
    assert decide(plans,'baseline',p,['slit_width_um'])['selected']=='good'


def test_cost_penalty_and_unknown_normalization_are_not_ignored():
    p,plans=fixture();plans[1]['cost']['travel_mm']=6;p['extra_travel_penalty_per_mm']=.6
    assert decide(plans,'baseline',p,['slit_width_um'])['selected']=='baseline'
    p['target_scales']={}
    assert decide(plans,'baseline',p,['slit_width_um'])['status']=='UNDEFINED_NORMALIZATION'


def test_candidate_identity_prevents_false_gain_from_independent_worst_cases():
    p,plans=fixture();plans=plans[:2];p['protected_scale_increase']={}
    plans[0]['scales_by_scenario']=[{'slit_width_um':10.},{'slit_width_um':1.}]
    plans[1]['scales_by_scenario']=[{'slit_width_um':8.},{'slit_width_um':2.}]
    # Difference of separate maxima would falsely report a gain of 2;
    # the same candidate pair correctly exposes degradation of 1.
    out=decide(plans,'baseline',p,['slit_width_um'])
    assert out['selected']=='baseline' and out['audit'][0]['worst_paired_proxy_gain']==-1.


def test_real_gaussian_plan_retains_every_parameter_and_assumption():
    from test_inverse_journeys import data
    from photonguard.experiments import inverse_profiles as ip,baseline_design as bd
    groups,cfg,_=data(m.GAUSSIAN);fit=ip.run(m.plan(groups,cfg))
    constraints={'points':5,'max_abs_x_mm':200,'min_step_mm':1,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0}
    result=bd.propose(groups,cfg,fit,{},constraints,{'target':'waist_position','source':'USER_FORM'})
    before=copy.deepcopy(groups);out=apply(result,groups,cfg,{'mode':'CONDITIONAL_EXPLORATION','max_travel_mm':250})
    assert out['schema']=='photonguard.measurement-plan.v4'
    assert all(len(p['tradeoff_scales']['scales_by_scenario'])==3*len(out['candidate_parameters']) for p in out['plans'])
    assert all({'waist_radius_um','waist_z_mm','prediction'}==set(p['tradeoff_scales']['scales_by_scenario'][0]) for p in out['plans'])
    assert any(p['execution_allowed'] is False for p in out['plans']) and groups==before
