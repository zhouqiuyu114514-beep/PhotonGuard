"""Control-path tests only; never launch physical or model jobs."""
from pathlib import Path
import hashlib
import json
import pytest
from tools import study_equivalent_cap as study


def test_baseline_rejects_modified_old_field_even_if_manifest_file_is_unchanged(tmp_path):
    field = tmp_path / 'old-field.npz'
    field.write_bytes(b'old immutable field')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{}')
    plan = {'baseline': {'folder': str(tmp_path), 'manifest_sha256': study.sha(manifest)},
            'old_manifest_files': {'old-field.npz': study.sha(field)}}
    study.verify_baseline(plan)
    field.write_bytes(b'modified field')
    with pytest.raises(ValueError, match='OLD_FIELDS_CHANGED'):
        study.verify_baseline(plan)


def test_existing_execution_marker_prevents_worker_replay(tmp_path, monkeypatch):
    plan = {'kind': 'SYNTHETIC_CONTROL_TEST'}
    study.save(tmp_path / 'plan.json', plan)
    study.save(tmp_path / 'execution-started.json', {'attempts': 1})
    monkeypatch.setattr(study, 'make_plan', lambda: plan)
    def forbidden(*args, **kwargs):
        pytest.fail('A worker must not start twice')
    monkeypatch.setattr(study.subprocess, 'run', forbidden)
    with pytest.raises(ValueError, match='NO_RETRY_OR_REPLAY'):
        study.execute(tmp_path, study.digest(plan))


def test_exact_plan_digest_checked_before_any_worker_or_financial_access(tmp_path, monkeypatch):
    study.save(tmp_path / 'plan.json', {'kind': 'SYNTHETIC_CONTROL_TEST'})
    monkeypatch.setattr(study, 'make_plan', lambda: pytest.fail('Must reject digest before source IO'))
    with pytest.raises(ValueError, match='EXACT_PLAN_REVIEW_REQUIRED'):
        study.execute(tmp_path, '0' * 64)


def test_atomic_reservation_cannot_be_overwritten_or_released(tmp_path):
    path = tmp_path / 'reservation.json'
    study.save(path, {'output_bytes_reserved': study.RESERVE})
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        study.save(path, {'output_bytes_reserved': 0})
    assert path.read_bytes() == original


def test_independent_weight_preserves_fractional_material_with_integer_air_index():
    import numpy as np
    from tools.verify_equivalent_cap import direct_weight
    fields = {'x_um': np.array([0., 1.]), 'y_um': np.array([0., 1.])}
    requirements = {'film_thickness_um': .6, 'slab_thickness_um': .3,
                    'ridge_width_um': 1.4, 'top_index': 1, 'bottom_index': 1.44}
    material = {'laboratory_epsilon': np.diag([4.569161256391351, 4.889011892589024, 4.889011892589024]).tolist()}
    weight = direct_weight(fields, requirements, material)
    np.testing.assert_array_equal(weight[0, 0], np.diag(material['laboratory_epsilon']))
    assert weight.dtype.kind == 'f'
