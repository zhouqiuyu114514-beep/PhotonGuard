"""Regression for complete human input, same-field evidence and execution limits."""
import copy
import pytest
from photonguard.experiments import fact_state as fs
from photonguard.experiments.dialogue_update import update,compile_case_plan

ORIGINAL='''我想做一个近红外反射膜的教学设计。
膜两侧都是空气，正入射；材料无损、无色散。高折射率材料 nH=2.1，低折射率材料 nL=1.45。按 H/L 交替排列，从 H 层开始，每层采用设计波长 940 nm 对应的四分之一波光学厚度。
初始为2层，只允许比较总层数2、4、6、8层，其他条件不变。计算波长为780、850、940、1000、1064 nm。
目标：940 nm处反射率至少80%。请整理条件，准备四个候选的比较计划，等我确认后再计算。只做快速计算，不做Meep独立验证。若没有候选达标，请如实说明。'''

def prepared(text=ORIGINAL):return update(fs.seed('F02'),text,'first')

def test_original_complete_text_keeps_exact_five_waves_and_removes_meep():
    state=prepared();result=compile_case_plan(state)
    assert not state['questions']
    spec=result['spec'];params=spec['known_parameters']
    assert params['material_n_high']==2.1 and params['material_n_low']==1.45
    assert params['design_wavelength_um']==pytest.approx(.94)
    assert params['wavelengths_um']==pytest.approx([.78,.85,.94,1,1.064])
    assert not {'scan_min_um','scan_max_um','scan_points'} & params.keys()
    assert spec['allowed_variables']=={'layer_count':[2,4,6,8]}
    assert spec['resource_budget']['max_meep_validations']==spec['resource_budget']['max_fdtd']==0
    assert 'meep' not in [t['id'] for t in result['plan']['tool_graph']]
    for fact in state['facts'].values():
        for e in fact['evidence']:
            assert e['quote']==ORIGINAL[e['start']:e['end']]

@pytest.mark.parametrize('policy',['只做快速计算','只运行快速计算','仅使用TMM快速计算','不做Meep独立验证','禁止FDTD','不要Meep独立核对'])
def test_fast_only_standalone_and_followup_persist(policy):
    state=prepared(ORIGINAL.replace('只做快速计算，不做Meep独立验证',policy))
    state=update(state,'目标波长改为780 nm。保持材料和实际膜厚不变。','followup')
    result=compile_case_plan(state)
    assert result['plan'] and result['spec']['goal']['wavelength_um']==pytest.approx(.78)
    assert result['spec']['known_parameters']['design_wavelength_um']==pytest.approx(.94)
    assert result['spec']['resource_budget']['max_fdtd']==0

@pytest.mark.parametrize('text',['如果允许Meep独立验证会怎样','不要允许Meep独立验证','Meep独立验证尚未确认'])
def test_conditional_or_negated_request_cannot_relax_fast_only(text):
    state=update(prepared(),text,'next')
    assert state['facts']['execution.fast_only']['value'] is True

def test_model_cannot_borrow_design_wave_for_other_target():
    state=update(fs.seed('F02'),'设计波长940 nm，目标波长780 nm','x',model_obj={'patches':[{'field':'goal.wavelength_um','value':.94,'quote':'设计波长940 nm'}]})
    assert state['facts']['goal.wavelength_um']['value']==pytest.approx(.78)
    assert state['issues'][0]['kind']=='SOURCE_UNRESOLVED'

def test_model_cannot_turn_on_meep_or_invent_index():
    state=update(fs.seed('F02'),ORIGINAL,'x',model_obj={'patches':[{'field':'execution.fast_only','value':False,'quote':'不做Meep独立验证'},{'field':'parameters.material_n_low','value':2.1,'quote':'nH=2.1'}]})
    assert len(state['issues'])==2
    assert compile_case_plan(state)['spec']['resource_budget']['max_fdtd']==0

def test_catalog_first_item_is_redundant_model_baseline_only():
    state=update(fs.seed('F02'),'层数候选2、4、6、8','x',model_obj={'patches':[{'field':'parameters.layer_count','value':2,'quote':'层数候选2、4、6、8'}]})
    assert not state['issues'] and 'parameters.layer_count' not in state['facts']
    bad=update(fs.seed('F02'),'层数候选2、4、6、8','x',model_obj={'patches':[{'field':'parameters.layer_count','value':7,'quote':'层数候选2、4、6、8'}]})
    assert bad['issues']

def test_fractional_layer_count_is_not_rounded_into_a_valid_plan():
    with pytest.raises(ValueError,match='整数'):
        compile_case_plan(prepared(ORIGINAL.replace('总层数2、4、6、8层','总层数2.5、4、6、8层')))

def test_form_update_cannot_drop_existing_fast_only_policy():
    state=update(prepared(),'用户确认目标','next',request={'goal':{'target':.7}})
    assert compile_case_plan(state)['spec']['resource_budget']['max_fdtd']==0


def test_switch_light_source_keeps_design_and_old_result_reference():
    s=update(prepared(),'现在光源换成780 nm，反射率仍要求至少80%。保留原来四个候选的材料、层数和实际膜厚，不要按新波长重新设计膜厚。请根据已有计算比较原推荐方案和其他候选是否达标，并保留940 nm时的结果供对照。只做快速计算。','second')
    r=compile_case_plan(s)
    assert not s['questions']
    assert r['spec']['goal']['wavelength_um']==pytest.approx(.78)
    assert r['spec']['known_parameters']['design_wavelength_um']==pytest.approx(.94)
    assert r['spec']['resource_budget']['max_fdtd']==0


def test_model_directory_alias_and_endpoints_do_not_expand_catalog():
    obj={'patches':[{'field':'parameters.layer_count','value':[2,4,6,8],'quote':'层数候选2、4、6、8'}, {'field':'recipe.min','value':2,'quote':'层数候选2、4、6、8'}, {'field':'recipe.max','value':8,'quote':'层数候选2、4、6、8'}]}
    s=update(fs.seed('F02'),'层数候选2、4、6、8','x',model_obj=obj)
    assert not s['issues'] and s['facts']['recipe.values']['value']==[2,4,6,8]
    assert 'recipe.min' not in s['facts'] and 'recipe.max' not in s['facts']


@pytest.mark.parametrize('phrase',[
 '每层光学厚度是940纳米波长的四分之一',
 '每层厚度为940nm的四分之一波光学厚度',
 '每层厚度都按940纳米波长的四分之一波来设计',
])
def test_explicit_quarter_wave_reference_word_orders(phrase):
    s=update(fs.seed('F02'),phrase,'one')
    assert not s.get('ambiguities')
    assert s['facts']['parameters.design_wavelength_um']['value']==pytest.approx(.94)


def test_physical_thickness_fraction_is_not_design_wavelength():
    s=update(fs.seed('F02'),'膜厚为940nm的四分之一','one')
    assert 'parameters.design_wavelength_um' not in s['facts']


@pytest.mark.parametrize('phrase',['只比较2、4、6、8层','只考虑2层、4层、6层、8层','候选2层、4层、6层和8层'])
def test_layer_unit_binds_catalog_without_internal_field_names(phrase):
    s=update(fs.seed('F02'),phrase,'one')
    assert s['facts']['recipe.values']['value']==[2,4,6,8]


def test_heading_units_and_reporting_request_are_not_missing_parameters():
    text='| 参数 | 值 |\n设计波长（nm）=940。目标波长（nm）=940。如果都不达标，就直说。'
    s=update(fs.seed('F02'),text,'one')
    assert not s.get('ambiguities')
    assert s['facts']['parameters.design_wavelength_um']['value']==pytest.approx(.94)
    assert s['facts']['goal.wavelength_um']['value']==pytest.approx(.94)


def test_lower_bound_and_unchanged_range_language():
    s=update(prepared(),'更正反射率不低于75%。其他物理条件和候选允许范围不变。','two')
    r=compile_case_plan(s)
    assert r['plan'] and r['spec']['goal']['operator']=='>='
    assert r['spec']['goal']['target']==pytest.approx(.75)


def test_unused_default_grid_not_presented_as_active_conditions():
    active=fs.effective_facts(prepared())
    assert 'parameters.wavelengths_um' in active
    assert not {'parameters.scan_min_um','parameters.scan_max_um','parameters.scan_points'} & active.keys()


def test_old_model_value_cannot_override_explicit_new_goal():
    s=update(prepared(),'反射率目标改为不低于75%','next',model_obj={'patches':[{'field':'goal.target','value':.8,'quote':'保持原值'}]})
    assert s['issues'] and s['facts']['goal.target']['value']==pytest.approx(.75)


def test_wrong_model_namespace_repaired_only_with_same_field_source():
    text='计算波长780、850、940 nm'
    s=update(fs.seed('F02'),text,'one',model_obj={'patches':[{'field':'recipe.wavelengths_um','value':[.78,.85,.94],'quote':text}]})
    assert not s['issues']
    s=update(fs.seed('F02'),'设计波长940 nm','one',model_obj={'patches':[{'field':'recipe.wavelengths_um','value':[.94],'quote':'设计波长940 nm'}]})
    assert s['issues'] and 'parameters.wavelengths_um' not in s['facts']


def test_colloquial_catalog_sampling_and_report_instruction():
    text=ORIGINAL.replace('只允许比较总层数2、4、6、8层','先只比2层、4层、6层、8层这四种').replace('计算波长为780、850、940、1000、1064 nm','要算780、850、940、1000、1064纳米这几个波长').replace('若没有候选达标，请如实说明','如果都不达标，就照实说')
    s=prepared(text)
    assert not s['questions'] and not s['issues']
    r=compile_case_plan(s)
    assert r['plan'] and r['spec']['allowed_variables']['layer_count']==[2,4,6,8]
    assert r['spec']['known_parameters']['wavelengths_um']==pytest.approx([.78,.85,.94,1,1.064])


@pytest.mark.parametrize('phrase',['光源换成780 nm','目标波长改为780 nm'])
def test_model_cannot_shrink_grid_when_user_changes_only_existing_goal(phrase):
    state=update(prepared(),phrase,'next',model_obj={'patches':[{'field':'parameters.wavelengths_um','value':[.78],'quote':phrase}]})
    assert not state['issues']
    result=compile_case_plan(state)
    assert result['plan'] and result['spec']['goal']['wavelength_um']==pytest.approx(.78)
    assert result['spec']['known_parameters']['wavelengths_um']==pytest.approx([.78,.85,.94,1,1.064])
    assert any(n['kind']=='MODEL_SAMPLING_CHANGE_REJECTED_GOAL_ONLY' and not n['activated'] for n in state['events'][-1]['interpretation_notes'])

@pytest.mark.parametrize('values,quote',[([.85],'光源换成780 nm'),([.78],'低折射率1.45'),([.78,.85],'光源换成780 nm')])
def test_unrelated_or_changed_model_sampling_proposals_still_block(values,quote):
    state=update(prepared(),'光源换成780 nm','next',model_obj={'patches':[{'field':'parameters.wavelengths_um','value':values,'quote':quote}]})
    assert state['issues']
    assert state['facts']['parameters.wavelengths_um']['value']==pytest.approx([.78,.85,.94,1,1.064])

def test_explicit_sampling_edit_is_not_mistaken_for_goal_only():
    state=update(prepared(),'计算波长改为780 nm。目标波长改为780 nm','next',model_obj={'patches':[{'field':'parameters.wavelengths_um','value':[.78],'quote':'计算波长改为780 nm'}]})
    assert not state['issues']
    assert state['facts']['parameters.wavelengths_um']['value']==[.78]

@pytest.mark.parametrize('phrase',['每层光学厚度为940 nm/4','每层四分之一波长光学厚度对应940 nm'])
def test_quarter_wave_optical_thickness_notation(phrase):
    state=update(fs.seed('F02'),phrase,'m')
    assert not state.get('ambiguities')
    assert state['facts']['parameters.design_wavelength_um']['value']==pytest.approx(.94)

@pytest.mark.parametrize('phrase',['每层物理厚度为940 nm/4','每层光学厚度为940 nm/40'])
def test_notation_does_not_invent_quarter_wave_design(phrase):
    state=update(fs.seed('F02'),phrase,'m')
    assert 'parameters.design_wavelength_um' not in state['facts']
