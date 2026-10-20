import copy,json,io,zipfile
import pytest
from photonguard.experiments.case_workflow import create
from photonguard.experiments.session_commands import act
from photonguard.experiments.model_context import build_context,public_command,public_tool_view
from photonguard.experiments.intent_study import feedback
from photonguard.experiments import service,fact_state as fs
from photonguard.workflow_model import wire
from photonguard.core import digest
from test_case_recovery import store_at
from test_experiment_service import ImmediateThread

@pytest.fixture
def computed(tmp_path,monkeypatch):
 monkeypatch.setattr(service.threading,'Thread',ImmediateThread)
 store=store_at(tmp_path);store.owner.allow_workers=True
 s=create(store,{'case_id':'D02','mode':'teaching','session_version':2})
 s=act(store,s,'fact_update',text='更正容差0.03 mm')
 s=act(store,s,'session_command',command={'action':'compute'},approve=True,plan_sha256=s['plan']['sha256'])
 assert s['status']=='COMPLETED'
 return store,s

@pytest.mark.parametrize('source',['rescore','draft','missing','unsupported'])
def test_restore_product_receipt_export_and_projection_same_version(computed,source):
 store,original=computed;old=copy.deepcopy(original['result'])
 draft=act(store,original,'session_input',text='更正容差0.015 mm')
 if source=='rescore':draft=act(store,draft,'session_command',command={'action':'rescore'})
 if source=='missing':draft=act(store,draft,'fact_update',text='束腰位置未确认；缝距范围未知。')
 if source=='unsupported':draft=act(store,draft,'fact_update',text='改为自由空间Fresnel传播。')
 s=act(store,draft,'session_command',command={'action':'restore','target_id':original['id'],'target_result_sha256':digest(old)})
 v=s['command_receipt']['rendered'];assert v['facts']['goal.tolerance']==v['goal']['tolerance']==.03
 assert v['result_context']['facts']['goal.tolerance']==.03 and not v['questions'] and 'scope_warning' not in v
 assert not s['command_receipt']['delivered_error'] and s['result']==old
 assert feedback(s,store)['rendered']['facts']['goal.tolerance']==.03
 with zipfile.ZipFile(io.BytesIO(store.export(s['id']))) as z:
  report=json.loads(z.read('tables/report.json'))['experiment_record'];assert report['goal']==v['goal'] and report['result_sha256']==digest(old)

def test_draft_separate_from_actual_parent(computed):
 store,original=computed;draft=act(store,original,'session_input',text='更正容差0.015 mm')
 v=store.presentation(draft)
 assert v['draft_context']['goal']['tolerance']==.015 and v['result_context']['goal']['tolerance']==.03
 assert v['draft_context']['record_id']!=v['result_context']['record_id']

def test_next_payload_projects_optional_comment_and_keeps_secret_guard(computed):
 store,s=computed;raw='{"action":"explain","facts":{"authorization":"annotation label only"}}'
 s=act(store,s,'session_command',command=json.loads(raw));fb=feedback(s,store)
 p,_=build_context([{'role':'assistant','content':raw},{'role':'tool','content':fb}],s['fact_state'])
 assert not wire.credential_risk(p) and 'annotation label' not in json.dumps(p)
 assert s['command_receipt']['audit']['schema_errors']==['authorization']
 assert public_command('not JSON','D02')=={'status':'MODEL_OUTPUT_INVALID'}
 with pytest.raises(ValueError,match='PREFLIGHT'):
  build_context([{'role':'user','content':{'text':'测试输入 '+'sk-'+'x'*32}}],s['fact_state'])
 a,_=build_context([],s['fact_state'],'R');b,_=build_context([],s['fact_state'],'S')
 aa=json.loads(a['messages'][-1]['content']);bb=json.loads(b['messages'][-1]['content']);snap=bb.pop('effective_facts');assert aa==bb and 'questions' not in snap

def test_async_running_and_failure_not_reported_as_completed(tmp_path,monkeypatch):
 class Deferred:
  def __init__(self,*a,**k):pass
  def start(self):pass
 monkeypatch.setattr(service.threading,'Thread',Deferred)
 store=store_at(tmp_path);store.owner.allow_workers=True
 s=create(store,{'case_id':'G02','mode':'teaching','session_version':2})
 s=act(store,s,'session_command',command={'action':'compute'},approve=True,plan_sha256=s['plan']['sha256'])
 assert s['command_receipt']['rendered']['status']=='RUNNING' and not s['command_receipt']['rendered']['result_context']
 def fail(*a,**k):raise RuntimeError('Injected physical failure')
 monkeypatch.setattr(service,'execute_plan',fail);store._run(s['id']);s=store.get(s['id'])
 assert s['command_receipt']['tool_terminal']=='FAILED' and s['command_receipt']['rendered']['status']=='FAILED'

def test_local_rejection_freezes_meter_without_fabricated_response(tmp_path):
 from photonguard.experiments.request_meter import RequestMeter,BatchFrozen
 class Client:
  calls=0
  def preflight(self):raise ValueError('Injected local guard failure')
  def complete(self,*a):self.calls+=1;raise AssertionError('must not send')
 c=Client();m=RequestMeter(c,tmp_path,2,live=False)
 with pytest.raises(BatchFrozen,match='LOCAL_PREFLIGHT'):m.call('first',{})
 with pytest.raises(BatchFrozen,match='ALREADY_FROZEN'):m.call('second',{})
 assert c.calls==0 and len(m.rows)==1 and m.rows[0]['preflight_rejected'] and not m.rows[0]['provider_response_received']

def test_product_ai_context_uses_projection_on_second_turn(computed):
 store,s=computed
 class Client:
  requests=[]
  def preflight(self):pass
  def complete(self,ident,payload):
   assert not wire.credential_risk(payload);self.requests.append(payload)
   return {'assistant':{'content':'{"action":"explain","facts":{"authorization":"annotation label only"}}'},'audit':{'live_dispatch':False}}
 c=Client();store.owner.product_client=c
 for _ in range(2):s=act(store,s,'session_ai',text='解释当前实际结果。',approve_data=True)
 assert len(c.requests)==2 and 'annotation label only' not in json.dumps(c.requests[-1])
 assert s['ai_step']['status']=='ACCEPTED' and s['command_receipt']['audit']['raw_commentary_error']
