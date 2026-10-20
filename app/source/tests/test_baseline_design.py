import copy
import pytest
from test_inverse_journeys import data
from photonguard.experiments import baseline_design as b,inverse_models as m,inverse_profiles as e

C={'max_abs_x_mm':5.,'points':81,'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}

def test_baseline_valid_and_default_policy_is_not_claimed_optimal():
    groups,cfg,_=data(span=.6);fit=e.run(m.plan(groups,cfg));p=b.propose(groups,cfg,fit,{},C)
    assert p['baseline_id']=='baseline' and p['recommended_id']=='baseline' and p['recommendation_kind']=='BASELINE_CONSERVATIVE'
    assert len(p['stability'])==3 and p['decision_policy']['minimum_relative_gain']==.2
    assert len(p['plans'])==7 and p['baseline_catalog'][0]['source']=='RC5_RC6_DECLARED_TEACHING_REFERENCE'
    assert all('sampling_risk' in plan for plan in p['plans'])

def test_unavailable_baseline_is_explained_without_widening_constraints():
    groups,cfg,_=data(span=.6);fit=e.run(m.plan(groups,cfg));c={**C,'max_abs_x_mm':1.}
    p=b.propose(groups,cfg,fit,{},c)
    assert p['baseline_id'] is None and p['baseline_catalog'][0]['reasons']==['超出允许范围']
    assert all(max(map(abs,v['prediction_x_mm']))<=1 for v in p['plans'])

def test_user_baseline_and_explicit_exploration():
    import numpy as np
    groups,cfg,_=data(span=.6);fit=e.run(m.plan(groups,cfg))
    p=b.propose(groups,cfg,fit,{},C,baseline={'source':'USER_SPECIFIED','positions_mm':np.linspace(-1,1,81).tolist(),'label':'My instrument recipe'},policy='local_exploration')
    assert p['baseline_catalog'][0]['source']=='USER_SPECIFIED' and p['recommended_id']==p['local_recommended_id']
    with pytest.raises(ValueError):b.propose(groups,cfg,fit,{},C,baseline={'source':'USER_SPECIFIED','positions_mm':[],'label':'','invented':True})

def test_stability_does_not_change_recorded_facts_or_fixed_amplitude():
    groups,cfg,_=data(span=.6);cfg['fixed']['amplitude']=1.;cfg['bounds'].pop('amplitude');saved=copy.deepcopy((groups,cfg));fit=e.run(m.plan(groups,cfg));b.propose(groups,cfg,fit,{},C)
    assert (groups,cfg)==saved
