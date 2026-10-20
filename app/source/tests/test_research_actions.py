import copy
import json
from unittest.mock import patch
import pytest
from test_inverse_journeys import store
from photonguard.core import digest
from photonguard.experiments import inverse_models as m, observation_group as ow
from photonguard.experiments import research_actions as ra, inverse_report as report


def record(store,model=m.SLIT):
    # Action-contract fixtures are reproducible, not statistical noise trials.
    # The production simulator still rejects out-of-range noisy reflectance.
    if model==m.FILM:
        with patch('secrets.randbits',return_value=0):
            return ow.create(store,{'model':model,'teaching':True})
    return ow.create(store,{'model':model,'teaching':True})


def item(kind='explain',**kw):
    return {'type':kind,'reason':'结合公开证据核对下一步。','proposal_id':None,'fact_fields':[],'quote':'',**kw}


def payload(s,*items):
    return {'input_binding':ra.binding(s),'actions':list(items or [item()])}


def update(field,value,quote):
    return {'field':field,'value':value,'quote':quote,'correction':False}


def respond(store,monkeypatch,s,text,updates=(),actions=None):
    class Client:
        def complete(self,*args):
            obj={'updates':list(updates),'focus':'measurement'}
            if actions is not None:obj['research_actions']=payload(s,*actions)
            return {'assistant':{'content':json.dumps(obj)}}
    monkeypatch.setattr(store,'_model',lambda *args:Client())
    # Preserve v1 receiver regression separately; v2 product fixtures live in test_research_advice.
    return report.legacy_guidance(store,s,{'text':text,'approve_data':True})


def test_suggestions_bound_to_facts_goal_data_and_result_not_execution(store):
    s=record(store);before=copy.deepcopy(s['inverse_ledger'])
    bundle=ra.validate(s,payload(s,item('inspect_observation'),item('request_calibration')),'')
    assert ra.current(s,bundle) and not bundle['approval'] and not bundle['executed']
    for mutate in [lambda v:v['inverse_settings']['fixed'].update(wavelength_nm=632),
                   lambda v:v.update(research_goal={'target':'width'}),
                   lambda v:v.update(acquisition_constraints={'points':5}),
                   lambda v:v['groups'][0].update(noise={'sigma':2}),
                   lambda v:v.update(inverse_result={'id':'new-result'}),
                   lambda v:v['groups'][0]['dataset'].update(sha256='new-data')]:
        changed=copy.deepcopy(s);mutate(changed);assert not ra.current(changed,bundle)
    assert s['inverse_ledger']==before and not s.get('inverse_plan')


@pytest.mark.parametrize('change',[
    lambda p:p['input_binding'].update(input_revision=999),
    lambda p:p['input_binding'].update(fit_result_id='invented'),
    lambda p:p['actions'][0].update(proposal_id='invented'),
    lambda p:p['actions'][0].update(type='run_solver'),
    lambda p:p['actions'][0].update(fact_fields=['bounds.film_index']),
    lambda p:p['actions'][0].update(quote='not in user text'),
    lambda p:p['actions'][0].update(reason='已经确诊模糊，真实缝宽是20微米'),
    lambda p:p['actions'][0].update(approve=True),
])
def test_research_output_rejects_forged_refs_and_approval(store,change):
    s=record(store);obj=payload(s);change(obj)
    with pytest.raises(ValueError):ra.validate(s,obj,'')


def test_simple_baseline_is_allowed_but_local_winner_cannot_be_renamed(store):
    s=record(store);s['measurement_plan']={'baseline_id':'fixed2','plans':[{'id':'fixed2'},{'id':'medium'}],'sha256':'saved-plan'}
    bundle=ra.validate(s,payload(s,item('choose_baseline',proposal_id='fixed2')),'')
    assert bundle['actions'][0]['type']=='choose_baseline'
    with pytest.raises(ValueError):ra.validate(s,payload(s,item('choose_baseline',proposal_id='medium')),'')
    offline=ra.fallback(s,'固定扫描已经够好，就用简单方案。')
    assert offline['source_kind']=='DETERMINISTIC_FALLBACK' and offline['actions'][0]['proposal_id']=='fixed2'


def test_explicit_catalog_does_not_relabel_legacy_named_local_candidates(store):
    s=record(store)
    s['measurement_plan']={'baseline_id':'baseline','baseline_catalog':[{'id':'baseline','executable':True}],
        'plans':[{'id':'repeat','identity':'LOCAL_CANDIDATE'},{'id':'baseline','identity':'BASELINE'}],'sha256':'saved'}
    assert ra.baseline_ids(s)=={'baseline'}
    with pytest.raises(ValueError):ra.validate(s,payload(s,item('choose_baseline',proposal_id='repeat')),'')
    assert ra.fallback(s,'使用基础方案')['actions'][0]['proposal_id']=='baseline'
    s['measurement_plan']={'baseline_id':None,'baseline_catalog':[{'id':'baseline','executable':False}],
        'plans':[{'id':'repeat','identity':'LOCAL_CANDIDATE'}],'sha256':'unavailable'}
    assert not ra.baseline_ids(s)
    s['measurement_plan']={'plans':[{'id':'repeat'}],'sha256':'legacy'}
    assert ra.baseline_ids(s)=={'repeat'}


def test_missing_plan_and_exhausted_root_stay_suggestions(store):
    s=record(store);budget=copy.deepcopy(s['inverse_ledger']);budget['fit_runs_reserved']=budget['max_fit_runs']
    bundle=ra.validate(s,payload(s,item('refit'),item('propose_followup')),'',ledger=budget)
    assert 'ROOT_BUDGET_EXHAUSTED' in bundle['actions'][0]['required_before_execution']
    assert 'SAVED_EXECUTABLE_PROPOSAL' in bundle['actions'][1]['required_before_execution']
    assert not bundle['executed'] and s['inverse_ledger']['fit_runs_reserved']==0


def test_gaussian_five_opportunities_and_priority_are_source_bound(store,monkeypatch):
    s=record(store,m.GAUSSIAN);before=copy.deepcopy(s['inverse_settings'])
    text='我只有5次测量机会，束腰位置比大小更重要。'
    s=respond(store,monkeypatch,s,text,[update('design.points',5,'5次测量机会'),update('goal.target','waist_position','束腰位置比大小更重要')],[item('compare_acquisition')])
    assert s['inverse_ai']['status']=='ACCEPTED' and s['acquisition_constraints']['points']==5
    assert s['research_goal']['target']=='waist_position' and s['inverse_settings']==before
    assert ra.current(s) and s['research_actions']['input_binding']['facts_sha256']!=digest(ra.state(s))
    assert s['inverse_ledger']['fit_runs_reserved']==0


def test_goal_switch_keeps_previously_declared_tolerances_and_prediction_region(store,monkeypatch):
    s=record(store,m.GAUSSIAN)
    s['research_goal']={'target':'balanced','source':'USER_FORM','tolerances':{'waist_radius_um':.25,'waist_z_mm':2.},'prediction_region_mm':[-50.,150.]}
    before=copy.deepcopy(s['research_goal'])
    s=respond(store,monkeypatch,s,'束腰位置更重要',[update('goal.target','waist_position','束腰位置更重要')])
    assert s['inverse_ai']['status']=='ACCEPTED'
    assert s['research_goal']['target']=='waist_position'
    assert s['research_goal']['tolerances']==before['tolerances']
    assert s['research_goal']['prediction_region_mm']==before['prediction_region_mm']


def test_fact_change_rebind_requires_new_fit_before_comparing(store,monkeypatch):
    s=record(store,m.GAUSSIAN)
    s['inverse_result']={'id':'saved-fit','resources':{'actual_residual_calls':1,'local_optimizations':1},'estimated_parameters':{'waist_radius_um':80.,'waist_z_mm':40.},'warnings':[],'data':[]}
    s['acquisition_constraints']={'points':5}
    original=s['id']
    op=update('fixed.wavelength_nm',632.,'波长632 nm');op['correction']=True
    changed=respond(store,monkeypatch,s,'更正：波长632 nm',[op],[item('compare_acquisition')])
    assert changed['inverse_ai']['status']=='ACCEPTED' and changed['id']!=original
    assert not changed.get('inverse_result') and ra.current(changed)
    action=changed['research_actions']['actions'][0]
    assert action['status']=='NEEDS_REVIEW' and 'FIT_RESULT' in action['required_before_execution']


def test_dark_fringes_prompt_does_not_diagnose_or_modify_facts(store,monkeypatch):
    s=record(store);before=copy.deepcopy(s['inverse_settings'])
    text='拟合曲线贴得很好，但暗纹不够暗，这能说明真实缝宽了吗？'
    s=respond(store,monkeypatch,s,text,actions=[item('inspect_observation',quote='暗纹不够暗'),item('request_calibration')])
    assert s['inverse_ai']['status']=='ACCEPTED' and s['inverse_settings']==before
    assert '不能单独确定真实缝宽' in s['inverse_ai']['text']
    assert ra.fallback(s,text)['actions'][0]['type']=='inspect_observation'


def test_film_catalog_is_exact_and_no_arbitrary_brightness(store,monkeypatch):
    s=record(store,m.FILM);before=copy.deepcopy(s['inverse_settings'])
    text='我只有633、660、780 nm三个光源，帮我区分膜厚候选，不能加新波长。'
    s=respond(store,monkeypatch,s,text,[update('design.wavelengths_nm',[633,660,780],'只有633、660、780 nm三个光源')],[item('compare_acquisition')])
    assert s['inverse_ai']['status']=='ACCEPTED' and s['acquisition_constraints']=={'wavelengths_nm':[633,660,780]}
    assert s['inverse_settings']==before and not s['research_actions']['approval']
    with pytest.raises(ValueError):report.grounded('design.wavelengths_nm',[633,660,700,780],'只有633、660、780 nm三个光源',text)
    with pytest.raises(ValueError):report.grounded('fixed.calibrated_reflectance',True,'只有亮度数据','只有亮度数据')


@pytest.mark.parametrize('field,value,quote',[
    ('fixed.film_index',2.,'薄膜实折射率为2'),
    ('fixed.incident_index',1.,'入射介质折射率为1'),
    ('fixed.substrate_index',1.5,'基底折射率为1.5'),
    ('fixed.incidence_deg',0.,'法向入射'),
    ('fixed.lossless',True,'无损单层'),
    ('fixed.layer_order','incident/film/substrate','入射介质/薄膜/基底'),
    ('fixed.calibrated_reflectance',True,'这是已校准的反射率'),
    ('bounds.thickness_nm',[100.,800.],'厚度100到800 nm'),
    ('bounds.thickness_nm',[100.,800.],'厚度0.1到0.8微米'),
])
def test_known_film_facts_and_finite_thickness_grounding(field,value,quote):
    report.grounded(field,value,quote,quote)


@pytest.mark.parametrize('field,value,quote',[
    ('fixed.film_index',2.,'薄膜折射率拟合为2'),
    ('fixed.film_index',2.,'薄膜折射率2+0.1i'),
    ('fixed.film_index',2.,'基底折射率2'),
    ('fixed.film_index',2.,'薄膜折射率2 nm'),
    ('fixed.film_index',2.,'薄膜折射率2到3'),
    ('fixed.calibrated_reflectance',True,'未校准反射率'),
    ('bounds.thickness_nm',[1,2],'厚度1到2'),
    ('bounds.thickness_nm',[0,1500],'厚度0到1500 nm'),
    ('design.wavelengths_nm',[633,780],'如果只有633、780 nm光源'),
    ('design.wavelengths_nm',[633,780],'只有633、780光源'),
])
def test_film_nl_rejects_unsupported_role_units_calibration(field,value,quote):
    with pytest.raises(ValueError):report.grounded(field,value,quote,quote)


def test_unknown_film_index_fit_field_rejected_atomically(store,monkeypatch):
    s=record(store,m.FILM);before=copy.deepcopy(s)
    s=respond(store,monkeypatch,s,'折射率1到3，厚度100到800 nm。',[update('bounds.thickness_nm',[100,800],'厚度100到800 nm'),update('bounds.film_index',[1,3],'折射率1到3')])
    assert s['inverse_ai']['status']=='NEEDS_REVIEW' and s['inverse_settings']==before['inverse_settings']
    assert s['inverse_ledger']==before['inverse_ledger']


def test_catalog_change_archives_proposal_and_rebind_marks_old_choice(store,monkeypatch):
    s=record(store,m.FILM)
    plan={'plans':[{'id':'wavelength-780'}],'recommended_id':'wavelength-780'};plan['sha256']=digest(plan)
    s['measurement_plan']=plan;s['acquisition_constraints']={'wavelengths_nm':[633,780]};store.save(s)
    s=respond(store,monkeypatch,s,'只有633、660 nm光源',[update('design.wavelengths_nm',[633,660],'只有633、660 nm光源')],[item('propose_followup',proposal_id='wavelength-780')])
    assert not s.get('measurement_plan') and s['measurement_history']==[plan]
    assert s['research_actions']['actions'][0]['status']=='STALE_PROPOSAL' and ra.current(s)


def test_offline_suggestions_are_not_paid_calls_or_fake_live_model(store):
    s=record(store);before=copy.deepcopy(s['inverse_ledger']);count=s['model_calls']
    s=ra.offline(store,s,{'text':'暗纹不够暗'})
    assert s['research_actions']['source_kind']=='DETERMINISTIC_FALLBACK'
    assert s['model_calls']==count and s['inverse_ledger']==before and ra.current(s)


def test_action_reasons_allow_caveats_but_not_extra_film_wavelengths(store):
    s=record(store,m.FILM);s['acquisition_constraints']={'wavelengths_nm':[633,660,780]}
    ra.validate(s,payload(s,item(reason='不能保证唯一，也未确诊原因；不是95%置信区间。')),'')
    ra.validate(s,payload(s,item(reason='应核对强度平均影响，避免把低残差解释为确诊。')),'')
    with pytest.raises(ValueError):ra.validate(s,payload(s,item('propose_followup',reason='补测700 nm以区分候选。')),'')
    ra.validate(s,payload(s,item('propose_followup',reason='补测700 nm以区分候选。')),'现在只有633、700 nm光源')


def test_server_rejects_review_of_rebased_stale_proposal(store,monkeypatch):
    from photonguard.workflow import WorkflowError
    s=record(store,m.FILM)
    plan={'plans':[{'id':'wavelength-780'}],'recommended_id':'wavelength-780'};plan['sha256']=digest(plan)
    s['measurement_plan']=plan;s['acquisition_constraints']={'wavelengths_nm':[633,780]};store.save(s)
    s=respond(store,monkeypatch,s,'只有633、660 nm光源',[update('design.wavelengths_nm',[633,660],'只有633、660 nm光源')],[item('propose_followup',proposal_id='wavelength-780')])
    bundle=s['research_actions'];assert ra.current(s)
    before=copy.deepcopy(s['inverse_ledger'])
    with pytest.raises(WorkflowError):store.action(s['id'],{'type':'inverse_research_validate','expected_revision':s['revision'],'suggestion_sha256':bundle['sha256'],'action_id':bundle['actions'][0]['id']})
    assert store.get(s['id'])['inverse_ledger']==before and not store.get(s['id']).get('research_action_review')


def test_failed_ai_reply_archives_previous_actions_and_old_saved_failure_is_not_current(store,monkeypatch):
    s=record(store)
    s=respond(store,monkeypatch,s,'解释现有结果',actions=[item('explain')]);previous=copy.deepcopy(s['research_actions'])
    assert ra.current(s)
    old_saved=copy.deepcopy(s);old_saved['inverse_ai']['status']='NEEDS_REVIEW'
    assert not ra.current(old_saved)  # Old records need no rewrite to display safely.
    bad=item('explain');bad['correction']=False
    s=respond(store,monkeypatch,s,'解释现有结果',actions=[bad])
    assert s['inverse_ai']['status']=='NEEDS_REVIEW' and not s.get('research_actions')
    assert s['research_actions_history']==[previous]
    s=ra.offline(store,s,{'text':'查看现有资料'})
    assert s['research_actions']['source_kind']=='DETERMINISTIC_FALLBACK' and ra.current(s)
