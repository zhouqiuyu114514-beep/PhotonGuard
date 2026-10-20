"""Recovery must retain case selection, parent facts and shared budgets."""
import copy,json,threading,hashlib
from types import SimpleNamespace
import pytest
from photonguard.experiments import case_workflow as flow
from photonguard.experiments.case_adaptation import adapt
from photonguard.experiments.case_adaptation import ground_goal_operator,normalize_request
from photonguard.experiments.case_catalog import unsupported_request
from photonguard.experiments.service import ExperimentStore
from photonguard.workflow import WorkflowError

class Client:
    def preflight(self):pass

def store_at(path):
    return ExperimentStore(SimpleNamespace(root=path,lock=threading.RLock(),csrf='test',product_client=Client()))

def completed(store):
    s=flow.create(store,{'case_id':'D02','mode':'teaching'});flow.reserve(store,s)
    winner=copy.deepcopy(s['plan']['candidates'][1]);winner['all_checks_passed']=True
    s.update(status='COMPLETED',result={'plan_sha256':s['plan']['sha256'],'winner_id':winner['id'],'candidates':[winner]})
    store.save(s);p=store.folder(s['id'])/'execution';p.mkdir();raw=json.dumps(s['result']).encode();(p/'result.json').write_bytes(raw)
    (p/'manifest.json').write_text(json.dumps({'files':{'result.json':hashlib.sha256(raw).hexdigest()}}))
    flow.settle_output(store,s);return s

def act(store,s,kind,**kw):return store.action(s['id'],{'type':kind,'expected_revision':s['revision'],**kw})

def test_missing_case_facts_supplement_uses_same_case_route(tmp_path,monkeypatch):
    store=store_at(tmp_path);seen=[]
    def model(text,*args,**kw):
        seen.append((text,kw))
        return {'plan':None,'questions':['束腰位置仍未知']}
    monkeypatch.setattr(flow,'from_text',model)
    s=store.create({'kind':'specified','text':'真实光束，束腰位置未知'})
    s=act(store,s,'library_plan',mode='live',approve_data=True,case_id='G02')
    s=act(store,s,'supplement',text='束腰位置为-30 mm',mode='live',approve_data=True)
    assert len(seen)==2 and seen[1][1]['case_id']=='G02'
    assert seen[1][0].startswith('真实光束') and seen[1][0].endswith('-30 mm')
    assert seen[1][1]['mode']=='specified' and s['result'] is None

def test_failed_exploration_recovery_keeps_parent_and_budget(tmp_path,monkeypatch):
    store=store_at(tmp_path);parent=completed(store)
    monkeypatch.setattr(flow,'from_text',lambda *a,**kw:{'plan':None,'questions':['请给出范围']})
    child=act(store,parent,'explore_case',mode='live',approve_data=True,new_exploration=True,case_id='D02',text='目标改成0.9 mm')
    assert child['library_context']['parent_id']==parent['id']
    def model(text,*args,**kw):
        assert kw['parent']['id']==parent['id'] and kw['case_id']=='D02'
        return adapt({'case_id':'D02','goal':{'metric':'fringe_period_mm','operator':'near','target':.9,'tolerance':.015},'bounds':{'min':120,'max':220}},parent=kw['parent'])
    monkeypatch.setattr(flow,'from_text',model)
    recovered=act(store,child,'supplement',text='缝距范围120到220 um',mode='live',approve_data=True)
    assert recovered['id']==child['id'] and recovered['status']=='PLANNED'
    assert recovered['exploration_root']==parent['id']
    assert recovered['spec']['resource_budget']['max_fast_evaluations']==18
    assert recovered['spec']['known_parameters']['wavelength_nm']==633
    assert store.get(parent['id'])['result']==parent['result']
    flow.reserve(store,recovered)
    assert store.get(parent['id'])['exploration_ledger']['stages']==2

def test_existing_revision_cannot_switch_to_case_route_and_escape_catalog(tmp_path):
    store=store_at(tmp_path);parent=completed(store)
    child=act(store,parent,'revise_goal',goal={'metric':'fringe_period_mm','operator':'near','target':.9,'tolerance':.015})
    with pytest.raises(WorkflowError,match='原候选目录'):
        act(store,child,'library_plan',request={'case_id':'D02','bounds':{'min':500,'max':600}})
    assert store.get(child['id'])==child

def test_recovery_rejects_changed_parent_result(tmp_path,monkeypatch):
    store=store_at(tmp_path);parent=completed(store)
    monkeypatch.setattr(flow,'from_text',lambda *a,**kw:{'plan':None,'questions':['缺项']})
    child=act(store,parent,'explore_case',mode='live',approve_data=True,new_exploration=True,text='修改目标')
    child['library_context']['parent_result_sha256']='0'*64;store.save(child)
    with pytest.raises(WorkflowError,match='来源结果已改变'):
        act(store,child,'library_plan',mode='live',approve_data=True)

def test_explicit_parameter_form_recovers_child_without_paid_call(tmp_path,monkeypatch):
    store=store_at(tmp_path);parent=completed(store)
    monkeypatch.setattr(flow,'from_text',lambda *a,**kw:{'plan':None,'questions':['缺项']})
    child=act(store,parent,'explore_case',mode='live',approve_data=True,new_exploration=True,case_id='D02',text='修改目标')
    calls=store.get(parent['id'])['family_model_calls']
    def forbidden(*a,**kw):pytest.fail('Direct parameter form must not call AI')
    monkeypatch.setattr(flow,'from_text',forbidden)
    req={'case_id':'D02','goal':{'metric':'fringe_period_mm','operator':'near','target':.87,'tolerance':.02},'bounds':{'min':135,'max':210}}
    child=act(store,child,'library_plan',request=req)
    assert child['status']=='PLANNED' and child['exploration_root']==parent['id'] and child['result'] is None
    assert child['spec']['resource_budget']['max_fast_evaluations']==18
    assert store.get(parent['id'])['family_model_calls']==calls

def test_supplements_are_separate_current_input_and_original_quotes_remain_valid():
    from photonguard.experiments.case_adaptation import from_text
    class Capture:
        def complete(self,ident,payload):
            data=json.loads(payload['messages'][1]['content'])
            assert data['facts']=='束腰未知' and data['current_user_update']=='束腰位置-35 mm'
            assert data['supplements_in_time_order']==['束腰位置-35 mm']
            return {'audit':{'status':'ASSISTANT_RETURNED','live_dispatch':False},'assistant':{'content':'{"request":null,"questions":["其他资料缺失"]}'}}
    r=from_text('束腰未知\n\n补充资料：\n束腰位置-35 mm',Capture(),'test')
    assert r['plan'] is None

def test_recipe_reference_can_use_explicit_bounds_source_but_never_unquoted_values():
    from photonguard.experiments.case_adaptation import from_text
    from test_case_library import parent_case
    req={'case_id':'D02','parameters':{},'goal':{'metric':'fringe_period_mm','operator':'near','target':.87,'tolerance':.02},'bounds':{'min':135,'max':210},'goal_quote':'周期接近0.87 mm，容差0.02 mm','recipe_quote':'仅改变缝距','parameter_sources':{'bounds':{'quote':'范围135到210 um','unit':'um'}}}
    class Reply:
        def complete(self,*a):return {'audit':{'status':'ASSISTANT_RETURNED','live_dispatch':False},'assistant':{'content':json.dumps({'request':req,'questions':[]})}}
    text='周期接近0.87 mm，容差0.02 mm；仅改变缝距；范围135到210 um'
    r=from_text(text,Reply(),'test',parent=parent_case())
    assert r['plan'] and r['provenance']['request']['recipe_quote']=='范围135到210 um'
    req['bounds']['min']=134
    r=from_text(text,Reply(),'test',parent=parent_case())
    assert r['plan'] is None

@pytest.mark.parametrize('text',['不要套教学值，请使用Fresnel传播','不使用 Fresnel，但要高NA模型','不要套默认参数并用Fresnel','不要换成焦平面，需要自由空间衍射传播'])
def test_unrelated_negative_clause_does_not_hide_unsupported_model(text):
    assert unsupported_request(text)

@pytest.mark.parametrize('text',['不用Fresnel，只做理想焦平面','不使用自由空间Fresnel','非自由空间Fresnel；使用薄透镜','without Fresnel; ideal lens'])
def test_explicitly_excluded_method_is_not_positive_request(text):
    assert unsupported_request(text) is None

def test_live_reported_wrong_goal_cannot_become_executable():
    with pytest.raises(ValueError,match='比较方式'):
        ground_goal_operator({'metric':'screen_radius_um','operator':'maximize','target':70},'希望屏幕1/e²半径不超过70 um')
    ground_goal_operator({'operator':'<=','target':70},'希望屏幕1/e²半径不超过70 um')
    ground_goal_operator({'operator':'maximize'},'反射率最大')
    with pytest.raises(ValueError,match='阈值'):
        ground_goal_operator({'operator':'maximize','target':70},'反射率最大')
    r,changes=normalize_request({'case_id':'G02','values':{'focal_length_mm':[100,120,160]}})
    assert r['values']==[100,120,160] and changes
    r,changes=normalize_request({'case_id':'G02','values':{'waist_z_mm':[0,30]}})
    assert isinstance(r['values'],dict) and not changes
