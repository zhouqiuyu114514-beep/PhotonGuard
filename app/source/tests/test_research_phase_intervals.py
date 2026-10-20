"""Analytic scalar bounds and trust-boundary regressions; no solver/API calls."""
from fractions import Fraction
import math
import pytest
from photonguard.research_phase_bounds import (
    assess_phase_interval, assess_neff_goal_envelope, assess_goal_envelope, pi_bounds)


def test_review_counterexample_is_uncertain_for_the_whole_interval():
    point=assess_phase_interval([1.6,1.6],.8,{})
    interval=assess_phase_interval([1.5,1.7],.8,{})
    assert point['conditional_goal_decision']=='MET'
    assert interval['conditional_goal_decision']=='INCONCLUSIVE'
    lo,hi=interval['conditional_phase_factor_interval']
    assert lo<.781207263<.8<.804062127<hi


@pytest.mark.parametrize('interval,decision',[([0,0],'MET'),([-.1,.1],'MET'),([1.7,1.8],'EXCLUDED'),([100,110],'EXCLUDED'),([-110,-100],'EXCLUDED'),([-100,100],'INCONCLUSIVE')])
def test_whole_interval_and_global_envelope(interval,decision):
    a=assess_phase_interval(interval,.8,{'certified':True,'hash':'f'*64})
    assert a['conditional_goal_decision']==decision
    assert a['design_goal_status']=='NOT_EVALUATED'
    assert not a['continuous_truth_interval_certified']


def test_pi_is_enclosed_by_independent_known_decimal_bracket():
    lo,hi=pi_bounds()
    decimal=Fraction('3.14159265358979323846264338327950288419716939937510')
    assert decimal<lo<hi<decimal+Fraction(1,10**50)
    assert hi-lo<Fraction(1,10**100)


def test_hypothetical_wide_bounds_are_sufficient_but_not_certified():
    a=assess_neff_goal_envelope([1.,1.98],[2.03,2.3],1.55,20.,1000.,.8,{'certified':True})
    assert a['conditional_phase_factor_upper']<.000481
    assert a['conditional_exclusion_if_interval_were_certified']
    assert not a['continuous_truth_interval_certified']


def test_exact_envelope_is_outward_even_after_nontrivial_divisions():
    a=assess_goal_envelope([1.23456789,1.3],{},1234.56789,.8)
    exact=4/(Fraction(1.23456789)**2*Fraction(1234.56789)**2)
    assert Fraction(a['conditional_phase_factor_upper'])>=exact
    assert Fraction(math.nextafter(a['conditional_phase_factor_upper'],-math.inf))<exact


@pytest.mark.parametrize('value',[[float('nan'),2],[2,1],[True,2],['1','2']])
def test_non_numeric_or_reversed_interval_rejected(value):
    with pytest.raises(ValueError):assess_phase_interval(value,.8,{})
