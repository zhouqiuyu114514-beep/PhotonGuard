"""Reference-order compatibility and resource abstention; no solver or API."""
import copy
import hashlib
import itertools

import pytest

from photonguard import mode_diagnosis as diagnosis
from photonguard.core import digest, load, write_json
from photonguard.adapters import qpm_phase
from test_mode_ai import data
from test_mode_ai_evidence_levels import save_archived_fixture


INTERPRETATIONS=[
    ('phase_precision_insufficient',[
        'check.phase_precision.metric','check.phase_precision.tolerance','qpm.verification_status'],
        [.2,.1,'INCONCLUSIVE']),
    ('locked_design_not_met',[
        'mode.verification_status','qpm.verification_status','qpm.design_goal_status','qpm.phase_factor_NOT_efficiency'],
        ['PASS','PASS','NOT_MET',.2]),
    ('continuous_error_bound_unknown',[
        'evidence.continuous_solution_error_certification.supported',
        'evidence.continuous_solution_error_certification.status'],[False,'UNKNOWN']),
    ('discrete_checks_do_not_certify_continuous_error',[
        'evidence.root_closure_same_discrete_problem.supported',
        'evidence.mode_shape_identity_within_computed_candidates.supported',
        'evidence.continuous_solution_error_certification.supported',
        'evidence.continuous_solution_error_certification.status'],[True,True,False,'UNKNOWN']),
    ('setting_sensitivity_not_error_bound',[
        'evidence.tested_setting_sensitivity.supported',
        'evidence.tested_setting_sensitivity.not_a_true_error_bound',
        'evidence.continuous_solution_error_certification.supported'],[True,True,False]),
]


def table_for(refs,values):
    return {'facts':{ref:{'value':value,'unit':'dimensionless'} for ref,value in zip(refs,values)},
        'facts_sha256':'SYNTHETIC_UNIT_FIXTURE'}


def abstention(claim):
    return {'decision':'no_change','changes':[],'rationale':'structured_claims',
        'evidence_ids':[],'issues':[],'claims':[claim]}


@pytest.mark.parametrize('code,refs,values',INTERPRETATIONS)
def test_every_complete_interpretation_permutation_is_audited_without_changing_response(code,refs,values):
    table=table_for(refs,values)
    canonical={'claim_type':'mode_interpretation','fact_refs':refs,'conclusion':code}
    for permutation in itertools.permutations(refs):
        claim={**canonical,'fact_refs':list(permutation)};before=copy.deepcopy(claim)
        audit=diagnosis.audit_mode_claims([claim],table)
        assert audit['status']=='VERIFIED_STRUCTURED_CLAIMS'
        assert claim==before and audit['accepted']==[canonical]
        expected=[] if list(permutation)==refs else [{'claim_index':0,
            'original_fact_refs':list(permutation),'canonical_fact_refs':refs}]
        assert audit['reference_order_normalizations']==expected


@pytest.mark.parametrize('defect',[
    'duplicate','missing','extra','unknown_ref','non_string','not_list','unknown_conclusion','false_premise'])
def test_reference_order_compatibility_never_repairs_missing_invalid_or_unproved_premises(defect):
    code,refs,values=copy.deepcopy(INTERPRETATIONS[2]);table=table_for(refs,values)
    claim={'claim_type':'mode_interpretation','fact_refs':refs[:],'conclusion':code}
    if defect=='duplicate':claim['fact_refs']=[refs[0],refs[0]]
    elif defect=='missing':claim['fact_refs']=refs[:1]
    elif defect=='extra':claim['fact_refs']=refs+['mode.verification_status']
    elif defect=='unknown_ref':claim['fact_refs']=[refs[0],'invented.fact']
    elif defect=='non_string':claim['fact_refs']=[refs[0],{}]
    elif defect=='not_list':claim['fact_refs']=tuple(refs)
    elif defect=='unknown_conclusion':claim['conclusion']='continuous_error_certified'
    elif defect=='false_premise':table['facts'][refs[0]]['value']=True
    audit=diagnosis.audit_mode_claims([claim],table)
    assert audit['status']=='UNSUPPORTED' and not audit['accepted']
    assert not audit['reference_order_normalizations']


@pytest.mark.parametrize('operation,value',[('pair',[1.,3.]),('difference',2.)])
def test_measured_operand_order_remains_semantic_not_normalized(operation,value):
    refs=['first.metric','second.metric'];table=table_for(refs,[1.,3.])
    claim={'claim_type':'measured_fact','fact_refs':refs,'operation':operation,'value':value,'unit':'dimensionless'}
    assert diagnosis.audit_mode_claims([claim],table)['status']=='VERIFIED_STRUCTURED_CLAIMS'
    claim['fact_refs']=list(reversed(refs))
    result=diagnosis.audit_mode_claims([claim],table)
    assert result['status']=='UNSUPPORTED' and not result['reference_order_normalizations']
    claim['value']=[3.,1.] if operation=='pair' else -2.
    result=diagnosis.audit_mode_claims([claim],table)
    assert result['status']=='VERIFIED_STRUCTURED_CLAIMS' and result['accepted']==[claim]
    assert not result['reference_order_normalizations']


def test_bounded_comparison_order_and_mixed_claim_indices_stay_exact():
    code,refs,values=INTERPRETATIONS[2];table=table_for(refs,values)
    table['facts'].update(table_for(['check.phase.metric','check.phase.tolerance'],[.2,.1])['facts'])
    interpretation={'claim_type':'mode_interpretation','fact_refs':list(reversed(refs)),'conclusion':code}
    wrong={'claim_type':'bounded_inference','fact_refs':['check.phase.tolerance','check.phase.metric'],
        'operation':'above_threshold','conclusion':'tested_metric_exceeds_tolerance'}
    measured={'claim_type':'measured_fact','fact_refs':['check.phase.metric'],
        'operation':'value','value':.2,'unit':'dimensionless'}
    result=diagnosis.audit_mode_claims([measured,interpretation,wrong,interpretation],table)
    assert result['status']=='UNSUPPORTED'
    assert result['findings']==[{'claim_index':2,'code':'CLAIM_COMPARISON_CONTEXT'}]
    assert [item['claim_index'] for item in result['reference_order_normalizations']]==[1,3]


def test_retained_teaching_three_reference_difference_is_rejected_without_repairing_the_response():
    # Exact public scalar claim retained from the one-shot eval-v3 teaching case.
    # This is an offline protocol regression, not another provider or solver run.
    refs=['qpm.bare_delta_beta_rad_per_um','qpm.grating_K_rad_per_um','qpm.residual_delta_beta_rad_per_um']
    values=[1.580250699912698,.3141592653589793,1.2660914345537186]
    table=table_for(refs,values)
    for fact in table['facts'].values():fact['unit']='rad_per_um'
    saved={'claim_type':'measured_fact','fact_refs':refs,'operation':'difference',
        'value':values[2],'unit':'rad_per_um'};before=copy.deepcopy(saved)
    audit=diagnosis.audit_mode_claims([saved],table)
    assert audit['status']=='UNSUPPORTED' and audit['findings']==[{'claim_index':0,'code':'CLAIM_OPERATION'}]
    assert saved==before and not audit['reference_order_normalizations']
    # Independent valid examples preserve SECOND minus FIRST and use a separate
    # scalar citation for the recorded result, rather than normalizing the failure.
    difference={**saved,'fact_refs':[refs[1],refs[0]]}
    scalar={**saved,'fact_refs':[refs[2]],'operation':'value'}
    audit=diagnosis.audit_mode_claims([difference,scalar],table)
    assert audit['status']=='VERIFIED_STRUCTURED_CLAIMS' and audit['accepted']==[difference,scalar]
    wrong_direction={**difference,'fact_refs':refs[:2]}
    assert diagnosis.audit_mode_claims([wrong_direction],table)['findings']==[{
        'claim_index':0,'code':'CLAIM_VALUE_OR_DIRECTION'}]


def test_base80_without_eligible_change_abstains_and_does_not_recommend_refinement(data):
    arguments=list(data);candidate=copy.deepcopy(data[2]);candidate['numerics']['resolution']=80;arguments[2]=candidate
    root=data[5];write_json(root/'numerical-candidate.json',candidate)
    manifest=load(root/'manifest.json')
    manifest['files']['numerical-candidate.json']=hashlib.sha256((root/'numerical-candidate.json').read_bytes()).hexdigest()
    write_json(root/'manifest.json',manifest)
    request,table,_=diagnosis.build_request(*arguments)
    assert request['observations']['resource_eligible_changes']==[]
    refs=INTERPRETATIONS[0][1]
    action=abstention({'claim_type':'mode_interpretation','fact_refs':list(reversed(refs)),
        'conclusion':'phase_precision_insufficient'});original=copy.deepcopy(action)
    before=[digest(item) for item in (arguments[0],arguments[2],arguments[3],table)]
    result=diagnosis.validate_action(arguments[0],candidate,arguments[3],request,table,action)
    assert result['status']=='NO_PATCH' and result['patch'] is None and action==original
    assert '没有可批准的进一步数值修改' in result['reason']
    assert result['independent_resource_scope_note'] in result['reason']
    assert '可审阅有限数值加密' not in result['reason']
    assert before==[digest(item) for item in (arguments[0],arguments[2],arguments[3],table)]
    proposed={**action,'decision':'propose_patch','changes':[{'path':['numerics','resolution'],'new':120}],
        'issues':[{'location_key':'numerics.resolution','reason':'structured_claims','evidence_ids':['phase_precision']}]}
    with pytest.raises(ValueError,match='OUTSIDE_ELIGIBLE'):
        diagnosis.validate_action(arguments[0],candidate,arguments[3],request,table,proposed)


def test_teaching_not_met_keeps_locked_design_after_reference_normalization(data):
    arguments=list(data);goal=copy.deepcopy(data[3]);goal['length_um']=10;arguments[3]=goal
    modes,receipts=diagnosis.mpb_modes.qpm_sources(data[5])
    qtask={'schema_version':1,'adapter':'qpm-shg-phase-v1','task_id':data[0]['task_id']+'-QPM',
        'requirements':goal,'modes':modes,'provenance':{'reference':data[4],
        'mode_task_sha256':digest(data[0]),'confirmed_goal_sha256':digest(goal),
        'confirmation_inherited_from_explicit_workflow_consent':True}}
    arguments[-1]=qpm_phase.evaluate(qtask,verified_mode_sources=receipts)
    assert arguments[-1]['verification_status']=='PASS' and arguments[-1]['design_goal_status']=='NOT_MET'
    request,table,_=diagnosis.build_request(*arguments)
    refs=INTERPRETATIONS[1][1];value=abstention({'claim_type':'mode_interpretation',
        'fact_refs':list(reversed(refs)),'conclusion':'locked_design_not_met'})
    original_goal=copy.deepcopy(goal)
    result=diagnosis.validate_action(data[0],data[2],goal,request,table,value)
    assert result['status']=='NO_PATCH' and result['patch'] is None and goal==original_goal
    assert '合法设计结果' in result['reason'] and not result['independent_resource_scope_note']


@pytest.mark.parametrize('include_levels',[False,True])
def test_saved_legacy_and_current_references_reassess_with_explicit_scope_without_rewriting(data,tmp_path,monkeypatch,include_levels):
    root=save_archived_fixture(data,tmp_path,include_levels)
    code,refs,_=INTERPRETATIONS[2 if include_levels else 0]
    response=abstention({'claim_type':'mode_interpretation','fact_refs':list(reversed(refs)),'conclusion':code})
    # Create the archived rejection fixture before taking the immutability snapshot.
    write_json(root/'response.action.json',response)
    write_json(root/'result.json',{'status':'REJECTED','response_action_sha256':digest(response)})
    before={path.name:path.read_bytes() for path in root.iterdir()}
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:{'git_commit':'f'*40,'files':{'SYNTHETIC':'a'*64}})
    result=diagnosis.reassess_saved(data,root)
    assert result['status']=='NO_PATCH' and result['additional_model_calls']==result['provider_attempts']==0
    assert 'REFERENCE_ORDER_ONLY' in result['reassessment_scope']
    assert result['explanation_audit']['reference_order_normalizations']==[{
        'claim_index':0,'original_fact_refs':list(reversed(refs)),'canonical_fact_refs':refs}]
    assert all((root/name).read_bytes()==content for name,content in before.items())
