"""Replay the complete saved research chain for the actual selected record.

This is an explicit research sidecar, not a Boolean-based production promotion.
Continuous integral and upper-count arithmetic inherits the source-bound
outward computations and common-domain proofs listed in the evidence packet.
"""
import hashlib,json
from pathlib import Path
from fractions import Fraction as F
from .root_tube_arithmetic import recombine_forms,tube_bounds
from .fixed_s_rank_one import witness
from .selector_contract import read_contract
from .selector_observable_bounds import sqrt_bounds,outward
from .projector_budget import bound
from .selector_cone_bounds import conditional_cone_bounds
from .record_field_distance import distance_bound
from .pump_slab_envelope import check as pump_check
from .evidence_resolver import EvidenceResolver


def read(path):return json.loads(Path(path).read_text())


def verify_bound(entry, resolver=None):
    return (resolver or EvidenceResolver()).resolve(entry).path


def verified_endpoint(value):
    integrals={k:list(map(F,v)) for k,v in value['integrals'].items()}
    if any(lo>hi for lo,hi in integrals.values()):raise ValueError('REVERSED_INTEGRAL')
    mass=integrals['mass'];num=integrals['N'];r=integrals['residual2']
    if mass[0]<=0 or num[0]<=0 or r[1]<0:raise ValueError('ENDPOINT_NORMS')
    ray=[num[0]/mass[1],num[1]/mass[0]]
    return {'true_rayleigh_interval':list(map(str,ray)),'true_rayleigh_residual2_upper':str(r[1]/mass[0])}


def replay(out, *, resolver=None):
    import numpy as np
    from .interval_arithmetic import R,C
    from .upper_dense import positive_definite
    out=Path(out);plan=read(out/'execution-plan.json');center=read(out/'center-stage-plan.json');record_plan=read(out/'record-stage-plan.json')
    all_inputs={**plan['inputs'],**center['inputs'],**record_plan['inputs']}
    resolver=resolver or EvidenceResolver()
    for source in (plan,center,record_plan):
        for entry in source['inputs'].values():verify_bound(entry,resolver)
    paths={key:verify_bound(entry,resolver) for key,entry in plan['inputs'].items()}
    model=read(paths['model']);record=read(paths['record'])
    if model['material_result_hashes']['0.775']!=plan['inputs']['record']['sha256'] or model['adapter_source_sha256']!=plan['inputs']['worker']['sha256']:
        raise ValueError('ORIGINAL_MODEL_WORKER_RECORD_BINDING')
    contract=read_contract(paths['worker'])
    candidates=[m for m in record['all_modes'] if m['electric_component_norm_fraction'][0]>.55 and m['neff']>1.44 and m['core_electric_energy_fraction']>.35 and m['outer_cell_energy_fraction']<.05]
    if len(record['all_modes'])!=4 or max(candidates,key=lambda x:x['neff'])!=record['selected_mode']:raise ValueError('ACTUAL_NUMERIC_SELECTION')
    selected=record['selected_mode'];sc=F(selected['neff']);h=F(plan['half_width_exact'])
    if sc!=F(plan['center_s_exact']) or selected['fields_npz']!=Path(plan['inputs']['selected_field']['path']).name:
        raise ValueError('SELECTED_FIELD_PARAMETER_BINDING')
    if record_plan['inputs']['proposal']['sha256']!=hashlib.sha256((out/'CENTER/proposal.npz').read_bytes()).hexdigest():raise ValueError('COMMON_CENTER_FIELD')
    freeze=read(paths['common_freeze'])
    if freeze['model_sha256']!=plan['inputs']['model']['sha256'] or freeze['trial_file_sha256']!=plan['inputs']['common_dofs']['sha256']:
        raise ValueError('COMMON_SMALL_FORM_DOF_BINDING')
    forms=recombine_forms(read(paths['forms_first']),read(paths['forms_last']),sc)
    lower=[witness(forms,F(1283,1000),[1,2]),witness(forms,F(1299,1000),[0,1,2])];upper_replays=[]
    for i,cut in enumerate((F(1283,1000),F(1299,1000)),1):
        upper=read(out/('upper-'+str(i))/'result.json');matrix_path=out/('upper-'+str(i))/'matrices.npz'
        if (upper['upper_count']!=i+1 or upper['M']!=8 or upper['calibration'] is not None or F(upper['s_exact'])!=sc or F(upper['f_cut_exact'])!=cut
            or upper['execution_binding']['model_file_sha256']!=plan['inputs']['model']['sha256']
            or hashlib.sha256(matrix_path.read_bytes()).hexdigest()!=upper['execution_binding']['matrix_sha256']):raise ValueError('CENTER_UPPER_BINDING')
        with np.load(matrix_path,allow_pickle=False) as z:
            matrix=C(R(z['congruence_re_lo'],z['congruence_re_hi']),R(z['congruence_im_lo'],z['congruence_im_hi']))
        proof=positive_definite(matrix)
        if not proof['positive_definite']:raise ValueError('UPPER_CONGRUENCE_REPLAY')
        upper_replays.append({'cut_exact':str(cut),'upper_count':i+1,'margin':proof['strict_margin_lower']})
    raw_endpoints=[read(out/f'CENTER/endpoint-{i}.json') for i in (0,1)]
    if [F(v['s_exact']) for v in raw_endpoints]!=[sc-h,sc+h]:raise ValueError('COMMON_TUBE_ENDPOINTS')
    endpoints=[verified_endpoint(v) for v in raw_endpoints]
    regions=[[[value if i==j else 0 for j in range(3)] for i in range(3)] for value in (model['top_epsilon'],model['bottom_epsilon'])]
    regions.append(model['materials']['0.775']['laboratory_epsilon'])
    if min(F(m[i][i]) for m in regions for i in range(3))!=1:raise ValueError('LIPSCHITZ_EPSILON')
    tube=tube_bounds(endpoints,sc,h,F(1283,1000),F(1299,1000),1/F(.775))
    raw=raw_endpoints[0]['integrals'];v={k:list(map(F,a)) for k,a in raw.items()}
    electric=sqrt_bounds(v['electric'][0]/v['mass'][1])[0];budget=bound(F(tube['q_upper_exact']),electric)
    def ratio(a,b):return [max(F(0),a[0]/b[1]),min(F(1),a[1]/b[0])]
    p=ratio(v['Ex'],v['electric_L2']);c=ratio(v['core'],v['electric']);o=ratio(v['outer'],v['electric'])
    mean=[v['electric'][0]/v['electric_L2'][1],v['electric'][1]/v['electric_L2'][0]]
    selector=conditional_cone_bounds(p,c,o,F(budget['electric_error_upper_exact']),sqrt_bounds(mean[1])[1],epsilon_regions=regions,mean_epsilon=mean)
    integrals=read(out/'RECORD/integrals.json')
    if integrals['exact_triangle_partition_equalities']!=12800:raise ValueError('RECORD_PARTITION_CHECKS')
    association=distance_bound(integrals,raw['mass'],F(tube['eta_upper_exact']))
    if (not tube['root_uniqueness_if_bound_inputs'] or not selector['strict_filters_would_pass_if_inputs_certified']
        or F(tube['q_upper_exact'])>F(139,1000) or electric<F(7,10)
        or not association['preregistered_quarter_distance_passes'] or not association['unique_dominant_rank_one_component']):
        raise ValueError('RETURNED_RECORD_BINDING_UNPROVEN')
    pump=pump_check(model)
    if pump['status']!='MODEL_PUMP_UPPER_VERIFIED':raise ValueError('PUMP_BOUND')
    from photonguard.research_phase_bounds import assess_neff_goal_envelope
    scalar=assess_neff_goal_envelope([0,pump['neff_upper_outward_binary64']],[outward(sc-h,False),outward(sc+h,True)],1.55,20,1000,.8,
        {'certificate':'This replayed source-bound continuous record/root-tube chain','F_is_phase_factor_not_conversion_efficiency':True})
    status='SELECTED_RECORD_CONTINUOUS_TARGET_BOUND'
    return {'status':status,'continuous_model_hash':plan['inputs']['model']['sha256'],'source_worker_hash':plan['inputs']['worker']['sha256'],
        'source_original_record':plan['inputs']['record'],'source_original_field':plan['inputs']['selected_field'],'source_trial':record_plan['inputs']['proposal'],
        'source_forms_and_DOF_hashes':{k:plan['inputs'][k] for k in ('forms_first','forms_last','common_dofs','common_freeze')},
        'rank_and_gap_proofs':{'lower':lower,'upper_replay':upper_replays,'tube':tube},'rayleigh_and_residual_bounds':endpoints,
        'selector_interval_bounds':selector,'record_to_trial_bound':association,'root_existence':True,'root_uniqueness':True,
        'J':tube['J_exact'],'selection_replay':{'contract':contract,'selected_mode':selected,'returned_roots':record['roots_cycles_per_um'],'passing_bands':[m['band'] for m in candidates]},
        'continuous_target_association':'Unique dominant continuous eigenprojection of the fixed L2 reconstruction of the actual selected record, with a unique root in J',
        'continuous_global_neff_maximum_proved':False,'pump_bound_replay':pump,'scalar_phase_checker':scalar,
        'research_goal_decision':'EXCLUDED_FOR_THIS_FROZEN_MODEL' if scalar['conditional_exclusion_if_interval_were_certified'] else 'INCONCLUSIVE',
        'certified_phase_factor_upper':scalar['conditional_phase_factor_upper'],'original_goal':{'length_um':1000,'period_um':20,'qpm_order':1,'phase_budget_rad':.1,'phase_factor_target':.8},
        'limits':['Original frozen-coefficient periodic continuous model; not fabricated-device or material-uncertainty certification',
            'Source-bound outward integration and upstream common-domain/tail proofs under the documented IEEE assumptions; not an external formal proof',
            'Actual returned-record correspondence uses the preregistered periodic nearest-center L2 reconstruction and dominant-projection criterion'],
        'production_JSON_modified':False,'new_MPB_Meep_API_calls':0,'input_bindings':all_inputs}
