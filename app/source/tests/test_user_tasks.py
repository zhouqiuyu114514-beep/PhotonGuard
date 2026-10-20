import copy
import json
import pytest
from test_inverse_journeys import store,act,wait,data
from test_research_advice import receive
from photonguard.workflow import WorkflowError
from photonguard.experiments import task_entry as entry,task_flow as flow,task_view as view
from photonguard.experiments import inverse_models as m,observation_group as ow,advice_contract as c,inverse_report


def initial(store,model):
    s=entry.start(store,{'text':'明确选择教学任务','model':model,'teaching':True})['case']
    s=act(store,s,'inverse_task_initial_plan',confirm_conditions=True)
    return wait(store,act(store,s,'inverse_run',approve=True,plan_sha256=s['inverse_plan']['sha256']))


def menu(store,s):
    constraints={'wavelengths_nm':[633.,660.,780.]} if s['inverse_settings']['model']==m.FILM else {
        'points':71 if s['inverse_settings']['model']==m.SLIT else 5,'max_abs_x_mm':5. if s['inverse_settings']['model']==m.SLIT else 200.,
        'min_step_mm':.001,'allow_extension':True,'stable_exposure_background':True,'registration_uncertainty_mm':0.}
    return act(store,s,'inverse_measurement_plan',constraints=constraints)


@pytest.mark.parametrize('text,mode',[('比较已知参数的透镜方案','forward'),('我有高斯扫描CSV，反推束腰','inverse'),('帮我研究光学',None),('已有数据，比较透镜方案',None)])
def test_explainable_routing_without_physical_guesses(text,mode):
    assert entry.route(text)['mode']==mode
    assert entry.route(text)['source']=='PROGRAM_ROUTING_NOT_AI'


def test_missing_data_does_not_silently_make_teaching_or_call_model(store):
    assert entry.start(store,{'text':'帮我研究光学'})['status']=='NEEDS_INTENT'
    assert entry.start(store,{'text':'高斯已有数据，反推束腰'})['status']=='NEEDS_DATA'
    assert not store.bootstrap()['cases']
    _,_,raw=data(m.GAUSSIAN,count=9)
    s=entry.start(store,{'text':'分析我的观测','mode':'inverse','model':m.GAUSSIAN,'csv_text':raw,'source_kind':'USER_PROVIDED','source_name':'user'})['case']
    assert not s.get('teaching_object') and not s['inverse_settings']['fixed'] and s['model_calls']==0
    with pytest.raises((WorkflowError,ValueError)):act(store,s,'inverse_task_initial_plan',confirm_conditions=True)


@pytest.mark.parametrize('bad',['unknown','empty','duplicate'])
def test_invalid_primary_does_not_become_model_selection(store,bad):
    s=ow.create(store,{'model':m.GAUSSIAN,'teaching':True});obj=c.fixture();obj['primary_suggestion_id']='missing'
    if bad=='empty':obj['suggestions']=[]
    if bad=='duplicate':
        item=c.fixture('inspect_observation')['suggestions'][0];item['id']=obj['suggestions'][0]['id'];obj['suggestions'].append(item)
    out=receive(store,s,obj,'解释已有资料')
    assert out['inverse_ai']['validation_status']=='PARTIAL_VALID'
    assert view.advice(out)['source']!='MODEL_EXPLICIT_SELECTION'


def test_primary_is_model_named_and_old_contract_navigation_is_program(store):
    s=ow.create(store,{'model':m.GAUSSIAN,'teaching':True});obj=c.fixture();obj['suggestions']+=c.fixture('inspect_observation')['suggestions'];obj['primary_suggestion_id']='S_inspect_observation'
    s=receive(store,s,obj,'解释已有资料');assert view.advice(s)['primary']['kind']=='inspect_observation'
    assert view.advice(s)['source']=='MODEL_EXPLICIT_SELECTION'
    obj.pop('primary_suggestion_id');s=receive(store,s,obj,'解释已有资料')
    assert view.advice(s)['source']=='PROGRAM_NAVIGATION'


@pytest.mark.parametrize('model',m.MODELS)
def test_one_explicit_plan_runs_real_acquisition_review_and_joint_worker(store,model):
    s=menu(store,initial(store,model));assert s['status']=='COMPLETED'
    pid=s['measurement_plan']['recommended_id'];old=s['inverse_result'];before=copy.deepcopy(ow.root_record(store,s)['inverse_ledger'])
    s=act(store,s,'inverse_task_prepare',proposal_id=pid);sha=s['task_plan']['sha256']
    assert ow.root_record(store,s)['inverse_ledger']==before and flow.current(s)
    with pytest.raises(WorkflowError):act(store,s,'inverse_task_run',approve=False,plan_sha256=sha)
    out=wait(store,act(store,s,'inverse_task_run',approve=True,plan_sha256=sha))
    assert out['status']=='COMPLETED' and len(out['groups'])==2
    assert out['task_execution']['status']=='COMPLETED'
    assert [v['id'] for v in out['task_execution']['steps']]==['acquire','review','fit','receipt']
    assert out['task_execution']['model_action_id'] is None and out['model_calls']==0
    assert out['acquisition_expectation']['sampling_positions_match']
    assert ow.root_record(store,out)['inverse_ledger']['fit_runs_reserved']==2
    assert ow.root_record(store,out)['inverse_ledger']['acquisitions_reserved']==1
    ow.verify(store,out)
    task=view.summary(out);assert task['state']=='RESULT' and task['chart']
    if model==m.FILM:assert task['previous_mode_count']==len(old['modes'])
    assert task==inverse_report.view(out)['task_summary']
    exported=inverse_report.summary(out).decode();assert task['headline'] in exported and '<svg' in exported
    assert 'groups' not in task['numerical_plan'] and 'settings' not in task['continuous_plan']
    with pytest.raises(WorkflowError):act(store,store.get(s['id']),'inverse_task_run',approve=True,plan_sha256=sha)


def test_changed_goal_revokes_task_plan_and_new_plan_never_inherits_approval(store):
    s=menu(store,initial(store,m.GAUSSIAN));s=act(store,s,'inverse_task_prepare',proposal_id='baseline');old=s['task_plan']['sha256']
    obj=c.fixture('compare_acquisition');obj['updates']=[{'id':'U1','field':'goal.target','value':'waist_position','quote':'束腰位置优先','correction':False}]
    fixed=copy.deepcopy(s['inverse_settings']);s=receive(store,s,obj,'束腰位置优先')
    assert s['inverse_settings']==fixed and not flow.current(s) and not s.get('measurement_plan')
    with pytest.raises(WorkflowError):act(store,s,'inverse_task_run',approve=True,plan_sha256=old)
    s=menu(store,s);s=act(store,s,'inverse_task_prepare',proposal_id='baseline')
    assert old!=s['task_plan']['sha256'] and not s['task_plan']['approval']


def test_combined_fail_preserves_new_observation_and_does_not_repeat(store,monkeypatch):
    s=menu(store,initial(store,m.GAUSSIAN));s=act(store,s,'inverse_task_prepare',proposal_id='baseline')
    original=ow.action
    def fail_plan(store,s,data):
        if data['type']=='inverse_plan':raise WorkflowError('frozen join failure')
        return original(store,s,data)
    monkeypatch.setattr(ow,'action',fail_plan)
    out=act(store,s,'inverse_task_run',approve=True,plan_sha256=s['task_plan']['sha256'])
    assert out['task_execution']['status']=='PAUSED' and len(out['groups'])==2
    assert (store.folder(out['id'])/'scan-1.csv').exists()
    assert ow.root_record(store,out)['inverse_ledger']['acquisitions_reserved']==1
    assert ow.root_record(store,out)['inverse_ledger']['fit_runs_reserved']==1


def test_model_receipt_omits_raw_plot_and_full_fit_inputs(store,monkeypatch):
    s=initial(store,m.GAUSSIAN);sent=[]
    class Client:
        def complete(self,ident,payload):sent.append(payload);return {'assistant':{'content':json.dumps(c.fixture())}}
    monkeypatch.setattr(store,'_model',lambda *args:Client())
    s=inverse_report.guidance(store,s,{'text':'解释变化','approve_data':True})
    p=json.loads(next((store.folder(s['id'])/'ai-requests').glob('*/public-input.json')).read_text())
    assert 'chart' not in p['record']['task_summary'] and 'groups' not in p['record']['task_summary']['numerical_plan']
    assert p['record']['task_summary']['headline']==view.summary(s)['headline']


@pytest.mark.parametrize('field,value,quote,text',[
    ('preference.mode','BASELINE_FIRST','先比较','先比较'),
    ('design.max_abs_x_mm',4.,'最大行程4毫米','最大行程4毫米'),
    ('design.points',71,'新增71个点','沿用已有条件')])
def test_live_failure_fixes_do_not_accept_invented_defaults_travel_or_old_quotes(store,field,value,quote,text):
    s=ow.create(store,{'model':m.SLIT,'teaching':True});old=copy.deepcopy(s['inverse_settings']);obj=c.fixture('compare_acquisition')
    obj['updates']=[{'id':'U1','field':field,'value':value,'quote':quote,'correction':False}]
    out=receive(store,s,obj,text)
    assert out['inverse_ai']['validation_status']=='FACT_PATCH_REJECTED' and out['inverse_settings']==old
    assert not out.get('measurement_plan')


def test_explicit_stop_revokes_prepared_continuous_plan(store):
    s=menu(store,initial(store,m.GAUSSIAN));s=act(store,s,'inverse_task_prepare',proposal_id='baseline');old=s['task_plan']['sha256']
    s=receive(store,s,c.fixture('stop'),'停止当前分支');b=s['research_actions']
    s=act(store,s,'inverse_research_prepare',suggestion_sha256=b['sha256'],action_id=b['primary_action_id'])
    assert view.summary(s)['state']=='STOPPED' and not flow.current(s)
    with pytest.raises(WorkflowError):act(store,s,'inverse_task_run',approve=True,plan_sha256=old)


def test_initial_refit_requires_visible_observation_review_before_preparation(store):
    s=entry.start(store,{'text':'我想知道光束最细处在哪里','model':m.GAUSSIAN,'teaching':True})['case']
    s=receive(store,s,c.fixture('refit'),'现在可以开始分析吗？')
    primary=view.advice(s)['primary']
    assert not primary['ready'] and '采集条件' in primary['needs'][0]
    with pytest.raises(WorkflowError):act(store,s,'inverse_research_prepare',suggestion_sha256=s['research_actions']['sha256'],action_id=primary['id'])
    s=act(store,s,'inverse_task_initial_plan',confirm_conditions=True)
    s=receive(store,s,c.fixture('refit'),'我已确认这些条件，请准备分析')
    assert view.advice(s)['primary']['ready'] and not s.get('inverse_result')
    assert ow.root_record(store,s)['inverse_ledger']['fit_runs_reserved']==0


def test_imported_followup_leaves_waiting_state_and_old_selection_remains_auditable(store):
    s=menu(store,initial(store,m.GAUSSIAN))
    s=receive(store,s,c.fixture('propose_followup',proposal='baseline'),'按已有方案继续')
    a=view.advice(s);s=act(store,s,'inverse_research_prepare',suggestion_sha256=a['suggestion_sha256'],action_id=a['primary']['id'])
    # A public external import must resolve the selected-observation marker too.
    _,_,raw=data(m.GAUSSIAN,count=9)
    child=act(store,s,'inverse_append',approve=True,csv_text=raw,source_kind='SYNTHETIC_TEACHING',source_name='external test',license='CC0-1.0')
    assert child['research_origin']['status']=='ACQUISITION_RECEIVED'
    assert child['research_origin']['received_dataset_sha256']==child['groups'][-1]['dataset']['sha256']
    assert store.get(s['id'])['research_origin']['status']=='ACQUISITION_SELECTED'


def test_legacy_import_receipt_is_result_instead_of_waiting_without_record_rewrite():
    # Minimal saved projection from the reproduced imported-data journey.
    s={'id':'child','revision':1,'status':'COMPLETED','inverse_settings':ow.defaults(m.GAUSSIAN),
       'groups':[],'inverse_result':{'estimated_parameters':{'waist_radius_um':96.,'waist_z_mm':23.}},
       'research_origin':{'status':'ACQUISITION_SELECTED','plan_sha256':'selected'},
       'comparison_origin':{'record_id':'parent'},'acquisition_expectation':{'proposal_sha256':'selected'}}
    original=copy.deepcopy(s);assert view.summary(s)['state']=='RESULT' and s==original
    s.pop('comparison_origin');assert view.summary(s)['state']=='WAITING_DATA'
