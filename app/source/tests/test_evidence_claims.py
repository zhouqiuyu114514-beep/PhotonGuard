"""Synthetic protocol boundary fixtures; never counted as physics examples."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from photonguard.core import digest
from photonguard.claims import audit_claims, audit_legacy_text
from photonguard.evidence_facts import collect_facts, verify_facts, compact_facts, verify_compact_facts

@pytest.fixture
def evidence(tmp_path):
    raw = tmp_path / 'raw'; raw.mkdir()
    for name, resolution, duration in [('base',80,100),('grid',120,100),('time',80,200)]:
        (raw / (name+'.json')).write_text(json.dumps({'engine':'SYNTHETIC_PROTOCOL_FIXTURE_NOT_MEEP',
            'target_recipe':{'resolution':resolution,'after_sources':duration,'courant':0.5}}))
    checks = [{'id': 'grid_sensitivity', 'status': 'FAIL', 'metrics': {'max_absolute_change':0.04629260417009062,'tolerance':0.005}},
        {'id':'time_sensitivity','status':'PASS','metrics':{'max_absolute_change':2.86e-10,'tolerance':0.005}}]
    (tmp_path/'report.json').write_text(json.dumps({'task_hash':'synthetic-task','candidate_hash':'synthetic-candidate','checks':checks}))
    (tmp_path/'manifest.json').write_text(json.dumps({'files':{str(p.relative_to(tmp_path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}}))
    return tmp_path

def pair():
    return {'claim_type':'measured_fact','fact_refs':['base.resolution','grid.resolution'],'operation':'pair','value':[80,120],'unit':'pixels_per_length_unit'}

def comparison():
    return {'claim_type':'bounded_inference','fact_refs':['check.grid_sensitivity.max_absolute_change','check.grid_sensitivity.tolerance'],
        'operation':'above_threshold','conclusion':'tested_metric_exceeds_tolerance'}

def test_correct_facts_and_conservative_hypothesis(evidence):
    table = collect_facts(evidence)
    audit = audit_claims([pair(),comparison(),{'claim_type':'hypothesis','fact_refs':['check.grid_sensitivity.status'],'conclusion':'spatial_discretization_possible'}],table)
    assert audit['status']=='VERIFIED_STRUCTURED_CLAIMS'
    assert '80 → 120' in audit['rendered'][0] and '不是唯一' in audit['rendered'][2]

@pytest.mark.parametrize('changes,code',[
    ({'value':[80,160]},'VALUE_OR_DIRECTION'),
    ({'value':[120,80]},'VALUE_OR_DIRECTION'),
    ({'unit':'nm'},'UNIT'),
    ({'fact_refs':['base.resolution','time.courant']},'UNIT'),
    ({'fact_refs':['made.up','grid.resolution']},'REFERENCE'),
    ({'conclusion':'all_causes_excluded'},'SCHEMA'),
])
def test_wrong_claim_with_real_reference_is_rejected(evidence,changes,code):
    claim=pair();claim.update(changes)
    audit=audit_claims([claim],collect_facts(evidence))
    assert audit['status']=='UNSUPPORTED' and code in audit['findings'][0]['code']

def test_comparison_cannot_reverse_direction(evidence):
    claim=comparison();claim.update(operation='within_threshold',conclusion='tested_metric_within_tolerance')
    assert audit_claims([claim],collect_facts(evidence))['status']=='UNSUPPORTED'

def test_pass_not_full_convergence_or_causality_proof(evidence):
    claim={'claim_type':'bounded_inference','fact_refs':['check.time_sensitivity.max_absolute_change','check.time_sensitivity.tolerance'],
        'operation':'within_threshold','conclusion':'tested_metric_within_tolerance'}
    result=audit_claims([claim],collect_facts(evidence))
    assert result['status']=='VERIFIED_STRUCTURED_CLAIMS' and '不证明' in result['rendered'][0]
    claim['conclusion']='all_time_step_errors_excluded'
    assert audit_claims([claim],collect_facts(evidence))['status']=='UNSUPPORTED'

@pytest.mark.parametrize('mutation',['value','unit','pointer','hash'])
def test_fact_table_mutation_or_pointer_swap_rejected(evidence,mutation):
    table=collect_facts(evidence);key={'value':'value','unit':'unit','pointer':'json_pointer','hash':'artifact_sha256'}[mutation]
    table['facts']['base.resolution'][key]='changed'
    with pytest.raises(ValueError,match='BINDING'):verify_facts(evidence,table)

def test_artifact_mutation_rejected(evidence):
    table=collect_facts(evidence)
    (evidence/'raw/grid.json').write_text('{}')
    with pytest.raises(ValueError,match='INTEGRITY'):verify_facts(evidence,table)

def test_historical_two_errors_are_preserved_and_detected(evidence):
    text='在80和160两种网格下，时间敏感度通过，说明不是时间步长问题。'
    before=text
    audit=audit_legacy_text(text,collect_facts(evidence))
    assert text==before and audit['status']=='UNSUPPORTED'
    assert {i['code'] for i in audit['findings']}=={'LEGACY_GRID_VALUE_MISMATCH','DURATION_IS_NOT_TIMESTEP_TEST'}
    assert audit['original_safe_response_preserved']

def test_unknown_historical_prose_is_not_falsely_verified(evidence):
    assert audit_legacy_text('原因可能很复杂。',collect_facts(evidence))['status']=='UNVERIFIED_LEGACY_TEXT'

def test_conservative_legacy_negation_is_not_reported_as_overclaim(evidence):
    audit=audit_legacy_text('通过已测试的敏感度设置并不能证明收敛；不能排除Courant时间步长误差。',collect_facts(evidence))
    assert not audit['findings'] and audit['status']=='UNVERIFIED_LEGACY_TEXT'

def test_negation_in_one_clause_does_not_hide_another_positive_overclaim(evidence):
    audit=audit_legacy_text('这里不证明收敛；另一组结果保证全面收敛。',collect_facts(evidence))
    assert audit['status']=='UNSUPPORTED' and audit['findings']==[{'code':'UNBOUNDED_CONVERGENCE_CLAIM'}]

def test_wire_deduplicates_hashes_without_losing_facts_or_paths(evidence):
    full=collect_facts(evidence);wire=compact_facts(full)
    assert set(wire['facts'])==set(full['facts'])
    assert len(json.dumps(wire))<len(json.dumps(full))
    for ident,value in wire['facts'].items():
        assert wire['artifacts'][value['a']]==full['facts'][ident]['artifact_sha256']
        assert value['p']==full['facts'][ident]['json_pointer']
    assert verify_compact_facts(evidence,wire)==full

@pytest.mark.parametrize('mutation',['hash','pointer','unit','value','omission'])
def test_compact_wire_is_bound_and_cannot_hide_or_change_a_fact(evidence,mutation):
    wire=compact_facts(collect_facts(evidence))
    if mutation=='hash':wire['artifacts']['report.json']='f'*64
    elif mutation=='omission':wire['facts'].pop('base.resolution')
    else:wire['facts']['base.resolution'][{'pointer':'p','unit':'unit','value':'value'}[mutation]]='tampered'
    with pytest.raises(ValueError,match='BINDING'):verify_compact_facts(evidence,wire)
