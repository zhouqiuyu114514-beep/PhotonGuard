"""Planning boundary checks: no solver/model requests, and no hidden truth fixtures."""
import copy
import json
import math

import pytest

from photonguard.experiments.contracts import validate_spec
from photonguard.experiments.goals import assess, rank
from photonguard.experiments.planner import build_plan, plan_from_text, templates


def specimen(domain):
    return copy.deepcopy(next(t['spec'] for t in templates() if t['domain'] == domain))


class ReturnedJSON:
    """A recorded-shape test double; never contacts a provider."""
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def complete(self, ident, payload):
        self.requests.append((ident, payload))
        return {'audit': {'status': 'ASSISTANT_RETURNED', 'live_dispatch': False},
                'assistant': {'content': json.dumps(self.payload)}}


@pytest.mark.parametrize('domain', ['film', 'diffraction', 'gaussian'])
def test_plan_hash_preserves_explicit_candidate_and_locked_contract(domain):
    raw = specimen(domain)
    before = copy.deepcopy(raw)
    plan = build_plan(raw)
    assert raw == before
    assert plan == build_plan(raw)
    assert len(plan['sha256']) == 64
    assert len(plan['candidates']) == math.prod(len(v) for v in raw['allowed_variables'].values())
    assert set(plan['locked_parameters']).isdisjoint(plan['allowed_variables'])
    assert plan['spec']['assumptions']


def test_goal_revision_preserves_input_beam_and_catalog():
    parent = validate_spec(specimen('gaussian'))
    revised = copy.deepcopy(parent)
    revised['goal'] = {'metric': 'screen_radius_um', 'operator': '<=', 'target': 50, 'unit': 'um'}
    plan = build_plan(revised, parent)
    for candidate in plan['candidates']:
        for key in ('wavelength_nm', 'waist_radius_um', 'waist_z_mm', 'screen_distance_mm'):
            assert candidate['parameters'][key] == parent['known_parameters'][key]
    assert {c['parameters']['focal_length_mm'] for c in plan['candidates']} == {100, 150, 200}


@pytest.mark.parametrize('change', ['beam', 'new_variable', 'new_catalog_value', 'new_domain'])
def test_revision_cannot_make_goal_easier_by_changing_unauthorized_inputs(change):
    parent = validate_spec(specimen('gaussian'))
    revised = copy.deepcopy(parent)
    if change == 'beam':
        revised['known_parameters']['waist_radius_um'] = 700
    elif change == 'new_variable':
        revised['locked_parameters'].remove('screen_distance_mm')
        revised['allowed_variables']['screen_distance_mm'] = [100, 150]
    elif change == 'new_catalog_value':
        revised['allowed_variables']['focal_length_mm'] = [80, 100]
    else:
        revised = specimen('diffraction')
    with pytest.raises(ValueError):
        build_plan(revised, parent)


def test_catalog_can_be_narrowed_without_changing_original_results():
    parent = validate_spec(specimen('gaussian'))
    before = copy.deepcopy(parent)
    revised = copy.deepcopy(parent)
    revised['allowed_variables']['focal_length_mm'] = [100, 150]
    assert len(build_plan(revised, parent)['candidates']) == 2
    assert parent == before


def test_phase_only_revision_keeps_geometry():
    parent = validate_spec(specimen('diffraction'))
    revised = copy.deepcopy(parent)
    revised['allowed_variables']['relative_phase_rad'] = [math.pi]
    candidate = build_plan(revised, parent)['candidates'][0]
    for key, value in parent['known_parameters'].items():
        if key != 'relative_phase_rad':
            assert candidate['parameters'][key] == value


@pytest.mark.parametrize('domain,key', [('gaussian', 'waist_z_mm'), ('gaussian', 'waist_radius_um'),
                                       ('diffraction', 'slit_height_um'), ('diffraction', 'relative_phase_rad')])
def test_missing_physical_facts_are_not_filled_from_templates(domain, key):
    raw = specimen(domain)
    del raw['known_parameters'][key]
    with pytest.raises(ValueError, match='缺少参数'):
        build_plan(raw)


def test_single_slit_has_no_artificial_relative_phase_requirement():
    raw = specimen('diffraction')
    raw['known_parameters']['aperture'] = 'single_slit'
    raw['allowed_variables'] = {}
    raw['locked_parameters'] = []
    for key in ('relative_phase_rad', 'slit_separation_um'):
        del raw['known_parameters'][key]
        del raw['parameter_sources'][key]
    raw['goal'] = {'metric': 'first_zero_mm', 'operator': 'near', 'target': 6.33, 'tolerance': .01, 'unit': 'mm'}
    plan = build_plan(raw)
    assert len(plan['candidates']) == 1
    assert 'relative_phase_rad' not in plan['candidates'][0]['parameters']
    assert 'slit_separation_um' not in plan['candidates'][0]['parameters']


@pytest.mark.parametrize('budget', [{'max_candidates': 2}, {'max_fast_evaluations': 2},
                                  {'max_meep_validations': 3}, {'max_fdtd': 7},
                                  {'worker_seconds': 61}, {'worker_memory_mib': 1025},
                                  {'output_mib': 65}, {'worker_seconds': 0},
                                  {'max_candidates': True}, {'unlimited': True}])
def test_resource_budget_is_an_enforced_plan_limit(budget):
    raw = specimen('diffraction')
    raw['resource_budget'].update(budget)
    with pytest.raises(ValueError):
        build_plan(raw)


@pytest.mark.parametrize('field,value', [('resource_budget', []), ('resource_budget', None),
                                      ('locked_parameters', [{}]), ('allowed_variables', []),
                                      ('candidate_bounds', []), ('parameter_sources', None),
                                      ('schema_version', True)])
def test_malformed_untrusted_fields_are_rejected_as_validation_errors(field, value):
    raw = specimen('gaussian')
    raw[field] = value
    with pytest.raises(ValueError):
        validate_spec(raw)


def test_candidate_bounds_are_real_constraints():
    raw = specimen('gaussian')
    raw['candidate_bounds'] = {'focal_length_mm': {'min': 100, 'max': 150}}
    with pytest.raises(ValueError, match='边界'):
        build_plan(raw)


def test_duplicate_catalog_entries_do_not_spend_duplicate_work():
    raw = specimen('gaussian')
    raw['allowed_variables']['focal_length_mm'] = [100, 100]
    with pytest.raises(ValueError, match='重复'):
        build_plan(raw)


def test_film_single_point_goal_is_actually_sampled():
    plan = build_plan(specimen('film'))
    for candidate in plan['candidates']:
        assert .633 in candidate['parameters']['wavelengths_um']
        assert candidate['parameters']['wavelengths_um'].count(.633) == 1


def test_nearby_sample_does_not_substitute_for_the_exact_goal_wavelength():
    raw = specimen('film')
    raw['known_parameters']['wavelengths_um'] = [.5, .633 + 5e-13, .8]
    raw['parameter_sources']['wavelengths_um'] = {'quote': 'explicit test samples', 'unit': 'um'}
    plan = build_plan(raw)
    axis = plan['candidates'][0]['parameters']['wavelengths_um']
    assert .633 in axis
    assessed = assess({'data': {'wavelengths_um': axis, 'R': [.1]*len(axis)}}, plan['goal'])
    assert assessed['value'] == .1


def test_full_wavelength_grid_cannot_silently_overrun_budget():
    raw = specimen('film')
    raw['known_parameters']['wavelengths_um'] = [.5 + i*.0015 for i in range(201)]
    raw['goal']['wavelength_um'] = .6331
    raw['parameter_sources']['wavelengths_um'] = {'quote': 'explicit 201 point test grid', 'unit': 'um'}
    with pytest.raises(ValueError, match='201'):
        build_plan(raw)


@pytest.mark.parametrize('payload', [[], None, True, 'text', {'spec': []}, {'spec': 2}, {'spec': 'text'}])
def test_bad_model_json_shape_is_retained_as_a_stopped_draft(payload):
    client = ReturnedJSON(payload)
    result = plan_from_text('明确资料，但需要有效结构才能执行。', client=client, ident='shape-test')
    assert len(client.requests) == 1
    assert not result.get('plan')
    assert result.get('questions')
    assert result.get('actual_model_calls') == 0  # test double, never a live request


def test_ai_cannot_invent_a_source_quote():
    client = ReturnedJSON({'spec': specimen('gaussian'), 'questions': []})
    result = plan_from_text('我的资料尚未包含束腰位置。', client=client, ident='quote-test')
    assert result['validation_error']
    assert not result.get('plan')
    assert '逐字' in result['questions'][0]


def test_local_free_text_stops_instead_of_faking_ai_understanding():
    result = plan_from_text('只有光束直径一毫米，帮我找到最小光斑。')
    assert not result.get('plan')
    assert result['actual_model_calls'] == 0
    assert result['questions']


def test_optimizer_does_not_fabricate_a_target_pass():
    result = assess({'metrics': {'screen_radius_um': 40}}, {'metric': 'screen_radius_um', 'operator': 'minimize'})
    assert result['met'] is None
    assert result['optimization_only'] is True


def test_goal_cannot_use_plot_interpolation():
    result = {'data': {'wavelengths_um': [.6, .7], 'R': [.5, .9]}}
    goal = {'metric': 'reflectance', 'operator': '>=', 'target': .8, 'wavelength_um': .633}
    with pytest.raises(ValueError, match='实际采样'):
        assess(result, goal)


def test_failed_numerical_candidate_is_never_promoted_for_its_better_number():
    rows = [
        {'id': 'c-good', 'status': 'RUN_COMPLETED', 'all_checks_passed': True, 'goal': {'value': 40}},
        {'id': 'c-bad', 'status': 'RUN_COMPLETED', 'all_checks_passed': False, 'goal': {'value': 1}},
        {'id': 'c-incomplete', 'status': 'RUN_FAILED', 'all_checks_passed': True, 'goal': {'value': 0}},
    ]
    assert rank(rows, {'metric': 'screen_radius_um', 'operator': 'minimize'}) == ['c-good']


def test_unknown_tools_and_model_code_are_not_executable_plan_fields():
    raw = specimen('gaussian')
    raw['domain'] = 'os.system'
    with pytest.raises(ValueError):
        build_plan(raw)
    raw = specimen('gaussian')
    raw['python_code'] = 'print("untrusted")'
    with pytest.raises(ValueError):
        build_plan(raw)
def test_catalog_baseline_normalization_does_not_invent_beam_facts():
    from photonguard.experiments.planner import normalize_catalog_baselines,templates
    s=next(t['spec'] for t in templates() if t['domain']=='gaussian')
    del s['known_parameters']['focal_length_mm']
    normalized,changes=normalize_catalog_baselines(s)
    assert normalized['known_parameters']['focal_length_mm']==100
    assert changes[0]['basis']=='EXPLICIT_PARENT_OR_FIRST_CATALOG_CANDIDATE_NOT_NEW_MEASUREMENT'
    del s['known_parameters']['waist_z_mm']
    normalized,_=normalize_catalog_baselines(s)
    assert 'waist_z_mm' not in normalized['known_parameters']


def test_separate_source_spans_preserve_units_and_full_catalog():
    from photonguard.experiments.planner import _validate_quotes
    raw=specimen('gaussian')
    raw['parameter_sources']['focal_length_mm']={'quotes':['焦距10、15 cm','另有200 mm'],'unit':'mm'}
    text=raw['parameter_sources']['wavelength_nm']['quote']+'\n焦距10、15 cm。暂不改变屏幕位置。\n另有200 mm。'
    assert _validate_quotes(raw,text)==raw
    assert validate_spec(raw)['parameter_sources']['focal_length_mm']['quotes']==['焦距10、15 cm','另有200 mm']
    raw['allowed_variables']['focal_length_mm'].append(300)
    with pytest.raises(ValueError,match='数值或单位'):
        _validate_quotes(raw,text)


@pytest.mark.parametrize('source',[
    {'quote':'焦距10、15 cm另有200 mm','unit':'mm'},
    {'quotes':['焦距10、15 cm','另有300 mm'],'unit':'mm'},
])
def test_source_splicing_or_altering_original_text_is_rejected(source):
    from photonguard.experiments.planner import _validate_quotes
    raw=specimen('gaussian')
    text=raw['parameter_sources']['wavelength_nm']['quote']+'\n焦距10、15 cm。保持其余参数。\n另有200 mm。'
    raw['parameter_sources']['focal_length_mm']=source
    with pytest.raises(ValueError,match='逐字'):
        _validate_quotes(raw,text)


@pytest.mark.parametrize('source',[
    {'quote':'633 nm','quotes':['633 nm'],'unit':'nm'},
    {'quotes':[],'unit':'nm'},
    {'quotes':['633 nm']*9,'unit':'nm'},
    {'quotes':[None],'unit':'nm'},
])
def test_malformed_multiple_source_spans_are_rejected(source):
    raw=specimen('gaussian');raw['parameter_sources']['wavelength_nm']=source
    with pytest.raises(ValueError):validate_spec(raw)


def test_film_source_records_distinguish_fast_and_independent_values():
    goal={'metric':'reflectance','operator':'>=','target':.8,'wavelength_um':.633}
    fast=assess({'engine':{'name':'tmm'},'data':{'wavelengths_um':[.633],'R':[.91]}},goal)
    independent=assess({'engine':{'name':'Meep DFT flux'},'data':{'wavelengths_um':[.633],'R':[.909]}},goal)
    assert fast['value']==.91 and independent['value']==.909
    assert fast['source']['kind']=='TMM_SAMPLE'
    assert independent['source']['kind']=='MEEP_SAMPLE'
    assert fast['source']['field']=='data.R[0]'
    assert fast['source']['interpolation_used'] is False


def test_formula_and_discrete_band_metrics_are_not_claimed_as_image_or_continuous_proof():
    geometry=assess({'metrics':{'fringe_period_mm':1}}, {'metric':'fringe_period_mm','operator':'minimize'})
    assert geometry['unit']=='mm'
    assert geometry['source']['kind']=='ANALYTIC_GEOMETRY'
    assert geometry['source']['measured_from_image'] is False
    band=assess({'engine':{'name':'tmm'},'metrics':{'reflectance_min':.5}}, {'metric':'reflectance_min','operator':'maximize'})
    assert band['source']['continuous_band_guarantee'] is False


def test_omitted_adjacent_catalog_citation_is_completed_without_changing_parameters():
    from photonguard.experiments.planner import complete_adjacent_catalog_quotes,_validate_quotes
    raw=specimen('gaussian')
    raw['parameter_sources']['focal_length_mm']={'quote':'透镜焦距基准100 mm','unit':'mm'}
    text=raw['parameter_sources']['wavelength_nm']['quote']+'\n透镜焦距基准100 mm，仅可比较100、150、200 mm三种焦距，其余固定。'
    expanded,changes=complete_adjacent_catalog_quotes(raw,text)
    assert expanded['known_parameters']==raw['known_parameters']
    assert expanded['allowed_variables']==raw['allowed_variables']
    assert expanded['parameter_sources']['focal_length_mm']['quote']=='透镜焦距基准100 mm，仅可比较100、150、200 mm'
    assert changes[0]['parameter_values_changed'] is False
    assert _validate_quotes(expanded,text)==expanded


@pytest.mark.parametrize('following',[
    '。屏幕位置候选100、150、200 mm。',
    '，屏幕位置候选100、150、200 mm。',
    '，仅可比较100、150 mm。',
    '，最大200 mm，最小100 mm，其余150 mm。',
])
def test_catalog_citation_completion_never_borrows_unrelated_or_unlisted_values(following):
    from photonguard.experiments.planner import complete_adjacent_catalog_quotes
    raw=specimen('gaussian')
    raw['parameter_sources']['focal_length_mm']={'quote':'透镜焦距基准100 mm','unit':'mm'}
    text='透镜焦距基准100 mm'+following
    expanded,changes=complete_adjacent_catalog_quotes(raw,text)
    assert expanded==raw and changes==[]


@pytest.mark.parametrize('domain,key,value',[
    ('diffraction','slit_width_um',300),('diffraction','grid_size',1024),
    ('gaussian','focal_length_mm',0),('gaussian','waist_radius_um',.5),
])
def test_unsupported_candidates_stop_before_creating_an_executable_plan(domain,key,value,monkeypatch):
    from photonguard.experiments import optics
    monkeypatch.setattr(optics,'_fft_field',lambda *a:pytest.fail('plan validation must not run FFT'))
    raw=specimen(domain);raw['known_parameters'][key]=value
    if key in raw['allowed_variables']:raw['allowed_variables'][key]=[value]
    with pytest.raises(ValueError):build_plan(raw)


def test_revision_cannot_escape_original_catalog_by_removing_variable():
    parent=validate_spec(specimen('gaussian'));raw=copy.deepcopy(parent)
    raw['allowed_variables']={};raw['known_parameters']['focal_length_mm']=120
    with pytest.raises(ValueError,match='原目录'):build_plan(raw,parent)
    raw['known_parameters']['focal_length_mm']=150
    assert len(build_plan(raw,parent)['candidates'])==1


def test_wavelength_candidates_have_their_own_physical_inputs():
    raw=specimen('diffraction');raw['allowed_variables']={'wavelength_nm':[488,633]}
    raw['locked_parameters'].remove('wavelength_nm')
    plan=build_plan(raw)
    assert [c['parameters']['wavelength_nm'] for c in plan['candidates']]==[488,633]
    assert all(c['parameters']['slit_separation_um']==126.6 for c in plan['candidates'])


def test_wrong_goal_unit_and_single_slit_fringe_metric_cannot_run():
    raw=specimen('gaussian');raw['goal']['unit']='mm'
    with pytest.raises(ValueError,match='单位'):build_plan(raw)
    raw=specimen('diffraction');raw['known_parameters']['aperture']='single_slit'
    raw['goal']={'metric':'fringe_period_mm','operator':'minimize'}
    with pytest.raises(ValueError,match='不适用于单缝'):build_plan(raw)


def test_omitted_aperture_enum_uses_only_an_explicit_unambiguous_name():
    from photonguard.experiments.planner import normalize_explicit_aperture
    raw=specimen('diffraction');del raw['known_parameters']['aperture']
    normalized,changes=normalize_explicit_aperture(raw,'研究双缝的理想透镜后焦面。其余参数不变。')
    assert normalized['known_parameters']['aperture']=='double_slit'
    assert normalized['parameter_sources']['aperture']['quote']=='研究双缝的理想透镜后焦面'
    assert changes
    for text in ['不知道是否为双缝。','不是双缝。','单缝与双缝都需要讨论。','可能为双缝。','未提供孔径类型。']:
        normalized,changes=normalize_explicit_aperture(raw,text)
        assert 'aperture' not in normalized['known_parameters'] and not changes
