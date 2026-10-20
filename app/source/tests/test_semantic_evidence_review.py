import copy
import pytest
from photonguard.experiments.fact_state import seed
from photonguard.experiments.evidence_review import checked,fit_numerical_defaults
from photonguard.experiments.dialogue_update import update

def fixture(text='这两条开口横向各20 μm。',value=20):
    b={'field':'parameters.slit_width_um','value':value,'quote':'20 μm','context':text,'assertion':True,'correction':False}
    return seed('D02'),text,{'patches':[{'field':b['field'],'value':value}]},{'bindings':[b],'nonfacts':[]}

def test_contextual_binding_has_original_offsets():
    s,t,m,r=fixture();o,c,n=checked(s,t,'e',m,r)
    assert o[0]['value']==20 and t[o[0]['evidence'][0]['start']:o[0]['evidence'][0]['end']]=='20 μm'

@pytest.mark.parametrize('change',[{'quote':'22 μm'},{'context':'假造原句20 μm'},{'value':200},{'assertion':False},{'field':'parameters.slit_height_um'}])
def test_forged_or_disagreed_evidence_not_accepted(change):
    s,t,m,r=fixture();r['bindings'][0].update(change);assert not checked(s,t,'e',m,r)[0]

@pytest.mark.parametrize('prefix',['如果获准，','待核对：','可能','不是','尚未确认：'])
def test_conditional_negated_unconfirmed_values_not_accepted(prefix):
    s,t,m,r=fixture(prefix+'这两条开口横向各20 μm。');assert not checked(s,t,'e',m,r)[0]

def test_conversion_checked_not_trusted():
    s,t,m,r=fixture('开口横向各0.02 mm。');r['bindings'][0].update(quote='0.02 mm');assert checked(s,t,'e',m,r)[0][0]['value']==20

def test_unsupported_compute_authorization_cannot_be_semantic():
    s,t,m,r=fixture('允许独立验证。',False);m['patches'][0]['field']='execution.fast_only';r['bindings'][0].update(field='execution.fast_only',quote=t);assert not checked(s,t,'e',m,r)[0]

def test_context_does_not_hide_other_numeric_constraints():
    s,t,m,r=fixture('开口横向各20 μm，另一个条件777 μm。');o,c,n=checked(s,t,'e',m,r)
    assert not any(a<=t.index('777')<b for a,b in c)

def test_presentation_cannot_hide_physics():
    for t in ['如果达标，焦距改为200 mm','加入吸收','偏振条件不变']:
        assert not checked(seed('D02'),t,'e',{'patches':[]},{'nonfacts':[{'quote':t,'kind':'presentation'}]})[1]

def test_unknown_keeps_previous_fact_and_requires_review():
    s,t,m,r=fixture('待核对：这两条开口横向各20 μm。')
    out=update(s,t,'e',model_obj=m,evidence_review=r)
    assert out['issues'] and 'parameters.slit_width_um' not in out['facts']

def test_locked_fact_cannot_be_changed_by_semantic_agreement():
    s,t,m,r=fixture();s['facts']['parameters.slit_width_um']={'value':30,'status':'resolved','locked':True,'source_kind':'parent_result','evidence':[],'support_events':[],'fact_id':'old'}
    out=update(s,t,'e',model_obj=m,evidence_review=r)
    assert out['facts']['parameters.slit_width_um']['status']=='conflict'
    assert out['facts']['parameters.slit_width_um']['value']==30

def test_default_window_fit_and_explicit_window_preserved():
    s=seed('D02');s['events']=[{}]
    for k,v in [('slit_width_um',20),('slit_height_um',400)]:s['facts']['parameters.'+k]={'value':v,'status':'resolved','source_kind':'user_text'}
    s['facts']['recipe.max']={'value':300,'status':'resolved','source_kind':'user_text'}
    out=fit_numerical_defaults(copy.deepcopy(s));assert out['facts']['parameters.window_mm']['value']==.5
    s['facts']['parameters.window_mm']['source_kind']='user_text';assert fit_numerical_defaults(s)['facts']['parameters.window_mm']['value']==.4


def test_shared_units_and_coordinated_scalars():
    s,t,m,r=fixture('宽和高分别为20、400 μm。')
    r['bindings'][0]['quote']='20、400 μm'
    assert checked(s,t,'e',m,r)[0][0]['value']==20

def test_dimensionless_value_does_not_inherit_neighbor_wavelength_unit():
    s=seed('F02');t='设计波长850 nm，高低材料分别2.2和1.46。'
    m={'patches':[{'field':'parameters.material_n_high','value':2.2}]}
    r={'bindings':[{'field':'parameters.material_n_high','value':2.2,'quote':'2.2','context':t,'assertion':True}]}
    assert checked(s,t,'e',m,r)[0][0]['value']==2.2

def test_local_field_evidence_blocks_cross_field_borrowing():
    s=seed('G01');t='屏幕距离120 mm。'
    m={'patches':[{'field':'parameters.focal_length_mm','value':120}]}
    r={'bindings':[{'field':'parameters.focal_length_mm','value':120,'quote':'120 mm','context':t,'assertion':True}]}
    assert not checked(s,t,'e',m,r)[0]

def test_window_adjustment_undo_and_non_geometry_recipe():
    from photonguard.experiments import fact_state as fs
    s=update(seed('D02'),'缝宽20 um，缝高400 um，缝距范围100到300 um','a')
    assert s['facts']['parameters.window_mm']['value']==.5
    assert fs.undo(s,'u')['facts']['parameters.window_mm']['value']==.4
    s=update(seed('D04','teaching'),'波长目录500、600、700 nm','a')
    assert s['facts']['parameters.window_mm']['value']==.4


def test_model_echoes_raw_catalog_unit_program_keeps_source_conversion():
    s=update(seed('G02'),'焦距候选8、10、12、16 cm','a',model_obj={'patches':[{'field':'recipe.values','value':[8,10,12,16],'quote':'焦距候选8、10、12、16 cm'}]})
    assert s['facts']['recipe.values']['value']==[80,100,120,160] and not s['issues']
    s=update(seed('G02'),'焦距候选8、10、12、16 cm','a',model_obj={'patches':[{'field':'recipe.values','value':[8,10,12,18],'quote':'焦距候选8、10、12、16 cm'}]})
    assert s['issues']


def test_numeric_quote_is_not_substring_of_another_number():
    s=seed('G02');t='腰在透镜前20 mm，屏在透镜后120 mm。'
    m={'patches':[{'field':'parameters.waist_z_mm','value':-20}]}
    r={'bindings':[{'field':'parameters.waist_z_mm','value':-20,'quote':'20 mm','context':t,'assertion':True}]}
    o,_,_=checked(s,t,'e',m,r);assert o[0]['value']==-20
    assert o[0]['evidence'][0]['start']==t.index('20 mm')


@pytest.mark.parametrize('omitted_in',[1,2])
def test_single_bounded_completeness_read_counts_actual_calls(tmp_path,omitted_in):
    import json,threading
    from types import SimpleNamespace
    from photonguard.experiments.service import ExperimentStore
    text='这两条开口横向各20 μm。'
    binding={'field':'parameters.slit_width_um','value':20,'quote':'20 μm','context':text,'assertion':True}
    answers=[{'case_id':'D02','patches':[] if omitted_in==1 else [{'field':binding['field'],'value':20,'quote':'20 μm'}],'questions':[]},
             {'bindings':[] if omitted_in==2 else [binding],'nonfacts':[]},
             {'bindings':[binding],'nonfacts':[]}]
    class Client:
        calls=0
        def preflight(self):pass
        def complete(self,ident,payload):
            self.calls+=1
            return {'assistant':{'content':json.dumps(answers[self.calls-1])},'audit':{'live_dispatch':False,'status':'ASSISTANT_RETURNED'}}
    client=Client();store=ExperimentStore(SimpleNamespace(root=tmp_path,lock=threading.RLock(),csrf='test',product_client=client))
    s=store.create({'kind':'specified','text':text})
    s=store.action(s['id'],{'type':'plan','expected_revision':s['revision'],'session_version':2,'mode':'live','force_model':True,'approve_data':True})
    assert client.calls==3 and s['model_calls']==3
    assert s['fact_state']['facts']['parameters.slit_width_um']['value']==20
    assert s['status']=='NEEDS_INFORMATION'  # remaining physics was never invented


def test_live_followup_uses_same_contextual_binding_and_preserves_parent(tmp_path):
    import json
    from test_case_recovery import store_at,act,completed
    from photonguard.experiments import fact_state as fs
    store=store_at(tmp_path);parent=completed(store)
    parent['fact_state']=fs.seed('D02','teaching');parent['session_version']=2;store.save(parent)
    text='条纹间距改为0.80 mm，允许上下偏差0.03 mm。'
    patches=[{'field':'goal.metric','value':'fringe_period_mm','quote':'条纹间距'},{'field':'goal.operator','value':'near','quote':'改为0.80 mm'},{'field':'goal.target','value':.8,'quote':'0.80 mm'},{'field':'goal.tolerance','value':.03,'quote':'0.03 mm'}]
    answers=[{'case_id':'D02','patches':patches,'questions':[]},{'bindings':[{**p,'context':text,'assertion':True,'correction':True} for p in patches],'nonfacts':[]},{'action':'stop'}]
    class Client:
        calls=0
        def preflight(self):pass
        def complete(self,ident,payload):
            self.calls+=1;return {'assistant':{'content':json.dumps(answers[self.calls-1])},'audit':{'live_dispatch':False,'status':'ASSISTANT_RETURNED'}}
    client=Client();store.owner.product_client=client
    child=act(store,parent,'session_ai',text=text,approve_data=True)
    assert child['status']=='PLANNED' and not child['questions'],child.get('session_issue')
    assert child['spec']['goal']['tolerance']==.03 and child['spec']['goal']['target']==.8
    assert child['spec']['known_parameters']==parent['spec']['known_parameters']
    assert store.get(parent['id'])['result']==parent['result']
    assert client.calls==3 and not child.get('result')


def test_goal_change_keeps_derived_candidate_baseline_and_catalog():
    from photonguard.experiments.dialogue_update import compile_case_plan,compile_goal_plan
    s=update(seed('D02'),'波长520 nm，焦距200 mm，缝宽20 um，缝高400 um，相位差0 rad，缝距范围100到300 um。条纹周期接近0.65 mm，容差0.025 mm。只做快速计算。','a')
    parent=compile_case_plan(s);parent['result']={'proof':'unit test, not computed'}
    changed=update(s,'条纹周期改为0.8 mm，容差改为0.03 mm。','b')
    r=compile_goal_plan(changed,parent)
    assert r['spec']['known_parameters']==parent['spec']['known_parameters']
    assert r['spec']['allowed_variables']==parent['spec']['allowed_variables']
    assert r['spec']['goal']['target']==.8
