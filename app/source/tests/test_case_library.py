"""Recipe provenance, actual constraints and exploration accounting. No provider."""
import copy,json,math,threading
from types import SimpleNamespace
import pytest
from photonguard.core import digest
from photonguard.experiments.case_catalog import catalog,search,unsupported_request
from photonguard.experiments.case_adaptation import adapt,from_text,normalize_request
from photonguard.experiments import case_workflow as workflow
from photonguard.experiments.service import ExperimentStore
from photonguard.workflow import WorkflowError

@pytest.mark.parametrize('ident',['F01','F02','F03','F04','D01','D02','D03','D04','G01','G02','G03','G04'])
def test_teaching_recipes_are_executable_and_never_existing_results(ident):
    r=adapt({'case_id':ident},mode='teaching')
    assert r['plan']['candidates'] and r['provenance']['preview_status']=='NOT_COMPUTED'
    assert r['spec']['context_kind']=='teaching'
    assert not r.get('result')

def test_own_parameters_never_inherit_teaching_beam_or_units():
    with pytest.raises(ValueError,match='waist_z_mm'):
        adapt({'case_id':'G02','parameters':{'wavelength_nm':532,'waist_radius_um':420,'screen_distance_mm':100},'values':[100,150],'goal':{'metric':'screen_radius_um','operator':'minimize'}})
    with pytest.raises(ValueError,match='不匹配'):
        adapt({'case_id':'D02','parameters':{'aperture':'single_slit'}})

def test_target_recipe_uses_user_wavelength_and_clips_only_to_explicit_bounds():
    req={'case_id':'D02','parameters':{'wavelength_nm':532,'focal_length_mm':180,'slit_width_um':20,'slit_height_um':100,'relative_phase_rad':0},'bounds':{'min':120,'max':210},'goal':{'metric':'fringe_period_mm','operator':'near','target':.8,'tolerance':.01}}
    r=adapt(req);assert r['provenance']['proposal']['analytic_suggestion_um']==pytest.approx(119.7)
    assert r['provenance']['proposal']['analytic_suggestion_in_range'] is False
    assert all(120<=v<=210 for v in r['spec']['allowed_variables']['slit_separation_um'])
    assert r['spec']['known_parameters']['wavelength_nm']==532
    assert r['provenance']['proposal']['computed_results'] is False

def parent_case(ident='D02'):
    r=adapt({'case_id':ident},mode='teaching');p=r['plan'];winner=copy.deepcopy(p['candidates'][1])
    winner.update(all_checks_passed=True)
    return {'id':'a'*32,'family_id':'a'*32,'domain':p['domain'],'spec':p['spec'],'plan':p,'result':{'plan_sha256':p['sha256'],'candidates':[winner],'winner_id':winner['id']},'library_origin':r['provenance']}

def test_phase_branch_locks_actual_selected_geometry_not_template_default():
    parent=parent_case();r=adapt({'case_id':'D03','goal':{'metric':'central_intensity_ratio','operator':'<=','target':.01}},parent=parent)
    assert r['spec']['known_parameters']['slit_separation_um']==pytest.approx(168.8)
    assert list(r['spec']['allowed_variables'])==['relative_phase_rad']
    assert r['provenance']['selected_result_sha256']==digest(parent['result'])
    with pytest.raises(ValueError,match='不能改动'):
        adapt({'case_id':'D03','parameters':{'wavelength_nm':532},'goal':r['spec']['goal']},parent=parent)

def test_search_scope_and_unsupported_propagation():
    assert search('中心变暗')[0]['id']=='D03'
    assert all(c['domain']=='gaussian' for c in search(domain='gaussian'))
    assert search(domain='film',metric='fringe_period_mm')==[]
    assert unsupported_request('用 Fresnel 计算自由空间传播')
    assert unsupported_request('不使用 Fresnel；研究理想透镜焦平面') is None

def test_same_exploration_reserves_attempts_and_cannot_refill_on_failure(tmp_path):
    owner=SimpleNamespace(root=tmp_path,lock=threading.RLock(),csrf='unit',product_client=None)
    store=ExperimentStore(owner);s=workflow.create(store,{'case_id':'D02','mode':'teaching'})
    workflow.reserve(store,s);root=store.get(s['id'])
    assert root['exploration_ledger']['reserved_fast']==6
    root.update(result=parent_case()['result'],status='FAILED');root['result']['plan_sha256']=root['plan']['sha256'];store.save(root)
    child=store.create({'kind':'specified','text':'明确下一目标'})
    req={'case_id':'D02','bounds':{'min':120,'max':220},'goal':{'metric':'fringe_period_mm','operator':'near','target':.9,'tolerance':.015}}
    child=workflow.apply_plan(store,child,adapt(req,parent=root),root)
    assert child['spec']['resource_budget']['max_fast_evaluations']==18
    workflow.reserve(store,child)
    with pytest.raises(WorkflowError,match='两阶段'):
        workflow.inherit(store,child,store.create({'kind':'specified','text':'第三阶段不能自动补额度'}))
    assert store.get(root['id'])['exploration_ledger']['stages']==2

def test_real_mode_requires_source_quotes_and_never_turns_missing_into_teaching():
    class Client:
        def complete(self,*args):return {'audit':{'status':'ASSISTANT_RETURNED','live_dispatch':False},'assistant':{'content':json.dumps({'request':{'case_id':'G02','parameters':{'waist_radius_um':500},'goal_quote':'想让光斑更小','goal':{'metric':'screen_radius_um','operator':'minimize'},'values':[100,150]},'questions':[]})}}
    result=from_text('想让光斑更小',Client(),'unit')
    assert result['plan'] is None and '出处' in result['questions'][0]

def test_duplicate_bounds_normalization_does_not_infer_unknown_scalar():
    wrapped={'case_id':'D02','bounds':{'slit_separation_um':{'min':120,'max':220}}}
    r,changes=normalize_request(wrapped);assert r['bounds']=={'min':120,'max':220} and changes
    wrapped['bounds']['other']={}
    r,changes=normalize_request(wrapped);assert r['bounds']==wrapped['bounds'] and not changes
    req={'case_id':'D02','parameters':{'slit_separation_um':{'min':120,'max':220}},'bounds':{'min':120,'max':220}}
    r,changes=normalize_request(req);assert r['parameters']=={} and changes
    req['parameters']['slit_separation_um']['min']=100
    r,changes=normalize_request(req);assert isinstance(r['parameters']['slit_separation_um'],dict) and not changes
    req={'case_id':'D03','parameters':{'wavelength_nm':633,'focal_length_mm':199}}
    r,changes=normalize_request(req,parent_case());assert r['parameters']=={'focal_length_mm':199}
