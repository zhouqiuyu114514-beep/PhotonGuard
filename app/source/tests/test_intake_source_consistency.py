"""Contradictory prose cannot silently authorize a numerical task."""
import json
import pytest
from photonguard import workflow_intake as intake
from photonguard.novice import TEMPLATE_TEXT, draft

@pytest.mark.parametrize('extra', [
    '另一份独立资料写：膜厚为490 nm。两份尚未核对，请保留冲突。',
    '测量记录：膜层折射率为2.4。',
    '附注中入射角为12 deg，需要核对。',
    '另一组真空波长上界为1.9 um。',
    '旧版等波长采样点数为31，尚未核对。',
])
def test_embedded_conflicting_assertions_block_rule_and_model(extra):
    prepared=intake.prepare('prose', TEMPLATE_TEXT+'\n'+extra)
    rule=intake.review(prepared,'mock')
    assert not rule['confirmable']
    assert any(f['status']=='conflict' for f in rule['normalized_response']['fields'].values())
    raw=json.dumps(intake.rule_candidate(prepared['view']),ensure_ascii=False)
    model=intake.review(prepared,'offline',raw)
    assert not model['confirmable']
    ui=draft('prose','specified',prepared['source_text'])
    assert not ui['ready']
    raw_ui=json.dumps(intake.rule_candidate(ui['intake']['view']),ensure_ascii=False)
    reviewed_ui=intake.apply(ui['intake'],{'type':'intake-review','mode':'offline','response_text':raw_ui})
    assert not draft('prose','specified',prepared['source_text'],reviewed_intake=reviewed_ui)['ready']

def test_equivalent_embedded_units_do_not_create_a_conflict():
    prepared=intake.prepare('same',TEMPLATE_TEXT+'\n测量记录：膜厚为0.3 um。')
    assert intake.review(prepared,'mock')['confirmable']

def test_conflict_response_preserves_both_sources_without_a_proposed_value():
    extra='另一份资料：膜厚为490 nm。'
    prepared=intake.prepare('conflict',TEMPLATE_TEXT+'\n'+extra)
    response=intake.rule_candidate(prepared['view']);field=response['fields']['film_thickness']
    field.update(status='conflict',value=None,unit=None)
    assert len(field['evidence'])==2
    response.update(review_status='CLARIFICATION_REQUIRED',conflicts=['film_thickness'],questions=[{'targets':['film_thickness'],'text':'请核对两份膜厚资料。'}])
    reviewed=intake.review(prepared,'offline',json.dumps(response,ensure_ascii=False))
    assert not reviewed['confirmable']
    assert reviewed['normalized_response']['fields']['film_thickness']['status']=='conflict'
    assert not any('数值表述不一致' in p for p in reviewed['scope_problems'])

def test_nonfactual_number_cannot_be_promoted_by_the_consistency_check():
    text=TEMPLATE_TEXT.replace('膜厚为300 nm。','膜厚待测。')+'\n建议：膜厚为490 nm。'
    reviewed=intake.review(intake.prepare('suggestion',text),'mock')
    assert reviewed['normalized_response']['fields']['film_thickness']['value'] is None
    assert not reviewed['confirmable']

def test_explicit_single_example_does_not_change_the_fact():
    reviewed=intake.review(intake.prepare('example',TEMPLATE_TEXT+'\n示例：膜厚为490 nm。'),'mock')
    assert reviewed['confirmable']
    assert reviewed['source_annotations'][0]['reason']=='教学示例'
    assert reviewed['normalized_response']['fields']['film_thickness']['value']=='300'
