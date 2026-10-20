"""Synthetic protocol fixtures; no provider, solver or continuous-truth claims."""
import copy
import hashlib
import json

import pytest

from photonguard import mode_diagnosis as diagnosis
from photonguard.core import digest, load, write_json
from photonguard.evidence_facts import pointer_value
from photonguard.workflow import write_once
from test_mode_ai import data, action


def refresh_report(data, edit):
    """Update only a synthetic fixture whose solver recomputation is mocked."""
    root=data[5];report=load(root/'report.json');edit(report)
    write_json(root/'report.json',report)
    manifest=load(root/'manifest.json')
    manifest['files']['report.json']=hashlib.sha256((root/'report.json').read_bytes()).hexdigest()
    write_json(root/'manifest.json',manifest)


def interpretation(code):
    refs={
        'continuous_error_bound_unknown':[
            'evidence.continuous_solution_error_certification.supported',
            'evidence.continuous_solution_error_certification.status'],
        'discrete_checks_do_not_certify_continuous_error':[
            'evidence.root_closure_same_discrete_problem.supported',
            'evidence.mode_shape_identity_within_computed_candidates.supported',
            'evidence.continuous_solution_error_certification.supported',
            'evidence.continuous_solution_error_certification.status'],
        'setting_sensitivity_not_error_bound':[
            'evidence.tested_setting_sensitivity.supported',
            'evidence.tested_setting_sensitivity.not_a_true_error_bound',
            'evidence.continuous_solution_error_certification.supported'],
    }
    return {'claim_type':'mode_interpretation','fact_refs':refs[code],'conclusion':code}


def no_change(claim):
    return {'decision':'no_change','changes':[],'rationale':'structured_claims',
        'evidence_ids':['evidence.continuous_solution_error_certification.status'],
        'issues':[],'claims':[claim]}


def add_root_closure(report):
    for check in report['checks']:
        if check['id'].endswith('.root_and_boundary'):
            check.update(frequency_closure=1e-12,cycles_to_radians_and_neff_verified=True)


def test_extension_preserves_old_context_and_exact_legacy_facts(data):
    legacy,old_table,old_context=diagnosis.build_request(*data,include_evidence_levels=False)
    request,table,context=diagnosis.build_request(*data)
    assert old_context==context
    assert all(table['facts'][key]==value for key,value in old_table['facts'].items())
    assert legacy['contract']==request['contract']=='mode-qpm-diagnosis-1'
    assert legacy['allowed_actions']==request['allowed_actions']
    assert legacy['observations']['resource_eligible_changes']==request['observations']['resource_eligible_changes']
    assert 'evidence_levels' not in legacy['observations']
    assert request['observations']['evidence_levels']['derived_from_verified_bundle_only']
    levels=diagnosis.evidence_levels(context['mode_report'],data[3],context['qpm_report'])
    raw=(json.dumps(levels,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    assert hashlib.sha256(raw).hexdigest()==request['observations']['evidence_levels']['artifact_sha256']
    for key,fact in table['facts'].items():
        if key.startswith('evidence.'):
            assert fact['source_artifact']==diagnosis.EVIDENCE_LEVELS_ARTIFACT
            assert fact['artifact_sha256']==hashlib.sha256(raw).hexdigest()
            assert pointer_value(levels,fact['json_pointer'])==fact['value']
            assert request['observations']['evidence_facts']['facts'][key]['kind']=='evidence_scope_fact'
    result=diagnosis.validate_action(data[0],data[2],data[3],request,table,action(request))
    assert result['status']=='PROPOSED' and result['patch']['change']['new']==64
    assert result['independent_evidence_scope_note'] in result['reason']
    assert 'continuous-truth certification' in request['prompt']
    assert len(json.dumps(request,ensure_ascii=True).encode())<65536


def test_missing_and_duplicate_checks_cannot_become_vacuous_support(data):
    report=load(data[5]/'report.json');add_root_closure(report)
    full=diagnosis.evidence_levels(report,data[3],data[6])
    assert all(level['supported'] for level in full['levels'][:-1])
    assert full['levels'][-1]=={
        'kind':'continuous_solution_error_certification','supported':False,'status':'UNKNOWN'}
    for suffix,index in [('root_and_boundary',1),('mode_identity',2),('tested_setting_sensitivity',3)]:
        reduced=copy.deepcopy(report)
        entry=next(c for c in reduced['checks'] if c['id'].endswith('.'+suffix))
        reduced['checks'].remove(entry)
        assert diagnosis.evidence_levels(reduced,data[3],data[6])['levels'][index]['supported'] is False
        duplicate=copy.deepcopy(report);duplicate['checks'].append(copy.deepcopy(entry))
        assert diagnosis.evidence_levels(duplicate,data[3],data[6])['levels'][index]['supported'] is False
    assert diagnosis.evidence_levels({'checks':[]},data[3],None)['levels'][1]['supported'] is False


def test_root_closure_is_separate_from_boundary_and_sensitivity_is_not_a_pass(data):
    report=load(data[5]/'report.json');add_root_closure(report)
    for check in report['checks']:
        if check['id'].endswith(('.root_and_boundary','.tested_setting_sensitivity')):
            check['status']='FAIL'
    levels=diagnosis.evidence_levels(report,data[3],data[6])
    assert levels['levels'][1]['supported'] is True
    assert levels['levels'][3]['supported'] is True
    assert levels['levels'][3]['not_a_true_error_bound'] is True
    root=next(c for c in report['checks'] if c['id'].endswith('.root_and_boundary'))
    for bad in (True,float('nan'),1e-7,-1):
        root['frequency_closure']=bad
        assert diagnosis.evidence_levels(report,data[3],data[6])['levels'][1]['supported'] is False


@pytest.mark.parametrize('code',[
    'continuous_error_bound_unknown','discrete_checks_do_not_certify_continuous_error',
    'setting_sensitivity_not_error_bound'])
def test_scope_interpretations_are_independently_checked_and_cannot_authorize_patch(data,code):
    refresh_report(data,add_root_closure)
    request,table,_=diagnosis.build_request(*data)
    claim=interpretation(code);result=diagnosis.validate_action(data[0],data[2],data[3],request,table,no_change(claim))
    assert result['status']=='NO_PATCH' and result['patch'] is None
    assert result['explanation_audit']['accepted']==[claim]
    value=action(request);value['claims']=[claim]
    with pytest.raises(ValueError,match='WITHOUT_RELEVANT_VERIFIED_BASIS'):
        diagnosis.validate_action(data[0],data[2],data[3],request,table,value)


def test_missing_root_metrics_do_not_support_discrete_closure_interpretation(data):
    request,table,_=diagnosis.build_request(*data)
    value=no_change(interpretation('discrete_checks_do_not_certify_continuous_error'))
    with pytest.raises(ValueError,match='EXPLANATION_UNSUPPORTED'):
        diagnosis.validate_action(data[0],data[2],data[3],request,table,value)


@pytest.mark.parametrize('claim',[
    {'claim_type':'mode_interpretation','fact_refs':['mode.verification_status'],
        'conclusion':'continuous_error_certified'},
    {'claim_type':'mode_interpretation','fact_refs':['mode.verification_status','qpm.verification_status'],
        'conclusion':'discrete_checks_do_not_certify_continuous_error'},
    {'claim_type':'measured_fact','fact_refs':['evidence.continuous_solution_error_certification.supported'],
        'operation':'value','value':True,'unit':'boolean'},
    {'claim_type':'measured_fact','fact_refs':['evidence.continuous_solution_error_certification.status'],
        'operation':'value','value':'PASS','unit':'status'},
])
def test_model_cannot_upgrade_discrete_checks_to_continuous_certification(data,claim):
    request,table,_=diagnosis.build_request(*data)
    with pytest.raises(ValueError,match='EXPLANATION_UNSUPPORTED'):
        diagnosis.validate_action(data[0],data[2],data[3],request,table,no_change(claim))


def test_unbound_research_and_caller_certificate_are_never_imported(data):
    def inject(report):
        report['research_phase_bounds']={'certified':True,'status':'PASS','note':'UNBOUND_RESEARCH_SENTINEL'}
        report['evidence_levels']={'continuous_solution_error_certification':True}
    refresh_report(data,inject)
    request,table,_=diagnosis.build_request(*data)
    assert 'UNBOUND_RESEARCH_SENTINEL' not in json.dumps(request)
    assert table['facts']['evidence.continuous_solution_error_certification.supported']['value'] is False
    assert table['facts']['evidence.continuous_solution_error_certification.status']['value']=='UNKNOWN'


def save_archived_fixture(data,tmp_path,include_levels):
    """Handwritten archive fixture; live metadata is synthetic test data only."""
    request,table,context=diagnosis.build_request(*data,include_evidence_levels=include_levels)
    parent=tmp_path/'synthetic-archive';parent.mkdir();root=parent/'request';root.mkdir()
    binding={'SYNTHETIC_ARCHIVE':True};write_once(parent/'binding.json',binding)
    response=action(request)
    artifacts={'request.json':request,'facts.json':table,'diagnostic-context.json':context,
        'start.json':{'request_sha256':digest(request),'source_binding_sha256':digest(binding)},
        'response.action.json':response,'result.json':{'response_action_sha256':digest(response)},
        'provider.audit.json':{'transport_kind':'live_https','actual_llm_calls':1,'test_fixture':True}}
    if include_levels:
        artifacts[diagnosis.EVIDENCE_LEVELS_ARTIFACT]=diagnosis.evidence_levels(context['mode_report'],data[3],context['qpm_report'])
    for name,value in artifacts.items():write_once(root/name,value)
    return root


@pytest.mark.parametrize('include_levels',[False,True])
def test_old_and_new_saved_fact_versions_reassess_without_rewriting_or_requests(data,tmp_path,monkeypatch,include_levels):
    root=save_archived_fixture(data,tmp_path,include_levels)
    original={p.name:p.read_bytes() for p in root.iterdir()}
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:{'git_commit':'f'*40,'files':{'SYNTHETIC':'a'*64}})
    result=diagnosis.reassess_saved(data,root)
    assert result['status']=='PROPOSED' and result['additional_model_calls']==result['provider_attempts']==0
    assert all((root/name).read_bytes()==raw for name,raw in original.items())
    assert bool(result['independent_evidence_scope_note']) is include_levels


def test_changed_saved_scope_artifact_blocks_reassessment(data,tmp_path,monkeypatch):
    root=save_archived_fixture(data,tmp_path,True)
    path=root/diagnosis.EVIDENCE_LEVELS_ARTIFACT;value=load(path)
    value['levels'][-1].update(supported=True,status='PASS');write_json(path,value)
    monkeypatch.setattr('photonguard.approved_gui.source_manifest',lambda _:{'git_commit':'f'*40,'files':{'SYNTHETIC':'a'*64}})
    with pytest.raises(ValueError,match='EVIDENCE_LEVELS_BINDING'):
        diagnosis.reassess_saved(data,root)
