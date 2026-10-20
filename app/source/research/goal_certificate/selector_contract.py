"""Read-only contract audit: production searches bands 1..4, then filters/max.

An all-spectrum existence claim does not prove membership in those candidates.
No imported Meep code is executed. Source changes fail closed at AST validation.
"""
import ast,hashlib
from pathlib import Path
from fractions import Fraction as F

def read_contract(source_path):
    raw=Path(source_path).read_bytes();tree=ast.parse(raw)
    constructors=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='ModeSolver']
    roots=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='find_k']
    if len(constructors)!=1 or len(roots)!=1:raise ValueError('PRODUCTION_SEARCH_SHAPE_CHANGED')
    bands=next((ast.literal_eval(k.value) for k in constructors[0].keywords if k.arg=='num_bands'),None)
    if bands!=4 or ast.literal_eval(roots[0].args[2])!=1 or ast.literal_eval(roots[0].args[3])!=4:raise ValueError('CANDIDATE_SEARCH_RANGE_CHANGED')
    assignments={n.targets[0].id:n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
    candidate=assignments['candidates'];selected=assignments['selected']
    expected=ast.parse("[m for m in modes if m['electric_component_norm_fraction'][dominant]>.55 and m['neff']>1.44 and m['core_electric_energy_fraction']>.35 and m['outer_cell_energy_fraction']<.05]",mode='eval').body
    select=ast.parse("max(candidates,key=lambda m:m['neff']) if candidates else None",mode='eval').body
    if ast.dump(candidate)!=ast.dump(expected) or ast.dump(selected)!=ast.dump(select):raise ValueError('SELECTION_RULE_CHANGED')
    masks={'core':"(abs(X)<=film/2)&(abs(Y)<=width/2) if quarter_turn else (abs(Y)<=film/2)&((abs(X)<=width/2) if not calibration_slab else True)",
        'boundary':"(abs(Y)>.45*sy)|((abs(X)>.45*sx) if not calibration_slab else False)",
        'norm':"np.sum(abs(field)**2,axis=(0,1,2))",'density':"np.maximum(energy[:,:,0],0)",'dominant':"1 if quarter_turn else 0"}
    for name,expression in masks.items():
        if ast.dump(assignments[name])!=ast.dump(ast.parse(expression,mode='eval').body):raise ValueError('SELECTION_MASK_OR_NORM_CHANGED:'+name)
    return {'status':'PRODUCTION_FINITE_CANDIDATE_CONTRACT_VERIFIED','worker_sha256':hashlib.sha256(raw).hexdigest(),'searched_bands':[1,2,3,4],
        'search_kind':'find_k roots on four requested sorted branches; numerical returned roots, not all continuous modes',
        'thresholds_exact':{'Ex_min':str(F(.55)),'neff_min':str(F(1.44)),'core_min':str(F(.35)),'outer_max':str(F(.05))},
        'core_mask':'ridge rectangle |x|<=width/2, |y|<=film/2; excludes residual slab outside ridge',
        'outer_mask':'|y|>.45*sy OR |x|>.45*sx','polarization_kind':'unweighted electric L2','selection':'maximum neff among passing returned candidates',
        'all_spectrum_existence_sufficient':False,'candidate_membership_still_requires_proof':True,'continuous_target_certified':False}

def assess_candidate_claim(contract,claim):
    return {'status':'CANDIDATE_MEMBERSHIP_UNPROVEN','continuous_target_rank_bound':False,'claim_accepted':False,
        'reason':'Band number, existence, parity, overlap, statuses and caller flags do not certify the continuous root belongs to the four returned production candidates.',
        'searched_bands':contract['searched_bands']}
