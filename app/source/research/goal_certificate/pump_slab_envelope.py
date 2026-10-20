"""Scalar/model checker for a periodic pump slab supersolution theorem.

Standard library only; exact decoded binary64 materials, not experimental data.
The theorem and scope are in PROOF_ZH.md. This does not certify the SH branch.
"""
from fractions import Fraction as F
from math import factorial, isfinite, nextafter, inf
from hashlib import sha256
import json

def number(x):
    if type(x) not in (int,float) or not isfinite(x):raise ValueError('NONFINITE_MODEL_SCALAR')
    return F(x)

def pi_interval():
    def atan(q):
        s=sum((F((-1)**j,(2*j+1)*q**(2*j+1)) for j in range(24)),F(0))
        return s,s+F(1,49*q**49)
    a,b=atan(5),atan(239)
    return 16*a[0]-4*b[1],16*a[1]-4*b[0]

def arithmetic(wavelength):
    # Verify a joint rectangle containing the stored wavelength and its nominal
    # decimal, rather than choosing whichever interpretation helps the proof.
    wave=number(wavelength);lo=min(wave,F(31,20));hi=max(wave,F(31,20))
    pl,ph=pi_interval();kl,kh=2*pl/hi,2*ph/lo
    h,alpha=F(337,100),F(59,10)
    assert kh*kh*F(11,16)<h*h and kl*kl*F(4257,2000)>alpha*alpha
    x=h*F(3,10);assert 0<x<pl/2
    sin_upper=x-x**3/6+x**5/120
    cos_lower=1-x*x/2+x**4/24-x**6/720
    assert cos_lower>0 and sin_upper/cos_lower<F(161,100)
    assert alpha*F(17,10)>10
    exp_lower=sum((F(20**j,factorial(j)) for j in range(5)),F(0))
    assert (exp_lower-1)/(exp_lower+1)>F(999,1000)
    left=h*F(161,100);right=alpha*F(999,1000)
    te=right-left;tm=right/F(1037,500)-left/F(489,100)
    assert te>0 and tm>0
    return {'TE_margin_lower_exact':str(te),'TM_margin_lower_exact':str(tm),
            'wavelength_joint_interval_exact':[str(lo),str(hi)],
            'pi_interval_exact':[str(pl),str(ph)],'all_rational_inequalities':True}

def applicable(model):
    t=model['task'];r=t['requirements'];mat=model['materials']['1.55']
    if model['numeric_semantics']!='binary64-inputs-exact-rational-geometry-v1':raise ValueError('NUMERIC_SEMANTICS')
    if t['adapter']!='mode-xcut-v1' or r['length_unit']!='um':raise ValueError('MODEL_UNITS')
    if r['wavelengths_um']!=[1.55,.775] or mat['wavelength_um']!=1.55:raise ValueError('WAVELENGTH_CHANGED')
    if r['orientation']!='xcut-yprop-v1' or r['material_model']!='zelmon1997-congruent-21C-v1':raise ValueError('MATERIAL_MODEL')
    if r['temperature_c']!=21 or r['composition']!='undoped-congruent':raise ValueError('MATERIAL_CONDITIONS')
    if t['numerics']['domain_um']!=[4,4] or model['boundary']!='periodic' or model['transverse_bloch_k']!=[0,0]:raise ValueError('PERIODIC_BOUNDARY')
    if number(model['relative_permeability'])!=1:raise ValueError('PERMEABILITY')
    film,slab,width=map(number,(r['film_thickness_um'],r['slab_thickness_um'],r['ridge_width_um']))
    if not 0<slab<=film<=F(3,5) or not 0<width<=4:raise ValueError('GEOMETRY_OUTSIDE_ENVELOPE')
    epsilon=mat['laboratory_epsilon']
    if len(epsilon)!=3 or any(len(row)!=3 for row in epsilon):raise ValueError('MATERIAL_TENSOR')
    for i in range(3):
        for j in range(3):
            v=number(epsilon[i][j])
            if i!=j and v!=0:raise ValueError('NONDIAGONAL_MODEL_UNSUPPORTED')
            if i==j and not 0<v<=F(489,100):raise ValueError('MATERIAL_ABOVE_ENVELOPE')
    for name in ('top_epsilon','bottom_epsilon'):
        if not 0<number(model[name])<=F(1037,500):raise ValueError('CLADDING_ABOVE_ENVELOPE')
    # Check cladding manifest values against the exact stored result of the
    # existing index-squared evaluation, then freeze that result as epsilon.
    if model['top_epsilon']!=r['top_index']**2 or model['bottom_epsilon']!=r['bottom_index']**2:raise ValueError('CLADDING_BINDING')
    return True

def check(model):
    binding=sha256(json.dumps(model,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    try:
        applicable(model);proof=arithmetic(model['materials']['1.55']['wavelength_um'])
        # A separate Decimal implementation recomputes the scalar inequalities;
        # it does not consume this implementation's pi or margin outputs.
        from .pump_decimal_review import verify
        second=verify(model['materials']['1.55']['wavelength_um'])
        assert second['scalar_review_passed']
    except (ValueError,KeyError,TypeError,AssertionError,IndexError) as error:
        return {'status':'NOT_APPLICABLE_OR_UNVERIFIED','reason':str(error),
                'model_sha256':binding,'production_changed':False}
    upper=float(F(41,20))
    if F(upper)<F(41,20):upper=nextafter(upper,inf)
    return {'status':'MODEL_PUMP_UPPER_VERIFIED','model_sha256':binding,
            'strict_neff_upper_exact':'41/20','neff_upper_outward_binary64':upper,
            'proof':proof,'second_implementation':second,
            'scope':'All forward pump modes of the specified frozen-coefficient periodic model; not measured material/device certification',
            'theorem':'Material order on common div_beta H=0 space, TE/TM positive periodic supersolution, strict ground-state identity',
            'proof_review':'Explicit local mathematical derivation and separate scalar implementation; not an external human review',
            'SH_or_target_rank_certified':False,'production_changed':False,'new_eigensolves':0,'new_API_calls':0}
