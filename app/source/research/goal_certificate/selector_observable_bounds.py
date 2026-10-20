"""Exact conditional propagation of electric-field error into selection tests.

These are implications, never certificates for supplied field/error estimates.
No Boolean or hash from the caller certifies a continuous field or projector.
"""
from fractions import Fraction as F
from math import isqrt,nextafter,inf

def fraction(x):
    if isinstance(x,bool):raise ValueError('BOOLEAN_IS_NOT_BOUND')
    try:return F(x)
    except (ValueError,TypeError,OverflowError) as e:raise ValueError('FINITE_RATIONAL_REQUIRED') from e

def sqrt_bounds(x):
    x=fraction(x)
    if x<0:raise ValueError('NEGATIVE_SQUARE_ROOT')
    scale=2**160;n=isqrt(x.numerator*scale*scale//x.denominator);lo=F(n,scale)
    return lo,lo if lo*lo==x else F(n+1,scale)

def outward(x,upper):
    value=float(x)
    if upper and F(value)<x:return nextafter(value,inf)
    if not upper and F(value)>x:return nextafter(value,-inf)
    return value

def fraction_interval(value):
    lo,hi=map(fraction,value)
    if not 0<=lo<=hi<=1:raise ValueError('OBSERVABLE_OUTSIDE_UNIT_INTERVAL')
    return lo,hi

def conditional_selector_bounds(p0,core0,outer0,relative_error_upper,gamma_upper):
    p,core,outer=map(fraction_interval,(p0,core0,outer0));e=fraction(relative_error_upper);gamma=fraction(gamma_upper)
    if not 0<=e<1 or gamma<1:raise ValueError('ERROR_OR_NORM_CONVERSION_DOMAIN')
    pe=gamma*e
    pl=(max(F(0),sqrt_bounds(p[0])[0]-pe)/(1+pe))**2
    cl=(max(F(0),sqrt_bounds(core[0])[0]-e)/(1+e))**2
    oh=((sqrt_bounds(outer[1])[1]+e)/(1-e))**2
    return {'status':'CONDITIONAL_SELECTOR_BOUNDS_ONLY','polarization_lower':outward(pl,False),'core_lower':outward(cl,False),'outer_upper':outward(oh,True),
        'exact_bounds':[str(pl),str(cl),str(oh)],'assumed_error_upper_exact':str(e),'assumed_gamma_upper_exact':str(gamma),
        'strict_filters_would_pass_if_inputs_certified':pl>F(.55) and cl>F(.35) and oh<F(.05),
        'continuous_field_or_error_certified':False,'candidate_membership_certified':False,'unlocks_target_binding':False}

def conditional_projector_error(residual_upper,gap_lower,electric_norm_lower,*,projection_rank):
    r,g,a=map(fraction,(residual_upper,gap_lower,electric_norm_lower))
    if projection_rank!=1:raise ValueError('RANK_ONE_PROJECTION_REQUIRED')
    if r<0 or g<=0 or a<=0 or r>=g:raise ValueError('POSITIVE_SEPARATION_AND_Q_LT_ONE_REQUIRED')
    q=r/g;rootlo=sqrt_bounds(1-q*q)[0];eta=sqrt_bounds(2-2*rootlo)[1];e=eta/a
    return {'status':'CONDITIONAL_PROJECTOR_BOUND_ONLY','combined_norm_error_upper':outward(eta,True),'electric_relative_error_upper':outward(e,True),
        'electric_relative_error_upper_exact':str(e),'assumes_trial_combined_norm_is_one':True,'assumes_simple_isolated_eigenvalue':True,
        'gap_or_residual_certified':False,'original_target_rank_bound':False}
