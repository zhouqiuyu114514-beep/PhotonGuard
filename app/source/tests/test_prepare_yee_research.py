"""Preparation only: do not import or execute numerical workers."""
import hashlib
import json
import shutil

import pytest

from tools import prepare_yee_research as prepare
from research.independent_reference import run_one as launch


@pytest.mark.parametrize('profile,count,cap', [
    ('calibration', 4, 1), ('ridge', 8, 1), ('ridge80', 4, 2),
])
def test_prepare_freezes_exact_sources_and_only_registered_cases(tmp_path, profile, count, cap):
    folder = tmp_path / profile
    result = prepare.prepare(folder, profile)
    plan = json.loads((folder / 'plan.json').read_text())
    freeze = json.loads((folder / 'freeze.json').read_text())
    original = json.loads((prepare.SOURCE / 'profiles.json').read_text())[profile]
    assert result['status'] == 'PREPARED_NOT_EXECUTED'
    assert result['solver_calls'] == result['API_calls'] == 0
    assert plan['cases'] == original['cases']
    assert len(plan['cases']) == plan['max_registered_attempts'] == count
    assert plan['per_worker_address_space_bytes'] == cap * 1024**3
    assert plan['per_worker_wall_seconds'] == 60
    assert plan['available_memory_fraction_max'] == .5
    assert plan['locked_long_device_length_um'] == 1000
    assert plan['max_worker_attempts'] == (4 if profile == 'ridge80' else 12)
    assert (folder / 'worker.py').read_bytes() == (prepare.SOURCE / original['worker']).read_bytes()
    for name, expected in freeze['files'].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected
    assert freeze['files']['worker.py'] == prepare.WORKER_SHA256[original['worker']]
    assert len(result['commands']) == count
    assert all(command[-3:] == [str(folder / 'run_one.py'), '--id', case['id']]
               for command, case in zip(result['commands'], plan['cases']))
    assert not list(folder.glob('*.started.json'))
    assert not list(folder.glob('*.npz'))


@pytest.mark.parametrize('profile', ['calibration', 'ridge', 'ridge80'])
def test_fixed_profile_plan_bytes_are_deterministic_across_directories(tmp_path, profile):
    left, right = tmp_path / 'left', tmp_path / 'right'
    prepare.prepare(left, profile)
    prepare.prepare(right, profile)
    for name in ['worker.py', 'run_one.py', 'plan.json', 'freeze.json']:
        assert (left / name).read_bytes() == (right / name).read_bytes()


@pytest.mark.parametrize('kind', ['empty-directory', 'populated-directory', 'file'])
def test_existing_output_is_never_overwritten(tmp_path, kind):
    folder = tmp_path / 'existing'
    if kind == 'file':
        folder.write_bytes(b'original')
    else:
        folder.mkdir()
        if kind == 'populated-directory':
            (folder / 'sentinel').write_bytes(b'original')
    before = folder.read_bytes() if folder.is_file() else {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(FileExistsError):
        prepare.prepare(folder)
    after = folder.read_bytes() if folder.is_file() else {p.name: p.read_bytes() for p in folder.iterdir()}
    assert after == before


@pytest.mark.parametrize('source_name', ['profiles.json', 'yee_reference_v2.py', 'yee_reference_r80_v4.py'])
def test_modified_source_is_rejected_before_output_creation(tmp_path, monkeypatch, source_name):
    source = tmp_path / 'sources'
    shutil.copytree(prepare.SOURCE, source)
    (source / source_name).write_bytes((source / source_name).read_bytes() + b'\n')
    monkeypatch.setattr(prepare, 'SOURCE', source)
    folder = tmp_path / 'result'
    profile = 'ridge80' if source_name == 'yee_reference_r80_v4.py' else 'calibration'
    with pytest.raises(ValueError, match='hash mismatch'):
        prepare.prepare(folder, profile)
    assert not folder.exists()


def test_unknown_profile_cannot_add_numerical_settings(tmp_path):
    with pytest.raises(ValueError, match='Unknown research profile'):
        prepare.prepare(tmp_path / 'out', 'ridge96')
    assert not (tmp_path / 'out').exists()


def test_dangling_symlink_is_not_followed_or_replaced(tmp_path):
    folder = tmp_path / 'out'
    target = tmp_path / 'missing'
    folder.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        prepare.prepare(folder)
    assert folder.is_symlink()
    assert not target.exists()


def test_default_profile_is_calibration(tmp_path):
    result = prepare.prepare(tmp_path / 'default')
    assert result['profile'] == 'calibration'
    assert result['registered_cases'] == 4


@pytest.mark.parametrize('boundary,exception', [
    ('changed-worker', SystemExit), ('active-lock', FileExistsError),
    ('failed-monitor', RuntimeError), ('incomplete-monitor', RuntimeError),
    ('unknown-id', SystemExit),
])
def test_launcher_rejection_boundaries_never_dispatch(tmp_path, monkeypatch, boundary, exception):
    folder = tmp_path / 'prepared'
    prepare.prepare(folder)
    case = 'slab-iso-512'
    if boundary == 'changed-worker':
        with (folder / 'worker.py').open('ab') as stream:
            stream.write(b'\n')
    elif boundary == 'active-lock':
        (folder / '.active-worker.lock').write_text('existing owner\n')
    elif boundary == 'failed-monitor':
        (folder / 'prior.monitor.json').write_text('{"returncode": 1}')
    elif boundary == 'incomplete-monitor':
        (folder / 'prior.monitor-start.json').write_text('{}')
    else:
        case = 'not-registered'
    before = {path.name: path.read_bytes() for path in folder.iterdir()}
    calls = []
    def forbidden_dispatch(*args, **kwargs):
        calls.append(args)
        raise AssertionError('A rejected launch must never dispatch a worker')
    monkeypatch.setattr(launch, '__file__', str(folder / 'run_one.py'))
    monkeypatch.setattr(launch.sys, 'argv', ['run_one.py', '--id', case])
    monkeypatch.setattr(launch.subprocess, 'Popen', forbidden_dispatch)
    with pytest.raises(exception):
        launch.main()
    assert calls == []
    assert {path.name: path.read_bytes() for path in folder.iterdir()} == before
    assert not list(folder.glob('*.started.json'))


def test_output_guard_checks_total_bytes_and_log_limit_without_a_worker(tmp_path):
    plan = {'max_output_bytes': 2 * 1024**2}
    (tmp_path / 'result.npz').write_bytes(b'x' * (2 * 1024**2 - 64 * 1024 + 1))
    assert launch.output_failure(tmp_path, plan) == 'OUTPUT_BUDGET_EXCEEDED'
    (tmp_path / 'result.npz').unlink()
    (tmp_path / 'case.stderr.log').write_bytes(b'x' * (1024**2 + 1))
    assert launch.output_failure(tmp_path, plan) == 'LOG_FILE_LIMIT_EXCEEDED'
