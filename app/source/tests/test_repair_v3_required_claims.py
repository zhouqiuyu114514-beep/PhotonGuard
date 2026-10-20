"""Live v3 must not turn historical prose into executable actions."""
import copy
import pytest
from photonguard import repair_diagnosis as diagnosis


@pytest.fixture
def boundary(monkeypatch):
    candidate={'origin':{'script_import':{'source_locations':{'resolution':{'line':3}}}}}
    table={'facts':{},'facts_sha256':'synthetic-facts'}
    monkeypatch.setattr(diagnosis,'load',lambda _:candidate)
    monkeypatch.setattr(diagnosis,'collect_facts',lambda _:table)
    monkeypatch.setattr(diagnosis,'compact_facts',lambda x:x)
    monkeypatch.setattr(diagnosis,'verify_compact_facts',lambda *args:table)
    base={'observations':{'checks':[{'id':'grid_sensitivity'}]}}
    request=copy.deepcopy(base)
    request.update(prompt=diagnosis.PROMPT,contract='ai-repair-diagnosis-3')
    request['observations'].update(source_locations=candidate['origin']['script_import']['source_locations'],evidence_facts=table)
    calls=[]
    monkeypatch.setattr(diagnosis,'action_to_patch',lambda *args:calls.append(args) or {'fixture':True})
    action={'decision':'propose_patch','changes':[{'path':['numerics','resolution'],'new':160}],
        'rationale':'structured_claims','evidence_ids':['grid_sensitivity'],
        'issues':[{'location_key':'resolution','reason':'structured_claims','evidence_ids':['grid_sensitivity']}]}
    return base,request,action,calls


@pytest.mark.parametrize('decision',['propose_patch','no_change','inconclusive','unsupported'])
def test_live_v3_missing_claims_never_reaches_patch(boundary,decision):
    base,request,action,calls=boundary;action['decision']=decision
    original=copy.deepcopy(action)
    with pytest.raises(ValueError,match='MODEL_ACTION_SCHEMA'):
        diagnosis.validate_model_action('/unused',base,request,action,{})
    assert not calls and action==original


def test_empty_claims_cannot_authorize_patch(boundary):
    base,request,action,calls=boundary;action['claims']=[]
    with pytest.raises(ValueError,match='MODEL_PATCH_WITHOUT_VERIFIED_BASIS'):
        diagnosis.validate_model_action('/unused',base,request,action,{})
    assert not calls


def test_relevant_audited_basis_is_still_required(boundary,monkeypatch):
    base,request,action,calls=boundary;action['claims']=[]
    fact={'claim_type':'measured_fact','operation':'value','value':'FAIL','fact_refs':['check.time_sensitivity.status']}
    monkeypatch.setattr(diagnosis,'explanation_audit',lambda *args:{'accepted':[fact],'rendered':['fixture']})
    with pytest.raises(ValueError,match='MODEL_PATCH_WITHOUT_VERIFIED_BASIS'):
        diagnosis.validate_model_action('/unused',base,request,action,{})
    fact['fact_refs']=['check.grid_sensitivity.status']
    diagnosis.validate_model_action('/unused',base,request,action,{})
    assert len(calls)==1


def test_legacy_explanation_remains_read_only():
    action={'rationale':'historical prose','issues':[]};before=copy.deepcopy(action)
    audit=diagnosis.explanation_audit(action,{'facts':{},'facts_sha256':'synthetic-facts'})
    assert audit['status']=='UNVERIFIED_LEGACY_TEXT' and action==before


@pytest.mark.parametrize('observed_status',['FAIL','PASS'])
def test_reference_values_alone_are_not_repair_basis_and_fail_cannot_be_invented(boundary,observed_status):
    base,request,action,calls=boundary
    checks=[{'id':'reference_pairing','status':observed_status}]
    base['observations']['checks']=checks;request['observations']['checks']=copy.deepcopy(checks)
    locations=request['observations']['source_locations'];locations['workflow.reference_amplitude']=[{'line':3}]
    facts=request['observations']['evidence_facts']['facts']
    facts.update({'check.reference_pairing.reference_amplitude':{'value':.7,'unit':'source_amplitude'},
        'check.reference_pairing.target_amplitude':{'value':1.0,'unit':'source_amplitude'},
        'check.reference_pairing.status':{'value':observed_status,'unit':'status'}})
    action.update(changes=[{'path':['workflow','reference_amplitude'],'new':1.0}],evidence_ids=['reference_pairing'],
        issues=[{'location_key':'workflow.reference_amplitude','reason':'structured_claims','evidence_ids':['reference_pairing']}],
        claims=[{'claim_type':'measured_fact','fact_refs':['check.reference_pairing.reference_amplitude','check.reference_pairing.target_amplitude'],
            'operation':'difference','value':.3,'unit':'source_amplitude'}])
    with pytest.raises(ValueError,match='MODEL_PATCH_WITHOUT_VERIFIED_BASIS'):
        diagnosis.validate_model_action('/unused',base,request,action,{})
    assert not calls
    action['claims'].append({'claim_type':'measured_fact','fact_refs':['check.reference_pairing.status'],'operation':'value','value':'FAIL','unit':'status'})
    if observed_status=='FAIL':
        diagnosis.validate_model_action('/unused',base,request,action,{})
        assert len(calls)==1
    else:
        with pytest.raises(ValueError,match='MODEL_PATCH_WITHOUT_VERIFIED_BASIS'):
            diagnosis.validate_model_action('/unused',base,request,action,{})
        assert not calls
