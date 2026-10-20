"""Read-only, no-solver verification of equivalent-cap persisted research evidence.

Only --report is written, exclusively; all project sources and evidence are read.
The selected new column is recomputed using direct same-grid sums rather than
the study's periodic interpolation/overlap implementation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import numpy as np


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def close(actual, expected, label, tolerance=1e-11):
    require(math.isfinite(float(actual)) and math.isfinite(float(expected)), label + ': nonfinite')
    error = abs(float(actual) - float(expected))
    require(error <= tolerance * max(1., abs(float(expected))), label + ': mismatch ' + str(error))
    return error


def overlap(a, b, weight=None):
    w = 1. if weight is None else weight
    inner = np.sum(a.conj() * w * b)
    norm_a = float(np.sum(abs(a)**2 * w))
    norm_b = float(np.sum(abs(b)**2 * w))
    require(norm_a > 0 and norm_b > 0, 'zero field norm')
    return {'squared_normalized_overlap': float(abs(inner)**2 / (norm_a * norm_b)),
            'global_phase_alignment_rad': float(np.angle(inner))}


def direct_weight(fields, requirements, material):
    X, Y = np.meshgrid(fields['x_um'], fields['y_um'], indexing='ij')
    film = requirements['film_thickness_um']
    slab = requirements['slab_thickness_um']
    width = requirements['ridge_width_um']
    weight = np.full(X.shape + (3,), requirements['top_index']**2, dtype=float)
    weight[Y < -film / 2] = requirements['bottom_index']**2
    crystal = ((Y >= -film / 2) & (Y < -film / 2 + slab)) | ((abs(X) < width / 2) & (abs(Y) < film / 2))
    weight[crystal] = np.diag(np.asarray(material['laboratory_epsilon']))
    return weight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    repo, study = args.repo.resolve(), args.study.resolve()
    require(not args.report.exists(), 'report must be new')
    sys.path.insert(0, str(repo))
    from photonguard.mode_numerical_review import load_research_evidence
    from photonguard.core import digest

    top_manifest = read(study / 'manifest.json')
    require(top_manifest.get('not_product_acceptance') is True, 'top manifest research scope')
    top_files = top_manifest['files']
    for required in ('plan.json', 'summary.json'):
        require(required in top_files, 'top manifest missing ' + required)
    for name, expected in top_files.items():
        target = (study / name).resolve()
        require(target.is_relative_to(study), 'top manifest path escape')
        require(sha(target) == expected, 'study file changed: ' + name)
    plan = read(study / 'plan.json')
    summary = read(study / 'summary.json')
    require(summary['plan_sha256'] == digest(plan), 'summary plan binding')
    parent = Path(plan['baseline']['folder'])
    require(sha(parent / 'manifest.json') == plan['baseline']['manifest_sha256'], 'old manifest binding')
    require(read(parent / 'manifest.json')['files'] == plan['old_manifest_files'], 'old file table')
    for name, expected in plan['old_manifest_files'].items():
        target = (parent / name).resolve()
        require(target.is_relative_to(parent.resolve()), 'old manifest path escape')
        require(sha(target) == expected, 'old file changed: ' + name)
    for name, expected in plan['carry_forward']['historical_cap_tensor_results'].items():
        require(sha(name) == expected, 'historical cap tensor record binding')
    records = []
    for setting in plan['find_k_settings']:
        wave = setting['wavelength_um']
        worker = study / ('C2-cap-' + str(wave))
        result_relative = str((worker / 'result.json').relative_to(study))
        require(result_relative in top_files, 'top manifest missing worker result')
        result = read(worker / 'result.json')
        require(result['setting'] == setting, 'worker setting binding')
        require(result['physical_requirements_sha256'] == plan['physical_requirements_sha256'], 'worker physical binding')
        require(result['qpm_goal_sha256'] == plan['qpm_goal_sha256'], 'worker goal binding')
        evidence = result['persisted_evidence']
        evidence_path = (worker / evidence['folder']).resolve()
        require(evidence_path.is_relative_to(worker.resolve()), 'evidence path escape')
        fields, tensors, manifest = load_research_evidence(evidence_path,
            expected_manifest_sha256=evidence['manifest_sha256'])
        selected = result['selected_mode']
        require(manifest['selected_band'] == selected['band'], 'selected-band binding')
        for key in ('E', 'H'):
            require(hashlib.sha256(fields[key].tobytes()).hexdigest() == selected['field_hashes'][key], 'selected field hash ' + key)
        require(float(fields['electric_energy'].min()) >= 0, 'negative raw energy')
        close(fields['electric_energy'].sum(), selected['raw_energy_audit']['raw_sum'], 'selected energy sum')
        baseline = parent / ('base-' + str(wave))
        old = read(baseline / 'result.json')
        require(result['old_result_sha256'] == sha(baseline / 'result.json'), 'old result hash')
        require(result['old_selected_mode'] == old['selected_mode'], 'old selected mode binding')
        require(result['material'] == old['material'], 'material binding')
        require(selected['actual_grid']['shape_xyz'] == [320, 320, 1], 'grid shape')
        weight = direct_weight(fields, plan['task']['requirements'], result['material'])
        errors, overlaps = [], []
        for old_mode in old['all_modes']:
            with np.load(baseline / old_mode['fields_npz'], allow_pickle=False) as archive:
                first = {key: np.array(archive[key], copy=True) for key in archive.files}
            for axis in ('x_um', 'y_um'):
                require(np.array_equal(first[axis], fields[axis]), 'same physical integration grid: ' + axis)
            stored = next(row for row in result['full_four_by_four_E_H_research_matrix']
                          if row['old_band'] == old_mode['band'] and row['new_band'] == selected['band'])
            bounds = stored['common_physical_window_um']
            ix = (fields['x_um'] >= bounds[0][0]) & (fields['x_um'] < bounds[0][1])
            iy = (fields['y_um'] >= bounds[1][0]) & (fields['y_um'] < bounds[1][1])
            def window(array):
                return array[ix][:, iy, 0, :]
            recomputed = {
                'E_L2_overlap_research': overlap(window(first['E']), window(fields['E'])),
                'H_L2_overlap_research': overlap(window(first['H']), window(fields['H'])),
                'E_common_positive_bulk_weight_overlap': overlap(window(first['E']), window(fields['E']), weight[ix][:,iy,:]),
            }
            for key, values in recomputed.items():
                errors.append(close(values['squared_normalized_overlap'], stored['metrics'][key]['squared_normalized_overlap'], key))
                expected_metric = stored['metrics'][key]
                actual_complex = math.sqrt(values['squared_normalized_overlap']) * np.exp(1j * values['global_phase_alignment_rad'])
                expected_complex = math.sqrt(expected_metric['squared_normalized_overlap']) * np.exp(1j * expected_metric['global_phase_alignment_rad'])
                errors.append(close(abs(actual_complex - expected_complex), 0, key + ' normalized complex inner product'))
            for owner, native in (('first_native_window_and_tail', first), ('second_native_window_and_tail', fields)):
                for key, array_key in (('E_L2_tail_fraction', 'E'), ('H_L2_tail_fraction', 'H'), ('electric_energy_tail_fraction', 'electric_energy')):
                    density = native[array_key][:, :, 0] if array_key == 'electric_energy' else np.sum(abs(native[array_key][:, :, 0, :])**2, axis=-1)
                    tail = 1 - float(density[ix][:, iy].sum() / density.sum())
                    errors.append(close(stored[owner][key], tail, owner + ' ' + key))
            overlaps.append({'old_band': old_mode['band'], 'new_band': selected['band'], 'metrics': recomputed})
        old_tensor = read(repo / 'local-validation/pro-numerical-review-20261007/recovery-window-v2' /
                          ('I2-' + str(wave)) / 'result.json')
        tensor_matches = []
        for component in old_tensor['tensor_components']:
            key = 'inverse_epsilon' if component['inverse'] else 'epsilon'
            i, j = map(int, component['component'])
            actual_hash = hashlib.sha256(tensors[key][i, j].tobytes()).hexdigest()
            require(actual_hash == component['sha256'], 'historical cap tensor hash ' + key + component['component'])
            tensor_matches.append({'tensor': key, 'component': component['component'], 'sha256_matches_prior_I2': True})
        row = next(row for row in summary['rows'] if row['wavelength_um'] == wave)
        require(row['worker_result_sha256'] == sha(worker / 'result.json'), 'summary worker result binding')
        dn = selected['neff'] - old['selected_mode']['neff']
        coefficient = 4 * math.pi * plan['qpm_goal']['length_um'] / plan['qpm_goal']['pump_wavelength_um']
        close(row['delta_neff'], dn, 'delta neff')
        close(row['delta_beta_rad_per_um'], 2 * math.pi * dn / wave, 'delta beta')
        close(row['absolute_phase_contribution_rad'], coefficient * abs(dn), 'absolute phase')
        close(row['signed_phase_contribution_rad'], coefficient * dn * (-1 if wave == plan['qpm_goal']['pump_wavelength_um'] else 1), 'signed phase')
        records.append({'wavelength_um': wave, 'selected_band': selected['band'],
            'recomputed_selected_column': overlaps, 'maximum_metric_difference': max(errors),
            'historical_cap_tensor_components': tensor_matches,
            'complete_competitor_matrix_independently_recomputed': False,
            'selected_column_and_tensor_arrays_verified': True,
            'saved_window_used_exactly': True,
            'periodic_endpoint_rounding_note': 'Saved v1 common bounds may omit a boundary sample through floating rounding; replay preserves the saved window rather than assuming zero tails'})
    require(summary['old_qpm_status'] == 'INCONCLUSIVE' and summary['old_design_goal_status'] == 'NOT_EVALUATED', 'scientific conclusion preserved')
    output = {'status': 'PASS', 'kind': 'OFFLINE_RECOMPUTATION_NO_SOLVER_OR_MODEL',
        'verifier_sha256': sha(Path(__file__)), 'plan_sha256': digest(plan),
        'new_solver_calls': 0, 'new_model_calls': 0, 'rows': records,
        'scope': 'Persisted selected new column, prior cap tensor hashes, old baseline hashes, phase arithmetic; no continuous error certification'}
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': 'PASS', 'waves': len(records), 'new_solver_calls': 0,
        'maximum_metric_difference': max(r['maximum_metric_difference'] for r in records)}, indent=2))


if __name__ == '__main__':
    main()
