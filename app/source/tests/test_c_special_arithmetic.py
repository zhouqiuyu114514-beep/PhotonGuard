from fractions import Fraction as F
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from research.goal_certificate.selector_cone_bounds import (
    conditional_cone_bounds, distance_down, distance_up, lower_ratio, upper_ratio)
from research.goal_certificate.projector_budget import bound
from research.goal_certificate.fixed_s_rank_one import complementary_gap, witness


def arguments():
    return dict(p=[F(99,100)]*2,core=[F(99,100)]*2,outer=[F(1,10000000)]*2,
                error=F(1,5),gamma=F(22,10),
                epsilon_regions=[[[1,0,0],[0,1,0],[0,0,1]],[[5,0,0],[0,5,0],[0,0,5]]],
                mean_epsilon=[F(47,10)]*2)


def test_conditional_and_budget():
    result=conditional_cone_bounds(**arguments())
    assert result['strict_filters_would_pass_if_inputs_certified']
    assert not result['continuous_field_or_error_certified']
    assert bound()['strictly_below_one_fifth']
    assert bound(F(2,15))['electric_error_upper'] < .191
    assert complementary_gap(F(1283,1000))==F(3,500)


@pytest.mark.parametrize('name,value', [('p',[F(.55)]*2),('core',[F(.35)]*2),('outer',[F(.05)]*2),('p',[0,1])])
def test_equal_threshold_or_wide_interval_fails(name,value):
    a=arguments();a[name]=value;a['error']=0
    assert not conditional_cone_bounds(**a)['strict_filters_would_pass_if_inputs_certified']


def test_nearest_point_equality_and_strict_counterexample():
    # v=(4/5,3/5), cone direction d=(3/5,4/5), w=<v,d>d.
    # w lies exactly on p=9/25 and distance ||v-w||=7/25.
    v=(F(4,5),F(3,5));d=(F(3,5),F(4,5));dot=sum(a*b for a,b in zip(v,d));w=[dot*a for a in d]
    assert sum((a-b)**2 for a,b in zip(v,w))==F(7,25)**2
    assert w[0]**2/sum(a*a for a in w)==F(9,25)
    assert distance_down(F(16,25),F(9,25))<=F(7,25)
    assert distance_up(F(9,25),F(16,25))<=F(7,25)
    assert lower_ratio(F(16,25),F(7,25))<=F(9,25)


def test_saturation():
    assert lower_ratio(F(1,4),F(3,4))==0
    assert upper_ratio(F(3,4),F(3,4))==1
    a=arguments();a['error']=F(9,10)
    assert conditional_cone_bounds(**a)['polarization_lower']==0


@pytest.mark.parametrize('kind', ['nondiagonal','negative','gamma','zero_norm','bad_gap','boolean','rank'])
def test_invalid_inputs(kind):
    a=arguments()
    with pytest.raises(ValueError):
        if kind=='nondiagonal':a['epsilon_regions'][0][0][1]=F(1,100)
        elif kind=='negative':a['epsilon_regions'][0][0][0]=-1
        elif kind=='gamma':a['gamma']=2
        elif kind=='boolean':a['error']=True
        elif kind=='zero_norm':bound(electric_norm_lower=0)
        elif kind=='bad_gap':complementary_gap(F(1277,1000))
        elif kind=='rank':bound(projection_rank=True)
        conditional_cone_bounds(**a)


def test_optimized_interpreter_keeps_rejection():
    code='from research.goal_certificate.projector_budget import bound\ntry:\n bound(electric_norm_lower=0)\nexcept ValueError:\n print("REJECTED")\nelse:\n raise SystemExit(3)'
    result=subprocess.run([sys.executable,'-O','-B','-c',code],capture_output=True,text=True,timeout=15)
    # The package rejects optimized interpreters before importing a checker.
    assert result.returncode!=0 and 'OPTIMIZATION_UNSUPPORTED' in result.stderr


def test_bad_forms_not_accepted():
    matrices={k:{part:[[[0]*3 for _ in range(3)]]*2 for part in ('real','imag')} for k in ('mass','N','continuous_graph')}
    with pytest.raises(ValueError,match='INSUFFICIENT'):witness(matrices,F(1277,1000),[1,2])
