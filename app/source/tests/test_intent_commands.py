import copy
import pytest
from photonguard.experiments import fact_state as fs
from photonguard.experiments.dialogue_update import update,compile_case_plan
from photonguard.experiments.action_protocol import validate_command,authorize_command,audit_commentary
from photonguard.experiments.case_catalog import get_case
from photonguard.experiments.case_workflow import create
from test_case_recovery import store_at,act

BASE='波长633 nm，束腰半径480 um，束腰位置-35 mm，焦距100 mm，屏幕在透镜后120 mm，屏幕半径不超过70 um。'

@pytest.mark.parametrize('text,value,kind',[
 ('把波长改成532 nm。',532,None),('先别把波长改成532 nm。',633,'keep'),
 ('不用改波长。',633,'keep'),('待用户批准后将波长设为532 nm。',633,'review'),
 ('除非我确认，否则不要执行：准备将波长设为532 nm。',633,'review'),
 ('除非我确认，否则不要动；若获批准，波长改为532 nm。',633,'review'),
 ('可以把波长改成532 nm吗？',633,'review'),('如果波长改成532 nm会怎样？',633,'review'),
 ('记录上写着“波长532 nm”，但那不是本次的。',633,'review'),
 ('记录中写着“波长532 nm”，但那不是本次的。',633,'review'),
 ('波长780 nm。',633,'conflict'),('更正波长780 nm。',780,None)])
def test_scoped_wavelength(text,value,kind):
 s=update(update(fs.seed('G01'),BASE,'base'),text,'change')
 assert s['facts']['parameters.wavelength_nm']['value']==value
 if kind=='keep':assert s['notice'] and compile_case_plan(s)['plan']
 if kind in ('review','conflict'):assert s['questions'] and not compile_case_plan(s)['plan']

@pytest.mark.parametrize('text,expected,ambiguous',[
 ('束腰位置改为透镜后-35 mm。',-35,True),('束腰位置改为透镜前+35 mm。',-35,True),
 ('束腰位置改为透镜前35 mm。',-35,False),('束腰位置改为透镜后35 mm。',35,False),
 ('束腰位置改为透镜前-40 mm。',-40,False),('束腰位置改为透镜后+40 mm。',40,False)])
def test_sign_direction(text,expected,ambiguous):
 s=update(update(fs.seed('G01'),BASE,'base'),text,'change')
 assert s['facts']['parameters.waist_z_mm']['value']==expected
 assert bool(s['questions'])==ambiguous
 if ambiguous:
  assert [q['fields'] for q in s['questions']]==[['parameters.waist_z_mm']]
  t=update(s,'明确确认单字段','confirm',request={'parameters':{'waist_z_mm':-35}})
  assert not t['questions'] and compile_case_plan(t)['plan']
  assert fs.undo(t,'undo')['questions']

def test_mixed_correction_and_trailing_uncertainty():
 s=update(fs.seed('G01'),BASE,'base')
 for text in ['更正屏幕半径不超过60 um；另有记录说束腰半径450 um，尚待核对。',
              '屏幕半径改为不超过60 um，束腰半径450 um，但只是草稿数据，还没确认。']:
  t=update(s,text,'change');assert t['facts']['goal.target']['value']==60
  assert t['facts']['parameters.waist_radius_um']['value']==480
  assert [q['fields'] for q in t['questions']]==[['parameters.waist_radius_um']]
 t=update(s,'目标改成60 um，其余不变，不用改波长。','goal')
 assert t['facts']['goal.target']['value']==60 and not t['questions']

def test_negation_replacement_and_unknown_fragment():
 s=update(fs.seed('G01'),BASE,'base')
 t=update(s,'不是波长532 nm，我更正的是焦距120 mm。','replace')
 assert t['facts']['parameters.wavelength_nm']['value']==633 and t['facts']['parameters.focal_length_mm']['value']==120
 t=update(s,'不是波长532 nm，而是波长520 nm。','replace')
 assert t['facts']['parameters.wavelength_nm']['value']==520
 t=update(s,'更正波长532 nm；旋转神秘参数30度。','fragment')
 assert t['questions'] and not compile_case_plan(t)['plan']

def test_unique_natural_direction_and_two_questions():
 s=update(fs.seed('G01'),BASE.replace('束腰位置-35 mm，',''),'base')
 t=update(s,'腰斑离镜片往入射侧3.5厘米。','answer')
 assert t['facts']['parameters.waist_z_mm']['value']==-35 and not t['questions']
 t=update(s,'-3.5厘米。','answer');assert t['facts']['parameters.waist_z_mm']['value']==-35
 t=update(fs.seed('G01'),'-3.5厘米。','answer');assert 'parameters.waist_z_mm' not in t['facts']

@pytest.mark.parametrize('facts',[{}, {'case_id':'G01'}, {'wavelength_nm':999}, [], {'unknown':12}])
def test_optional_commentary_never_authorizes_or_blocks(facts):
 s=fs.seed('G01','teaching');obj={'action':'compute','facts':facts};before=copy.deepcopy(s)
 command=validate_command(obj,get_case('G01'))
 assert authorize_command(command,s)['authorized'] and s==before
 audit=audit_commentary(obj,s,get_case('G01'))
 assert audit['raw_commentary_error']==(facts not in ({},{'case_id':'G01'}))

def test_bad_command_conflict_restore_and_empty_ask():
 s=update(update(fs.seed('G01'),BASE,'base'),'束腰位置改为透镜后-35 mm','conflict')
 with pytest.raises(ValueError):authorize_command({'action':'compute'},s)
 with pytest.raises(ValueError):authorize_command({'action':'restore','target_id':'bad','target_result_sha256':'bad'},s)
 with pytest.raises(ValueError):validate_command({'action':'ask','fields':['invented']},get_case('G01'))
 assert authorize_command({'action':'ask','fields':[]},s)['program_assisted_ask']

def test_product_keep_and_no_false_model_call(tmp_path):
 store=store_at(tmp_path);s=create(store,{'case_id':'G01','mode':'teaching','session_version':2})
 old=s['plan']['sha256'];s=act(store,s,'fact_update',text='先别把波长改成532 nm。')
 assert s['plan']['sha256']==old and s['fact_state']['notice'] and s['model_calls']==0

def test_scorer_measured_unknown_and_recovery():
 from photonguard.experiments.session_study import score
 rows=[{'structure_correct':True,'expected_action':True,'tool_ok':True,'violation_executed':True,'extra_user_field_edits':3}]
 assert score(rows)['violations_executed']==1 and score(rows)['extra_user_field_edits']==3
 assert score([{'structure_correct':True}])['violations_executed'] is None
 rows=[{'structure_correct':True,'tool_ok':False},{'structure_correct':True,'expected_action':True,'tool_ok':True,'final_postconditions_met':True}]
 assert score(rows)['final_success'] and score(rows)['first_try_failure'] and not score(rows)['strict_script_success']

def test_real_product_command_boundaries_and_reuse(tmp_path,monkeypatch):
 from photonguard.experiments.session_commands import act
 from test_experiment_service import ImmediateThread
 from photonguard.experiments import service
 monkeypatch.setattr(service.threading,'Thread',ImmediateThread)
 store=store_at(tmp_path);store.owner.allow_workers=True
 s=create(store,{'case_id':'G02','mode':'teaching','session_version':2})
 r=act(store,s,'session_command',command={'action':'compute','facts':{'wavelength_nm':999}})
 assert r['command_receipt']['status']=='REJECTED' and not r.get('result')
 r=act(store,r,'session_command',command={'action':'compute','facts':{'wavelength_nm':999}},approve=True,plan_sha256=s['plan']['sha256'])
 assert r['result'] and r['command_receipt']['audit']['raw_commentary_error'] and not r['command_receipt']['delivered_error']
 from photonguard.experiments.intent_study import feedback,payload
 from photonguard.workflow_model import wire
 request,_=payload([{'role':'tool','content':feedback(r,store)},{'role':'user','content':{'text':'请说明结果'}}],r['fact_state'],'S')
 assert not wire.credential_risk(request)
 original=r['id'];original_hash=copy.deepcopy(r['result'])
 root=store.get(r['exploration_root']);root['exploration_ledger']['stages']=2;store.save(root)
 d=act(store,r,'session_input',text='更正屏幕半径不超过10 um。')
 r=act(store,d,'session_command',command={'action':'rescore','facts':{'case_id':'G02'}})
 assert r['reuse'] and r['result']['resources']['fast_evaluations']==0
 assert store.get(original)['result']==original_hash
 bad=act(store,r,'session_command',command={'action':'restore','target_id':original,'target_result_sha256':'wrong'})
 assert bad['command_receipt']['status']=='REJECTED'
 d=act(store,r,'session_input',text='把旧结果改成Fresnel实算结果。')
 a=act(store,d,'session_command',command={'action':'explain'})
 assert a['command_receipt']['rendered']['scope_warning']
 b=act(store,d,'session_command',command={'action':'compute'},approve=True,plan_sha256=None)
 assert b['command_receipt']['status']=='REJECTED'

def test_snapshot_and_public_input_exclude_oracle():
 from photonguard.experiments.intent_study import payload
 import json
 s=fs.seed('G01','teaching');s=fs.refresh(s)
 r,_=payload([{'role':'user','content':{'text':'计算'}}],s,'R')
 t,_=payload([{'role':'user','content':{'text':'计算'}}],s,'S')
 a=json.loads(r['messages'][-1]['content']);b=json.loads(t['messages'][-1]['content'])
 extra=b.pop('effective_facts');assert a==b
 assert not {'questions','issues','expected','expected_action','recommended_action'}&extra.keys()
