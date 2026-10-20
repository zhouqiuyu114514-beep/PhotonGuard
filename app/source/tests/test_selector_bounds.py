from fractions import Fraction as F
from pathlib import Path
import pytest
from research.goal_certificate.selector_observable_bounds import sqrt_bounds,conditional_selector_bounds,conditional_projector_error
from research.goal_certificate.selector_contract import read_contract,assess_candidate_claim

@pytest.mark.parametrize('x',[F(0),F(1,3),F(2),F(9,16),F(1,10**40)])
def test_exact_square_root_enclosure(x):
    lo,hi=sqrt_bounds(x);assert lo*lo<=x<=hi*hi

def test_filter_margin_is_only_conditional_and_handles_exact_zero_error():
    a=conditional_selector_bounds([F(99,100)]*2,[F(98,100)]*2,[F(1,10**7)]*2,F(1,20),F(23,10))
    assert a['strict_filters_would_pass_if_inputs_certified'] and not a['unlocks_target_binding']
    b=conditional_selector_bounds([F(1)]*2,[F(1)]*2,[F(0)]*2,0,1)
    assert b['polarization_lower']==b['core_lower']==1 and b['outer_upper']==0

@pytest.mark.parametrize('error,gamma',[(-.1,2),(1,2),(.05,.9),(float('nan'),2)])
def test_invalid_error_does_not_produce_bounds(error,gamma):
    with pytest.raises(ValueError):conditional_selector_bounds([.99,.99],[.98,.98],[0.,.0001],error,gamma)

def test_cluster_projection_cannot_be_called_a_mode():
    with pytest.raises(ValueError,match='RANK_ONE'):conditional_projector_error(.001,.1,.5,projection_rank=2)
    with pytest.raises(ValueError,match='SEPARATION'):conditional_projector_error(.1,.1,.5,projection_rank=1)
    result=conditional_projector_error(F(1,1000),F(1,10),F(1,2),projection_rank=1)
    assert result['electric_relative_error_upper']<.021 and not result['original_target_rank_bound']

def test_global_mode_existence_does_not_bypass_four_candidate_scope(tmp_path):
    path=Path(__file__).resolve().parents[1]/'photonguard/adapters/mpb_worker.py';contract=read_contract(path)
    assert contract['searched_bands']==[1,2,3,4]
    for claim in ({'band':3,'certified':True},{'exists_above_2_09':True},{'parity':'minus'},{'verified':True}):assert not assess_candidate_claim(contract,claim)['claim_accepted']
    changed=tmp_path/'worker.py';changed.write_text(path.read_text().replace('num_bands=4','num_bands=5'))
    with pytest.raises(ValueError,match='SEARCH_RANGE_CHANGED'):read_contract(changed)
    changed.write_text(path.read_text().replace('>.45*sy','>.40*sy'))
    with pytest.raises(ValueError,match='MASK_OR_NORM_CHANGED'):read_contract(changed)
