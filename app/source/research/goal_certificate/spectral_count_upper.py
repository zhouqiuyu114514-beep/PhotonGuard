"""Infinite-tail lower form and rank-correction upper spectral count.

The scalar rectangle integration and final dense products are outward intervals.
Floating inverses/eigenvectors are proposals only. See UPPER_COUNT_PROOF_ZH.md.
"""
from fractions import Fraction as F
from functools import lru_cache
from math import factorial
import hashlib,json
import numpy as np
import scipy.linalg as la
from .interval_arithmetic import R,C,rational,up,down
from .upper_dense import matmul,transpose,midpoint,positive_definite,validate
from .pump_slab_envelope import applicable,pi_interval

def require(ok,msg):
    if not ok:raise ValueError(msg)

@lru_cache(None)
def trig(turns):
    turns=F(turns);turns=(turns+F(1,2))%1-F(1,2)
    if turns==0:return R(0),R(1)
    pl,ph=pi_interval();pi=R(float(rational(pl).lo),float(rational(ph).hi));x=2*pi*rational(turns);z=x*x
    sin=R(0);cos=R(0)
    for j in reversed(range(25)):
        sin=sin*z+rational(F((-1)**j,factorial(2*j+1)))
        cos=cos*z+rational(F((-1)**j,factorial(2*j)))
    sin=x*sin;se=float(rational(ph**51/F(factorial(51))).hi);ce=float(rational(ph**50/F(factorial(50))).hi)
    return sin+R(-se,se),cos+R(-ce,ce)

@lru_cache(None)
def rect(n,lo,hi):
    n=int(n);lo,hi=F(lo),F(hi)
    require(F(-2)<=lo<hi<=2,'RECTANGLE_RANGE')
    if n==0:return C(rational((hi-lo)/4))
    if n<0:return rect(-n,lo,hi).conj()
    sb,cb=trig(n*hi/4);sa,ca=trig(n*lo/4)
    pl,ph=pi_interval();den=2*n*R(float(rational(pl).lo),float(rational(ph).hi))
    return C((sb-sa)/den,(cb-ca)/den)

def table_rect(delta,lo,hi):
    entries={int(n):rect(int(n),F(lo),F(hi)) for n in np.unique(delta)}
    return C(R(np.vectorize(lambda n:float(entries[int(n)].re.lo))(delta),np.vectorize(lambda n:float(entries[int(n)].re.hi))(delta)),
             R(np.vectorize(lambda n:float(entries[int(n)].im.lo))(delta),np.vectorize(lambda n:float(entries[int(n)].im.hi))(delta)))

def material_profile(model,calibration=None):
    applicable(model);m=model['materials']['0.775'];a=np.asarray(m['laboratory_epsilon'])
    require(m['wavelength_um']==.775 and a.shape==(3,3) and np.isfinite(a).all() and np.array_equal(a,np.diag(np.diag(a))) and np.all(np.diag(a)>0),'SH_DIAGONAL_MATERIAL')
    if calibration=='uniform-isotropic':return [F(5)]*3,F(5),F(5)
    if calibration=='uniform-anisotropic':return list(map(F,(4,4.5,5))),None,None
    if calibration=='periodic-slab':return [F(4)]*3,F(1),F(1)
    require(calibration is None,'UNKNOWN_CALIBRATION')
    return list(map(F,np.diag(a))),F(model['top_epsilon']),F(model['bottom_epsilon'])

def tail_coercivity(model,M,s,f_cut,calibration=None):
    require(type(M) is int and 0<=M<=12,'FOURIER_CAP');s,f_cut=F(s),F(f_cut)
    require(s>0 and f_cut>0,'POSITIVE_SHIFT')
    ln,top,bottom=material_profile(model,calibration);eps=max(ln+[top or F(0),bottom or F(0)])
    k=s/F(model['materials']['0.775']['wavelength_um']);tail=k*k+F(M+1,4)**2;c=f_cut*f_cut/tail;margin=1/eps-c
    require(margin>0,'TAIL_NOT_COERCIVE')
    return k,tail,c,margin

def material_fourier_intervals(model,M,s,f_cut,calibration=None):
    k,tail,c,margin=tail_coercivity(model,M,s,f_cut,calibration)
    g=np.arange(-M,M+1);mx,my=np.meshgrid(g,g,indexing='ij');mx=mx.ravel();my=my.ravel()
    dx=mx[:,None]-mx[None,:];dy=my[:,None]-my[None,:];eye=C.point(((dx==0)&(dy==0)).astype(float));zx=C.point((dx==0).astype(float))
    ln,air,bottom=material_profile(model,calibration)
    req=model['task']['requirements'];a=F(req['film_thickness_um'])/2;b=-a+F(req['slab_thickness_um']);w=F(req['ridge_width_um'])/2
    if calibration=='periodic-slab':shape=zx*table_rect(dy,F(-1,2),F(1,2));bottom_shape=C.point(np.zeros(dx.shape))
    else:
        shape=zx*table_rect(dy,-a,b)+table_rect(dx,-w,w)*table_rect(dy,b,a)
        bottom_shape=zx*table_rect(dy,F(-2),-a)
    mats=[]
    for eps in ln:
        fn=lambda v:v/(1-c*v)
        if calibration and calibration.startswith('uniform'):matrix=eye*rational(fn(eps))
        else:matrix=eye*rational(fn(air))+bottom_shape*rational(fn(bottom)-fn(air))+shape*rational(fn(eps)-fn(air))
        validate(matrix);mats.append(matrix)
    return mats,mx,my,k,tail,c,margin

def transverse_basis_exact(mx,my,k,f_cut,tail):
    n=len(mx);jl=[np.zeros((n,2*n)) for _ in range(3)];jh=[a.copy() for a in jl]
    wl=np.zeros((2*n,2*n));wh=wl.copy()
    for i,(x,y) in enumerate(zip(mx,my)):
        ax=-F(int(x),4)/k;ay=-F(int(y),4)/k
        jl[0][i,i]=jh[0][i,i]=jl[1][i,n+i]=jh[1][i,n+i]=1
        for j,v in ((i,ax),(n+i,ay)):
            q=rational(v);jl[2][i,j]=q.lo;jh[2][i,j]=q.hi
        weight=F(f_cut)**2*(1/(k*k+F(int(x),4)**2+F(int(y),4)**2)-1/tail)
        for row,col,v in ((i,i,1+ax*ax),(n+i,n+i,1+ay*ay),(i,n+i,ax*ay),(n+i,i,ax*ay)):
            q=rational(weight*v);wl[row,col]=q.lo;wh[row,col]=q.hi
    return [C(R(l,h)) for l,h in zip(jl,jh)],C(R(wl,wh))

def propose_inverse_action(K,J):
    proposals=[]
    for a,b in zip(K,J):
        km=midpoint(a);z=la.solve((km+km.conj().T)/2,midpoint(b),assume_a='her',check_finite=True)
        require(np.isfinite(z).all(),'NONFINITE_PROPOSAL');proposals.append(z)
    return proposals

def saved_interval(target,prefix,value):
    target[prefix+'_re_lo']=value.re.lo;target[prefix+'_re_hi']=value.re.hi
    target[prefix+'_im_lo']=value.im.lo;target[prefix+'_im_hi']=value.im.hi

def verify_upper_count(model,M,s,f_cut,maximum_count,*,calibration=None):
    require(type(maximum_count) is int and maximum_count>=0,'COUNT_CAP')
    K,mx,my,k,tail,c,margin=material_fourier_intervals(model,M,s,f_cut,calibration)
    J,weight=transverse_basis_exact(mx,my,k,f_cut,tail);Z=propose_inverse_action(K,J)
    lower=-weight;artifacts={}
    for i,(a,j,z) in enumerate(zip(K,J,Z)):
        zi=C.point(z);lower=lower+matmul(transpose(j),zi)+matmul(transpose(zi),j)-matmul(transpose(zi),matmul(a,zi))
        artifacts['Z_'+str(i)]=z;saved_interval(artifacts,'K_'+str(i),a)
    lm=midpoint(lower);values,W=la.eigh((lm+lm.conj().T)/2,check_finite=True)
    guessed=int(np.count_nonzero(values<0));require(maximum_count<=len(values),'COUNT_DIMENSION')
    V=W[:,:maximum_count];d=float(up(1+max(0.,-float(values[0]))))
    # Explicit interval scalar multiplication retains rounding of V*d.
    raised=lower+matmul(C.point(V)*R(d),transpose(C.point(V)))
    congruence=matmul(transpose(C.point(W)),matmul(raised,C.point(W)))
    check=positive_definite(congruence)
    artifacts.update(W=W,V=V,D=np.array(d),mx=mx,my=my)
    saved_interval(artifacts,'L_lower',lower);saved_interval(artifacts,'congruence',congruence)
    result={'status':'CONTINUOUS_SPECTRAL_COUNT_UPPER_VERIFIED' if check['positive_definite'] else 'FLOAT_PREFLIGHT_INTERVAL_INERTIA_INCOMPLETE',
        'model_canonical_sha256':hashlib.sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'calibration':calibration,'M':M,'s_exact':str(F(s)),'f_cut_exact':str(F(f_cut)),'k_exact':str(k),'tail_q2_exact':str(tail),'c_exact':str(c),'tail_coercivity_exact':str(margin),
        'dimension':2*len(mx),'upper_count':maximum_count if check['positive_definite'] else None,'proposed_rank_correction':maximum_count,
        'float_negative_count_not_certificate':guessed,'float_lowest_values':values[:12].tolist(),'strict_congruence_positive_definiteness':check,
        'source_of_bound':'Full infinite-tail relaxation; exact transverse constraint; inverse-action lower form; interval rank correction and congruence Gershgorin',
        'frequency_count_definition':'positive frequencies strictly below f_cut, multiplicities included; fixed k, frozen coefficients',
        'original_target_rank_bound':False,'production_changed':False,'new_MPB_Meep_API_calls':0}
    return result,artifacts
