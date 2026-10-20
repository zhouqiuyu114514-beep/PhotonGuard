import pytest
from photonguard.experiments import fact_state as fs
from photonguard.experiments.dialogue_update import update,compile_case_plan
from photonguard.experiments.fact_binding import gaussian_assumption

TEXT = '我想为一束绿色激光选择聚焦透镜。\n\n光在空气中传播，采用理想 TEM00 高斯光束，M²=1，只使用一片理想薄透镜。\n\n波长为532 nm，束腰半径为320 μm，半径指1/e²强度半径。束腰位于透镜前30 mm，屏幕固定在透镜后110 mm。\n\n只允许比较焦距75、100、125、150 mm这四片透镜，其他物理条件保持不变。\n\n目标：屏幕上的光斑半径不超过90 μm。请比较四个候选是否达标；如果有多个达标，指出其中光斑最小的候选。如果全部未达标，请如实说明。\n\n只做快速计算，不做Meep独立验证。先整理条件并生成计划，等我确认后再计算。\n\n补充资料：\n确认采用当前高斯光束模型：TEM00、M²=1，所有光斑半径均为1/e²强度半径。先只判断四个候选的屏幕光斑半径是否不超过90 μm，不额外设置排序或条件分支。其余已确认参数保持不变，只做快速计算。'

def test_complete_gaussian_task_and_confirmation_have_no_missing_facts():
    state=fs.seed('G02')
    for i,text in enumerate(TEXT.split('\n\n补充资料：\n')):
        state=update(state,text,str(i))
        assert not state['questions'] and not state['issues']
    result=compile_case_plan(state);spec=result['spec']
    assert result['plan']
    assert spec['known_parameters']['waist_z_mm']==-30
    assert spec['known_parameters']['waist_radius_um']==320
    assert spec['known_parameters']['screen_distance_mm']==110
    assert spec['allowed_variables']['focal_length_mm']==[75,100,125,150]
    assert spec['goal']['operator']=='<=' and spec['goal']['target']==90
    assert spec['resource_budget']['max_fdtd']==0

@pytest.mark.parametrize('text',['M²=1','M^2 = 1.0','采用理想 TEM00 高斯光束','半径指1/e²强度半径','所有光斑半径均为1/e^2强度半径','确认采用当前高斯光束模型：TEM00、M²=1'])
def test_fixed_declaration_not_mistaken_for_numeric_parameter(text):
    state=update(fs.seed('G02'),text,'m')
    assert not state.get('ambiguities')
    assert 'goal.target' not in state['facts']
    assert 'parameters.waist_radius_um' not in state['facts']

@pytest.mark.parametrize('text',['M²=1.2','M²=10','采用TEM01高斯光束','半径为1/e强度半径','半径为半高全宽FWHM','如果M²=1','不是TEM00','M²=1且焦距为80mm'])
def test_other_or_conditional_models_are_not_accepted_as_fixed_declarations(text):
    assert not gaussian_assumption(text)

@pytest.mark.parametrize('text',['M²=1.2','采用TEM01高斯光束','半径为1/e强度半径'])
def test_incompatible_numeric_conventions_still_require_review(text):
    state=update(fs.seed('G02'),TEXT.split('\n\n补充资料：\n')[0].replace('M²=1',text),'m')
    assert state['questions'] and not compile_case_plan(state)['plan']

def test_hypothetical_physical_edit_not_consumed_as_reporting():
    state=update(fs.seed('G02'),TEXT.split('\n\n补充资料：\n')[0]+'如果有多个达标，焦距改为200 mm。','m')
    assert state['questions'] and any(a['kind']=='CONDITIONAL_PROPOSAL' for a in state['ambiguities'])

@pytest.mark.parametrize('text',['半径指FWHM','光斑按半高全宽定义','不是TEM00高斯光束'])
def test_incompatible_non_numeric_definitions_are_not_silently_ignored(text):
    state=update(fs.seed('G02'),TEXT.split('\n\n补充资料：\n')[0]+'。'+text,'m')
    assert state['questions'] and not compile_case_plan(state)['plan']

@pytest.mark.parametrize('notation',['（1/e²强度半径）','（指 1/e^2 强度半径）','(1/e2 强度半径)'])
def test_parenthesized_radius_definition_not_read_as_another_value(notation):
    state=update(fs.seed('G02'),'束腰半径320 μm'+notation,'m')
    assert not state.get('ambiguities')
    assert state['facts']['parameters.waist_radius_um']['value']==320

@pytest.mark.parametrize('word',['收紧到','收紧为','调整为','放宽到'])
def test_explicit_target_changes_do_not_create_false_conflict(word):
    state=update(fs.seed('G02'),TEXT.split('\n\n补充资料：\n')[0],'m')
    state=update(state,'屏幕光斑半径要求'+word+'不超过60 μm','m2')
    assert not state['questions']
    assert compile_case_plan(state)['spec']['goal']['target']==60

@pytest.mark.parametrize('phrase',['如果有多个达标，指出光斑最小的那个','若多个候选达标，请指出其中光斑最小者'])
def test_reporting_request_not_hypothetical_physical_edit(phrase):
    state=update(fs.seed('G02'),TEXT.split('\n\n补充资料：\n')[0]+'。'+phrase,'m')
    assert not state['questions']
    assert compile_case_plan(state)['spec']['goal']['operator']=='<='

def test_multi_lens_model_rejected_but_catalog_and_exclusion_allowed():
    from photonguard.experiments.case_catalog import unsupported_request
    assert unsupported_request('只使用两片理想薄透镜')
    assert unsupported_request('串联3片透镜')
    assert not unsupported_request('从四片透镜中选择一片，比较焦距75、100、125、150 mm')
    assert not unsupported_request('不使用两片理想薄透镜，只使用一片')

@pytest.mark.parametrize('text',['光束为空气中传播的理想TEM00高斯光束','条件：空气中理想 TEM00 高斯光束','绿色激光聚焦透镜选择：空气、理想TEM00高斯光束、M²=1、一片理想薄透镜','半径是1/e²强度半径','- 理想 TEM00 高斯光束'])
def test_combined_fixed_model_declarations(text):
    assert gaussian_assumption(text)
    assert not update(fs.seed('G02'),text,'m').get('ambiguities')

@pytest.mark.parametrize('text',['空气、理想TEM00高斯光束、M²=1.2','高折射率介质中TEM00高斯光束','条件：M²=1，焦距改为80 mm'])
def test_partial_known_model_declaration_never_hides_other_conditions(text):
    assert not gaussian_assumption(text)
