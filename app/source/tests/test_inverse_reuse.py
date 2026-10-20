"""Offline reuse contracts; numerical examples are separately run end to end."""
import json
from pathlib import Path

import pytest

from photonguard.core import digest
from photonguard.experiments import inverse_models as m, reuse

EXAMPLES = Path(__file__).parents[1] / 'examples/inverse'


def spec(name='gaussian'):
    return json.loads((EXAMPLES / (name + '-plan.json')).read_text())


def strategy_state(name='gaussian'):
    s = spec(name)
    groups = [{'dataset': {'x_mm': [-40., 120.]}}]
    return reuse.public_state(groups, s, {'id': 'saved'}, {}, {'plans': []})


def test_strategy_checks_state_range_points_and_reason():
    state = strategy_state()
    r = {'input_sha256': state['sha256'], 'positions_mm': [-150., -75., 0., 75., 150.], 'reason': 'Fixed public positions'}
    assert reuse.validate_strategy(state, r) == r
    for changed in ({'input_sha256': 'stale'}, {'positions_mm': [-300., -75., 0., 75., 150.]},
                    {'positions_mm': [-150., 0., 0., 75., 150.]}, {'positions_mm': [0., 1.]},
                    {'positions_mm': [-150., -75., float('nan'), 75., 150.]}, {'reason': ''}):
        with pytest.raises(ValueError):
            reuse.validate_strategy(state, r | changed)


def test_strategy_cannot_extend_forbidden_scan_or_add_film_wavelength():
    state = strategy_state()
    state['constraints']['allow_extension'] = False
    r = {'input_sha256': state['sha256'], 'positions_mm': [-150., -75., 0., 75., 150.], 'reason': 'Not approved'}
    with pytest.raises(ValueError, match='extension'):
        reuse.validate_strategy(state, r)
    film = strategy_state('film')
    r = {'input_sha256': film['sha256'], 'wavelengths_nm': [700.], 'reason': 'Unavailable source'}
    with pytest.raises(ValueError, match='catalogue'):
        reuse.validate_strategy(film, r)
    assert reuse.validate_strategy(film, r | {'wavelengths_nm': [660.]})['wavelengths_nm'] == [660.]


def test_public_strategy_has_no_future_data_or_generator_truth():
    s = spec()
    state = reuse.public_state([], s, {'id': 'actual'}, {}, {'plans': []})
    assert set(state) == {'schema', 'groups', 'settings', 'constraints', 'research_goal', 'fit_result', 'profiles', 'proposal', 'sha256'}
    state['settings']['fixed']['m2'] = 2
    assert s['settings']['fixed']['m2'] == 1


def test_explicit_approval_precedes_reading_input_or_creating_directory(tmp_path):
    with pytest.raises(ValueError, match='approve'):
        reuse.run(tmp_path / 'missing.csv', {}, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
    with pytest.raises(ValueError, match='approval'):
        reuse.followup(tmp_path / 'missing', tmp_path / 'missing.csv')


def test_plan_cannot_import_strategy_code_or_switch_model():
    s = spec()
    with pytest.raises(ValueError):
        reuse.validate_spec(s | {'strategy_module': 'uploaded_code'})
    with pytest.raises(ValueError, match='model'):
        reuse.validate_spec(s, m.FILM)


def test_bad_scan_constraints_stop_before_any_solver_or_output(tmp_path):
    s = spec()
    s['constraints']['points'] = 2
    initial = tmp_path / 'initial.csv'
    initial.write_text('z_mm,radius_1e2_um\n-40,205\n0,120\n40,82\n80,145\n120,235\n')
    with pytest.raises(ValueError):
        reuse.run(initial, s, tmp_path / 'never-created', approve=True)
    assert not (tmp_path / 'never-created').exists()


def test_declared_acquisition_metadata_is_not_invented_or_shared():
    s = spec()
    s['acquisition'] = {'observation': {'kind': 'POINT_SAMPLE'}, 'noise': {
        'sigma': .5, 'independent': True, 'source': 'TEACHING_GENERATOR',
        'reference': 'Disclosed public Gaussian generator', 'acquisition_id': 'scan-1'}}
    s['followup_acquisition'] = {'observation': {'kind': 'UNKNOWN'}}
    initial = reuse._group({'rows': 5}, s, 'initial.csv')
    follow = reuse._group({'rows': 5}, s, 'followup.csv', followup=True)
    assert initial['noise']['acquisition_id'] == 'scan-1'
    assert 'noise' not in follow
    assert follow['observation'] == {'kind': 'UNKNOWN'}
    initial['noise']['sigma'] = 100
    assert s['acquisition']['noise']['sigma'] == .5


def test_film_rejects_slit_spatial_kernel_before_computation(tmp_path):
    s = spec('film')
    s['acquisition'] = {'observation': {'kind': 'CALIBRATED_INTENSITY_AVERAGE', 'kernel': {
        'offsets_mm': [0.], 'weights': [1.], 'source': 'USER_DECLARED',
        'reference': 'A spatial intensity kernel cannot calibrate wavelength reflectance'}}}
    with pytest.raises(ValueError, match='双缝'):
        reuse.run(EXAMPLES / 'data/film-initial.csv', s, tmp_path / 'never-created', approve=True)
    assert not (tmp_path / 'never-created').exists()


def make_saved(tmp_path, monkeypatch):
    """Focus on state safety; real worker physics is exercised by the CLI runs."""
    initial = tmp_path / 'initial.csv'
    initial.write_text('z_mm,radius_1e2_um\n-40,205\n0,120\n40,82\n80,145\n120,235\n')
    def solve(folder, state, groups, operation='fit', reference=None):
        state['reserved']['fits'] += 1
        state['reserved']['residual_calls_reserved'] += 30000
        state['actual_residual_calls'] += 7
        return {'id': 'fit' + str(len(groups)), 'estimated_parameters': {'waist_radius_um': 82., 'waist_z_mm': 35.}, 'warnings': []}
    def propose(*args):
        p = {'plans': [{'id': 'baseline', 'prediction_x_mm': [-150., -75., 0., 75., 150.]}], 'recommended_id': 'baseline'}
        p['sha256'] = digest(p)
        return p
    monkeypatch.setattr(reuse, '_solve', solve)
    monkeypatch.setattr(reuse, 'propose', propose)
    folder = tmp_path / 'saved'
    reuse.run(initial, spec(), folder, approve=True)
    return folder, initial


def test_resume_uses_saved_fit_and_preserves_cumulative_allowance(tmp_path, monkeypatch):
    folder, _ = make_saved(tmp_path, monkeypatch)
    follow = tmp_path / 'next.csv'
    follow.write_text('z_mm,radius_1e2_um\n-150,440\n-75,290\n0,120\n75,132\n150,300\n')
    state = reuse.followup(folder, follow, approve=True)
    assert state['reserved']['fits'] == 2
    assert state['reserved']['followups'] == 1
    assert state['actual_residual_calls'] == 14
    assert state['initial_fit']['id'] == 'fit1'
    assert state['joint_fit']['id'] == 'fit2'
    with pytest.raises(ValueError, match='ready plan'):
        reuse.followup(folder, follow, approve=True)
    assert reuse.inspect(folder)['reserved']['fits'] == 2


def test_duplicate_or_wrong_coordinate_csv_consumes_no_followup(tmp_path, monkeypatch):
    folder, initial = make_saved(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='Duplicating'):
        reuse.followup(folder, initial, approve=True)
    wrong = tmp_path / 'wrong.csv'
    wrong.write_text('z_mm,radius_1e2_um\n-149,440\n-75,290\n0,120\n75,132\n150,300\n')
    with pytest.raises(ValueError, match='coordinates'):
        reuse.followup(folder, wrong, approve=True)
    assert reuse.inspect(folder)['reserved']['followups'] == 0


def test_saved_data_change_invalidates_read_and_resume(tmp_path, monkeypatch):
    folder, _ = make_saved(tmp_path, monkeypatch)
    with (folder / 'initial.csv').open('a') as f:
        f.write('121,235\n')
    with pytest.raises(ValueError, match='evidence changed'):
        reuse.inspect(folder)


def test_worker_failure_keeps_reserved_resources(tmp_path, monkeypatch):
    s = spec()
    raw = 'z_mm,radius_1e2_um\n-40,205\n0,120\n40,82\n80,145\n120,235\n'
    csv = tmp_path / 'initial.csv'
    csv.write_text(raw)
    class Failed:
        returncode = 9
    monkeypatch.setattr(reuse.subprocess, 'run', lambda *args, **kwargs: Failed())
    folder = tmp_path / 'stopped'
    with pytest.raises(ValueError, match='worker stopped'):
        reuse.run(csv, s, folder, approve=True)
    state = reuse.inspect(folder)
    assert state['status'] == 'STOPPED_WITH_RESERVED_BUDGET'
    assert state['reserved']['fits'] == 1
    assert state['reserved']['residual_calls_reserved'] == 30000
    assert state['model_requests'] == 0


def test_failed_replacement_keeps_initial_result_and_budget(tmp_path, monkeypatch):
    make_saved(tmp_path, monkeypatch)
    def fail(*args):
        raise ValueError('strategy outside range')
    monkeypatch.setattr(reuse, 'propose', fail)
    failed = tmp_path / 'strategy-failed'
    with pytest.raises(ValueError, match='outside range'):
        reuse.run(tmp_path / 'initial.csv', spec(), failed, approve=True)
    state = reuse.inspect(failed)
    assert state['status'] == 'STOPPED_WITH_RESERVED_BUDGET'
    assert state['initial_fit']['id'] == 'fit1'
    assert state['reserved']['fits'] == 1
