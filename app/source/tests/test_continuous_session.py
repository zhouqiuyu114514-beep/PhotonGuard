import copy,json
import pytest
from photonguard.experiments import fact_state as fs
from photonguard.experiments.dialogue_update import update,compile_case_plan
from photonguard.experiments.action_protocol import decode
from photonguard.experiments.case_catalog import catalog,get_case
from photonguard.experiments.case_workflow import create
from test_case_recovery import store_at,act,completed

GAUSSIAN='波长780 nm，束腰半径480 um，屏幕固定在透镜后120 mm。只比较焦距100、120、160 mm，希望屏幕1/e²半径不超过70 um。束腰位置尚未知。'

def test_short_gaussian_and_stale_model_question():
    s=update(fs.seed('G02'),GAUSSIAN,'one')
    assert [q['fields'] for q in s['questions']]==[['parameters.waist_z_mm']]
    s=update(s,'35 mm在透镜前','two',model_obj={'patches':[],'questions':['请提供束腰位置']})
    r=compile_case_plan(s)
    assert r['spec']['known_parameters']['waist_z_mm']==-35
    assert r['spec']['goal']['operator']=='<='
    assert s['events'][-1]['interpretation_notes'][0]['kind']=='STALE_QUESTION'
    assert s['facts']['parameters.waist_z_mm']['evidence'][0]['question_ref']

def test_wrong_field_model_patch_cannot_supply_focal_length():
    s=update(fs.seed('G01'),'波长780 nm，束腰半径480 um，束腰位置-35 mm，焦距未知，屏幕在透镜后120 mm。屏幕半径不超过70 um。','one',model_obj={'patches':[{'field':'parameters.focal_length_mm','value':120,'quote':'屏幕在透镜后120 mm'}]})
    assert s['facts']['parameters.focal_length_mm']['status']=='unknown'
    assert s['issues'][0]['kind']=='SOURCE_UNRESOLVED'
    assert compile_case_plan(s)['plan'] is None

def test_goal_operator_is_local_to_metric():
    s=update(fs.seed('G02'),GAUSSIAN+'最小焦距100 mm，屏幕半径不超过70 um。','one')
    assert s['facts']['goal.operator']['value']=='<='
    assert 'parameters.focal_length_mm' not in s['facts']

def test_conflict_correction_equivalence_undo_and_stale():
    s=update(fs.seed('G01'),'波长633 nm','one')
    t=update(s,'波长0.633 um','two');assert t['facts']['parameters.wavelength_nm']['status']=='resolved'
    t=update(t,'波长780 nm','three');assert t['facts']['parameters.wavelength_nm']['status']=='conflict'
    t=update(t,'更正波长为780 nm','four');assert t['facts']['parameters.wavelength_nm']['value']==780
    t=fs.undo(t,'undo');assert t['facts']['parameters.wavelength_nm']['status']=='conflict'
    assert fs.undo(t,'undo')==t
    with pytest.raises(ValueError,match='迟到'):fs.apply(t,'late','波长532 nm',[],base_revision=0)
    e=t['events'][0];assert fs.apply(t,'one','波长633 nm',e['operations'],base_revision=0)==t

def test_parent_range_unique_question_same_id_and_budget(tmp_path):
    store=store_at(tmp_path);p=completed(store)
    c=act(store,p,'explore_case',session_version=2,new_exploration=True,case_id='D02',text='条纹周期改成0.87 mm，绝对容差0.02 mm，缝距范围未知。')
    assert len(c['questions'])==1,c['questions']
    c=act(store,c,'supplement',text='135到210微米',event_id='range')
    assert c['status']=='PLANNED',c.get('questions')
    assert c['spec']['resource_budget']['max_fast_evaluations']==18
    assert c['exploration_root']==p['id']
    assert c['library_origin']['request']['bounds']=={'min':135,'max':210}
    repeated=store.action(c['id'],{'type':'supplement','expected_revision':0,'text':'135到210微米','event_id':'range'})
    assert repeated==c
    c=act(store,c,'fact_update',text='更正波长780 nm')
    assert c['fact_state']['facts']['parameters.wavelength_nm']['locked']
    assert c['fact_state']['facts']['parameters.wavelength_nm']['status']=='conflict'
    assert c['plan'] is None

def test_wrong_width_range_not_separation():
    s=update(fs.seed('D02'),'缝宽范围135到210 um','one',model_obj={'patches':[{'field':'recipe.min','value':135,'quote':'缝宽范围135到210 um'}]})
    assert 'recipe.min' not in s['facts'] and s['issues']

@pytest.mark.parametrize('item',catalog(),ids=lambda x:x['id'])
def test_twelve_cases_compile_from_explicit_teaching_and_form(item):
    state=fs.seed(item['id'],'teaching');assert compile_case_plan(state)['plan']
    case=get_case(item['id']);r={'case_id':case['id'],**case['teaching']}
    state=update(fs.seed(item['id']),'表单','one',request=r)
    assert compile_case_plan(state)['plan']

@pytest.mark.parametrize('text',['如果波长780 nm','不要采用波长780 nm','波长未知','波长不是780 nm','波长780 nm但未核对','如果波长780 nm，焦距100 mm'])
def test_conditional_negated_unknown_never_resolved(text):
    s=update(fs.seed('G01'),text,'one')
    assert s['facts'].get('parameters.wavelength_nm',{}).get('status')!='resolved'

def test_protocol_never_invents_type_only_action():
    with pytest.raises(ValueError):decode('{"type":"json_object"}')
    a,n=decode('```json\n{"type":"json_object","action":"stop"}\n```',{'action'})
    assert a=={'action':'stop'} and len(n)==2

def test_ambiguous_bare_number_does_not_fill_multiple_questions():
    s=update(fs.seed('G01'),'35','one');assert not s['facts'] or all(v['source_kind']!='user_text' for v in s['facts'].values())

def test_centimeters_and_explicit_correction_with_single_previous_focus():
    s=update(fs.seed('G01'),'束腰位置-35 mm','one')
    s=update(s,'-3.5 cm','two');assert s['facts']['parameters.waist_z_mm']['status']=='resolved'
    s=update(fs.seed('G01'),'焦距100 mm','one')
    s=update(s,'刚才写错，以120 mm为准','two');assert s['facts']['parameters.focal_length_mm']['value']==120

def test_ascii_comma_catalog_and_positive_dash_range():
    s=update(fs.seed('G02'),'只比较焦距100,120,160 mm','one')
    assert s['facts']['recipe.values']['value']==[100,120,160]
    s=update(fs.seed('D02'),'缝距范围135-210 um','one')
    assert s['facts']['recipe.max']['value']==210

def test_unsupported_update_invalidates_old_draft_plan(tmp_path):
    store=store_at(tmp_path)
    s=create(store,{'case_id':'G02','mode':'teaching','session_version':2})
    s=act(store,s,'fact_update',text='把它用于真实三维全矢量器件设计')
    assert s['plan'] is None and s['session_issue']['kind']=='UNSUPPORTED_SCOPE'

def test_schema_failure_is_not_reported_as_missing_user_facts(tmp_path):
    from test_experiment_service import FakeClient
    store=store_at(tmp_path);store.owner.product_client=FakeClient({'type':'json_object'})
    s=create(store,{'case_id':'G02','mode':'teaching','session_version':2})
    s=act(store,s,'fact_update',text='确认上述已知条件',mode='live',approve_data=True,force_model=True)
    assert s['status']=='NEEDS_REVIEW' and not s['questions']
    assert s['session_issue']['kind']=='MODEL_OUTPUT_INVALID'
    saved=copy.deepcopy(s['fact_state']['facts']);s=act(store,s,'undo_fact')
    assert s['status']=='PLANNED' and s['fact_state']['facts']==saved

def test_bare_public_field_normalization_preserves_semantic_guard():
    s=update(fs.seed('G01'),'屏幕在透镜后120 mm，焦距未知','one',model_obj={'patches':[{'field':'focal_length_mm','value':120,'quote':'屏幕在透镜后120 mm'}]})
    assert s['issues'] and s['facts']['parameters.focal_length_mm']['status']=='unknown'
    s=update(fs.seed('G01'),'焦距120 mm','one',model_obj={'patches':[{'field':'focal_length_mm','value':120,'quote':'焦距120 mm'}]})
    assert not s['issues'] and s['events'][0]['interpretation_notes'][0]['kind']=='PUBLIC_PARAMETER_NAMESPACE_COMPLETED'

def test_retract_and_undo_preserve_history():
    s=update(fs.seed('G01'),'焦距100 mm','one');old=copy.deepcopy(s['events'])
    t=update(s,'撤回焦距，待重新测量','two')
    assert t['facts']['parameters.focal_length_mm']['status']=='retracted'
    t=fs.undo(t,'undo');assert t['facts']==s['facts'] and t['events'][:1]==old

def test_report_metadata_aliases_and_conflict_base_are_not_physics_errors():
    from photonguard.experiments.action_protocol import check_report
    s=update(fs.seed('G01'),'焦距100 mm','one');s=update(s,'焦距120 mm','two')
    c=get_case('G01')
    report=check_report({'action':'ask','fields':['focal_length_mm'],'facts':{'focal_length_mm':100,'recipe.method':'single','metrics':c['metrics']}},s,c)
    assert report['gate_pass'] and report['fields']==['parameters.focal_length_mm']
    assert compile_case_plan(s)['plan'] is None
    report=check_report({'action':'compute','facts':{'focal_length_mm':100}},s,c)
    assert not report['gate_pass'] and report['value_errors']

def test_scorer_does_not_award_all_refusals():
    from photonguard.experiments.session_study import score
    assert score([{'structure_correct':True,'action':'stop','expected_action':False,'tool_ok':True}])['end_to_end'] is False

def test_film_reuse_requires_actual_sample_without_verification_promotion(tmp_path,monkeypatch):
    from test_experiment_service import ImmediateThread
    from photonguard.experiments import service
    monkeypatch.setattr(service.threading,'Thread',ImmediateThread)
    store=store_at(tmp_path);store.owner.allow_workers=True
    s=create(store,{'case_id':'F04','mode':'teaching','session_version':2})
    act(store,s,'run',approve=True,plan_sha256=s['plan']['sha256']);s=store.get(s['id'])
    assert s['status']=='COMPLETED',s.get('error')
    wave=s['result']['candidates'][0]['data']['wavelengths_um'][1]
    goal={**s['spec']['goal'],'wavelength_um':wave}
    reused=act(store,s,'revise_goal',goal=goal)
    assert reused['result']['resources']['fast_evaluations']==0
    assert reused['reuse']['verification_promoted'] is False
    store.verified_case(reused['id'])
    goal['wavelength_um']=.634123
    fresh=act(store,store.get(s['id']),'revise_goal',goal=goal)
    assert fresh['status']=='PLANNED' and not fresh.get('result')
