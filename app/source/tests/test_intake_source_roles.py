"""Source-role recognition must not let examples authorize execution."""
import json
import pytest
from photonguard import workflow_intake as i
from photonguard.novice import TEMPLATE_TEXT, draft, normalize

def prepared(text):
    return i.prepare('roles', normalize(text)[0])

@pytest.mark.parametrize('prefix', ['教学示例：','示例：','已作废的旧记录：','已作废记录：','已撤销记录：','未采纳的建议：','未采纳建议：','否定记录：并非','不是'])
def test_explicit_annotations_do_not_override_or_conflict_with_a_real_value(prefix):
    p=prepared(TEMPLATE_TEXT+'\n'+prefix+'膜厚为0.49 um。')
    result=i.review(p,'mock')
    assert result['confirmable']
    assert result['normalized_response']['fields']['film_thickness']['value']=='300'
    assert len(result['source_annotations'])==1
    assert draft('roles','specified',TEMPLATE_TEXT+'\n'+prefix+'膜厚为0.49 um。')['ready']

@pytest.mark.parametrize('prefix', ['教学示例：','已撤销记录：','未采纳建议：','否定记录：并非'])
def test_excluded_only_citation_cannot_supply_a_missing_actual_parameter(prefix):
    p=prepared(TEMPLATE_TEXT.replace('膜厚为300 nm。','膜厚未知。')+'\n'+prefix+'膜厚为490 nm。')
    response=i.rule_candidate(p['view']);assert response['fields']['film_thickness']['status']=='unknown'
    # A model may return valid JSON but falsely turn the annotated number into fact.
    lines=p['view']['packet']['documents'][0]['lines']
    response['fields']['film_thickness']={'status':'proposed','value':'490','unit':'nm','evidence':[{'document':'requirements','line':len(lines),'quote':lines[-1]}]}
    response.update(review_status='REVIEW_REQUIRED',questions=[],conflicts=[])
    result=i.review(p,'offline',json.dumps(response,ensure_ascii=False))
    assert not result['confirmable'] and any('仍缺实际参数依据' in s for s in result['scope_problems'])

@pytest.mark.parametrize('line', [
    '实测记录（文件名含示例）：膜厚为490 nm。',
    '原记录尚未作废：膜厚为490 nm。',
    '建议之后已经实测：膜厚为490 nm。',
    '教学示例：膜厚为490 nm；实际测量：膜厚为520 nm。',
    '教学示例：膜厚为490 nm，实际测量：膜厚为520 nm。',
    '已作废的旧记录：膜厚为490 nm，同时新的实测膜厚为520 nm。',
])
def test_keywords_or_partial_annotations_cannot_hide_actual_contradictions(line):
    result=i.review(prepared(TEMPLATE_TEXT+'\n'+line),'mock')
    field=result['normalized_response']['fields']['film_thickness']
    assert not result['confirmable'] and field['status']=='conflict' and field['value'] is None
    assert len(field['evidence'])>=2

def test_model_omission_of_real_conflict_remains_blocked():
    p=prepared(TEMPLATE_TEXT+'\n独立实测：膜厚为490 nm。')
    baseline=i.rule_candidate(prepared(TEMPLATE_TEXT)['view'])
    baseline['input_sha256']=p['view']['input_sha256']
    result=i.review(p,'offline',json.dumps(baseline,ensure_ascii=False))
    assert not result['confirmable'] and any('数值表述不一致' in s for s in result['scope_problems'])

def test_incomplete_annotation_grammar_remains_conservative():
    text=TEMPLATE_TEXT+'\n这只是一个关于膜厚为490 nm的例子，详细背景尚未提供。'
    result=i.review(prepared(text),'mock')
    assert not result['confirmable'] and not result['source_annotations']

def test_all_proposed_cannot_return_empty_clarification():
    from photonguard.novice_ai import review
    p=prepared(TEMPLATE_TEXT);response=i.rule_candidate(p['view'])
    response['review_status']='CLARIFICATION_REQUIRED'
    guarded=review(p['view'],json.dumps(response,ensure_ascii=False))
    assert not guarded['accepted'] and guarded['reason_code']=='SEMANTIC_CLARIFICATION_EMPTY'
    assert response['review_status']=='CLARIFICATION_REQUIRED'
