"""Independent scalar consequences of independently assembled intervals.

The spectral cuts, common self-adjoint domain, and pump theorem are explicit
upstream assumptions. They are not re-proved by this integration check.
"""
from fractions import Fraction as F
from math import isqrt
from .dyadic import pi_bounds

def sqrt_bounds(value):
    value=F(value)
    if value<0:raise ValueError('NEGATIVE_SQUARE_ROOT')
    scale=1<<160;root=isqrt(value.numerator*scale*scale//value.denominator);lo=F(root,scale)
    return lo,lo if lo*lo==value else F(root+1,scale)

def need(condition,reason):
    if not condition:raise ValueError(reason)

def compare(a,b,label):
    x,y=map(F,a);u,v=map(F,b)
    need(x<=y and u<=v,'REVERSED_INTERVAL:'+label)
    need(max(x,u)<=min(y,v),'DISJOINT_INTEGRALS:'+label)

def propagate(endpoints,record):
    iv=[{k:tuple(map(F,v)) for k,v in e['integrals'].items()} for e in endpoints]
    for values in iv:
        need(all(a<=b for a,b in values.values()),'REVERSED_INTEGRALS')
        need(values['mass'][0]>0,'MASS')
    ss=[F(e['s_exact']) for e in endpoints];h=(ss[1]-ss[0])/2
    need(h==F(1,1000),'ROOT_ENDPOINT_ORDER_OR_WIDTH')
    ray=[(v['N'][0]/v['mass'][1],v['N'][1]/v['mass'][0]) for v in iv]
    residual=[v['residual2'][1]/v['mass'][0] for v in iv]
    lip=1/F(.775);a=F(1283,1000)+h*lip;b=F(1299,1000)-h*lip
    gap=min(min(x[0] for x in ray)-a,b-max(x[1] for x in ray),min(x[0] for x in ray))
    need(gap>0,'SPECTRAL_GAP');q=sqrt_bounds(max(residual))[1]/gap;need(q<F(139,1000),'PROJECTION_BUDGET')
    eta=sqrt_bounds(2-2*sqrt_bounds(1-q*q)[0])[1]
    eigen=[(r[0]-e/(b-r[1]),r[1]+e/(r[0]-a)) for r,e in zip(ray,residual)]
    need(eigen[0][1]<1/F(.775)<eigen[1][0],'ROOT_CROSSING')
    derivative=(ray[1][0]-ray[0][1])/(2*h)-2*lip*eta;need(derivative>0,'HF_MONOTONICITY')
    v=iv[0];electric=sqrt_bounds(v['electric'][0]/v['mass'][1])[0];need(electric>=F(7,10),'ELECTRIC_NORMALIZATION')
    error=eta/electric
    def cone(p,z):
        need(0<=p<=1 and 0<=z<1,'CONE_DOMAIN')
        value=sqrt_bounds(p)[0]*sqrt_bounds(1-z*z)[0]-sqrt_bounds(1-p)[1]*z
        return max(F(0),value)**2
    gamma=sqrt_bounds(v['electric'][1]/v['electric_L2'][0])[1]
    ex=cone(v['Ex'][0]/v['electric_L2'][1],gamma*error)
    core=cone(v['core'][0]/v['electric'][1],error)
    outer=max(F(0),v['outer'][1]/v['electric'][0])
    out=(sqrt_bounds(outer)[1]*sqrt_bounds(1-error*error)[1]+sqrt_bounds(1-outer)[1]*error)**2
    need(ex>F(.55) and core>F(.35) and out<F(.05),'CONTINUOUS_SELECTOR')
    def minabs(pair):
        lo,hi=map(F,pair);need(lo<=hi,'REVERSED_CROSS')
        return F(0) if lo<=0<=hi else min(abs(lo),abs(hi))
    cross=record['cross_record_trial'];mlo,mhi=map(F,record['record_mass']);need(mlo>0,'RECORD_NORM')
    overlap=sqrt_bounds(minabs(cross['real'])**2+minabs(cross['imag'])**2)[0]/sqrt_bounds(mhi*v['mass'][1])[1]
    need(0<=overlap<=1,'OVERLAP');distance=sqrt_bounds(2-2*overlap)[1]+eta
    projection=max(F(0),1-distance*distance/2)**2
    need(distance<F(1,4) and projection>F(1,2),'DOMINANT_RECORD_PROJECTION')
    pi_lo,_=pi_bounds();mismatch=pi_lo*(4*(ss[0]-F(41,20))/F(1.55)-F(1,10))
    need(mismatch>0,'PHASE_MISMATCH');f_upper=4/(F(1000)**2*mismatch*mismatch);need(f_upper<F(.8),'GOAL_EXCLUSION')
    return {'status':'INDEPENDENT_INTEGRALS_AND_PROPAGATION_PASS','q_upper':float(q),'q_upper_exact':str(q),
        'root_exists_and_unique':True,'HF_derivative_lower':float(derivative),'selector_bounds':[float(ex),float(core),float(out)],
        'record_distance_upper':float(distance),'target_projection_lower':float(projection),'phase_factor_upper':float(f_upper),
        'phase_factor_upper_exact':str(f_upper),'research_goal_decision':'EXCLUDED_FOR_THIS_FROZEN_MODEL',
        'upstream_assumptions':['Source-bound lower/upper spectral counts at 1.283 and 1.299','Common periodic self-adjoint domain and parameter Lipschitz theorem','Original pump theorem n<41/20'],
        'new_geometry_or_physical_device_certified':False}
