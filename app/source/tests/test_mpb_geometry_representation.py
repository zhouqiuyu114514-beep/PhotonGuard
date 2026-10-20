"""Continuous geometry checks using MPB objects, with no native mode solver."""
import copy
from fractions import Fraction
import json

import numpy as np
import pytest

from photonguard.core import load
from photonguard.materials.ln_sellmeier import dielectric_tensor


@pytest.fixture
def geometry_run(monkeypatch, tmp_path):
    from photonguard.adapters import mpb_worker as worker
    captured = []

    class NoSolver:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def solve_kpoint(self, *args, **kwargs):
            pytest.fail('Geometry tests must not solve an eigenproblem')

        def find_k(self, *args):
            # Deliberately no capture callback or numerical result.
            return []

    monkeypatch.setattr(worker.mpb, 'ModeSolver', NoSolver)
    monkeypatch.setattr(worker, 'runtime_build_fingerprint', lambda: {'kind': 'GEOMETRY_ONLY_MOCK'})

    def run(requirements, **flags):
        before = copy.deepcopy(requirements)
        folder = tmp_path / str(len(captured))
        folder.mkdir()
        result = worker.solve(1.55, 80, [4, 6], folder, requirements, **flags)
        assert requirements == before
        assert json.loads((folder / 'result.json').read_text()) == result
        assert result['solver_counts']['eigenproblem_solves'] == 0
        return worker.mp, captured[-1], result

    return run


def requirements():
    return load('examples/mode_qpm/ridge.task.json')['requirements']


def material_tensor(medium):
    d, o = medium.epsilon_diag, medium.epsilon_offdiag
    return np.array([[d.x, o.x, o.y], [o.x, d.y, o.z], [o.y, o.z, d.z]])


def sampled_tensor(mp, config, point):
    # Meep's geometry list uses the last containing object at an overlap.
    medium = config['default_material']
    for obj in config['geometry']:
        if mp.is_point_in_object(mp.Vector3(*point, 0), obj):
            medium = obj.material
    return material_tensor(medium)


@pytest.mark.parametrize('film,slab,width', [(0.6, 0.3, 1.4), (0.2, 0.001, 0.5), (1.2, 1.199, 2.5)])
@pytest.mark.parametrize('turned', [False, True])
def test_cap_is_same_continuous_union_and_rotates_with_material(geometry_run, film, slab, width, turned):
    r = requirements()
    r.update(film_thickness_um=film, slab_thickness_um=slab, ridge_width_um=width)
    mp, config, result = geometry_run(r, quarter_turn=turned)
    substrate, residual, cap = config['geometry']
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    tensor = np.asarray(dielectric_tensor(1.55)['laboratory_epsilon'])
    expected_tensor = rotation @ tensor @ rotation.T if turned else tensor
    assert material_tensor(cap.material) == pytest.approx(expected_tensor)
    assert cap.material is residual.material
    assert [cap.size.x, cap.size.y] == pytest.approx([film - slab, width] if turned else [width, film - slab])
    assert [cap.center.x, cap.center.y] == pytest.approx([-slab / 2, 0] if turned else [0, slab / 2])
    height = 4 if turned else 6
    assert (substrate.size.x if turned else substrate.size.y) == pytest.approx(height / 2 - film / 2)

    # Exact real-number interval proof, distinct from finite floating-point samples:
    # slab [-f/2, -f/2+s], cap [-f/2+s, f/2] join without interior overlap.
    f, s = Fraction(str(film)), Fraction(str(slab))
    assert s / 2 - (f - s) / 2 == -f / 2 + s
    assert s / 2 + (f - s) / 2 == f / 2
    assert -f / 2 < -f / 2 + s < f / 2

    # An independent piecewise material oracle represents the old full-film ridge
    # union. Near-interface samples avoid ambiguous 1-ulp surface classifications.
    delta = 1e-9
    xs = [p + d for p in (-width / 2, 0, width / 2) for d in (-delta, delta)]
    ys = [p + d for p in (-film / 2, -film / 2 + slab, film / 2) for d in (-delta, delta)]
    points = [(x, y) for x in xs for y in ys]
    points += list(np.random.default_rng(42).uniform(-1.5, 1.5, (512, 2)))
    for x, y in points:
        crystal = y >= -film / 2 and (y <= -film / 2 + slab or (abs(x) <= width / 2 and y <= film / 2))
        expected = expected_tensor if crystal else np.eye(3) * (r['bottom_index'] ** 2 if y < -film / 2 else r['top_index'] ** 2)
        point = (-y, x) if turned else (x, y)
        assert sampled_tensor(mp, config, point) == pytest.approx(expected)
    assert result['geometry'] == 'rectangular-ridge'
    assert result['geometry_representation'] == 'non-overlapping-slab-cap-v1'
    assert result['quarter_turn_calibration_only'] is turned
    assert config['mesh_size'] == 7 and config['num_bands'] == 4
    assert config['tolerance'] == 1e-9 and config['deterministic'] and config['optimize_grid_size']


@pytest.mark.parametrize('turned', [False, True])
def test_old_ridge_bottom_corners_are_only_a_flat_substrate_face(geometry_run, turned):
    r = requirements()
    mp, config, _ = geometry_run(r, quarter_turn=turned)
    _, residual, cap = config['geometry']
    bottom = -r['film_thickness_um'] / 2
    for corner_x in (-r['ridge_width_um'] / 2, r['ridge_width_um'] / 2):
        # The cap has no object edge or corner at either former ridge bottom.
        point = (-bottom, corner_x) if turned else (corner_x, bottom)
        assert not mp.is_point_in_object(mp.Vector3(*point, 0), cap)
        assert mp.is_point_in_object(mp.Vector3(*point, 0), residual)
        for dy in (-1e-9, 1e-9):
            row = []
            for dx in (-1e-9, 0, 1e-9):
                x, y = corner_x + dx, bottom + dy
                row.append(sampled_tensor(mp, config, (-y, x) if turned else (x, y)))
            assert np.array_equal(row[0], row[1]) and np.array_equal(row[1], row[2])
            expected = material_tensor(residual.material) if dy > 0 else np.eye(3) * r['bottom_index'] ** 2
            assert row[0] == pytest.approx(expected)


def test_symmetric_slab_calibration_keeps_its_single_full_film(geometry_run):
    r = requirements()
    mp, config, result = geometry_run(r, calibration_slab=True)
    assert len(config['geometry']) == 1
    layer = config['geometry'][0]
    assert layer.size.x == mp.inf and layer.size.y == r['film_thickness_um']
    assert layer.center == mp.Vector3()
    assert material_tensor(config['default_material']) == pytest.approx(np.eye(3) * 1.44 ** 2)
    assert config['geometry_lattice'].size == mp.Vector3(0, 6, 0)
    assert result['geometry'] == 'symmetric-slab-calibration'
    assert result['geometry_representation'] == 'single-full-film-slab-v1'
    assert result['domain_um'] == [0, 6, 0]


def test_collapsed_slab_cannot_be_quarter_turned(geometry_run):
    with pytest.raises(ValueError, match='collapsed-axis'):
        geometry_run(requirements(), calibration_slab=True, quarter_turn=True)
