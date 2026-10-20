"""Independent Meep verification of an already computed bounded film candidate.

The trusted legacy film worker executes a JSON recipe (never model-written
Python). A completed runner, numerical PASS, and a met design target are three
separate facts. No thresholds, tolerances, or old evidence are modified here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from ..core import POLICY, POLICY_HASH, candidate_problem, digest, finite, lock_task, task_problem
from ..runner import run_case, verify_evidence
from .goals import assess

NUMERICS = {'resolution': 320, 'after_sources': 100, 'pml_um': 1,
            'air_um': 3, 'source_amplitude': 1}
POINT_METRICS = {'reflectance', 'transmittance'}
BAND_METRICS = {'reflectance_min', 'reflectance_mean', 'transmittance_min', 'transmittance_mean'}


def _write_new(path, value):
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
    with Path(path).open('xb') as stream:
        stream.write(encoded)


def _artifact(path, root):
    return {'path': str(Path(path).relative_to(root)),
            'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'bytes': Path(path).stat().st_size}


def _prepare(candidate, goal):
    if not isinstance(candidate, dict) or not isinstance(candidate.get('parameters'), dict):
        raise ValueError('candidate.parameters is required')
    parameters = candidate['parameters']
    if set(parameters) != {'layers', 'wavelengths_um'}:
        raise ValueError('film parameters require only layers and wavelengths_um')
    wave = parameters['wavelengths_um']
    if not isinstance(wave, list) or not 1 <= len(wave) <= 201 or any(not finite(w) or not .5 <= w <= 5 for w in wave):
        raise ValueError('bounded explicit wavelengths in [0.5,5] um are required')
    if any(a >= b for a, b in zip(wave, wave[1:])):
        raise ValueError('explicit wavelengths must be strictly increasing and unique')
    if not isinstance(goal, dict) or goal.get('metric') not in POINT_METRICS | BAND_METRICS:
        raise ValueError('unsupported film verification goal')
    if goal.get('operator') not in ('<=','>=','near','minimize','maximize'):
        raise ValueError('unsupported goal operator')
    if goal['operator'] not in ('minimize','maximize') and not finite(goal.get('target')):
        raise ValueError('finite target required')
    if goal['operator'] == 'near' and (not finite(goal.get('tolerance')) or goal['tolerance'] < 0):
        raise ValueError('finite nonnegative tolerance required')
    if goal['metric'] in POINT_METRICS:
        point = goal.get('wavelength_um')
        if not finite(point) or len([w for w in wave if abs(w-point) <= 1e-12]) != 1:
            raise ValueError('single-point goal must be uniquely present in the fast actual samples')
        delta = max(.025, point*.05)
        if point-delta < .5:
            validation_wave = [point, point+delta, point+2*delta]
        elif point+delta > 5:
            validation_wave = [point-2*delta, point-delta, point]
        else:
            validation_wave = [point-delta, point, point+delta]
        kind = 'POINT_GOAL_ONLY'
        note = 'Three actual Meep wavelength samples include the exact goal; no claim to verify the entire fast scan.'
    else:
        if len(wave) < 3:
            return None, None, {'kind': 'UNSUPPORTED_COVERAGE', 'reason': 'Legacy full verification needs at least 3 equally spaced wavelength points; no silent resampling.'}
        step = (wave[-1]-wave[0])/(len(wave)-1)
        if any(abs(w-(wave[0]+i*step)) > 1e-12 for i, w in enumerate(wave)):
            return None, None, {'kind': 'UNSUPPORTED_COVERAGE', 'reason': 'Band min/mean requires the original equal-wavelength point set; a nonuniform fast grid is not silently replaced.'}
        validation_wave = list(wave)
        kind = 'SAME_DISCRETE_GRID'
        note = 'Meep requests every original discrete wavelength; this is not continuous-band certification.'
    ident = 'experiment-film-'+digest({'parameters': parameters, 'goal': goal})[:16]
    task = {'schema_version': 1, 'case_id': ident, 'physics': {
            'dimensions': 1, 'angle_deg': 0, 'lossless': True, 'dispersive': False,
            'isotropic': True, 'mu': 1, 'n_incident': 1, 'n_exit': 1},
            'units_um': 1, 'layers': parameters['layers'],
            'wavelength_um': [validation_wave[0], validation_wave[-1]],
            'nfreq': len(validation_wave), 'sampling': {'kind': 'equal_wavelength'},
            'sources': ['Immutable experiment candidate '+digest(candidate)],
            'intent_note': 'Independent Meep verification for a confirmed finite candidate. '+note}
    recipe = {'schema_version': 1, 'adapter': 'film1d-v1', 'case_id': ident,
              'layers': [{'material_kind': 'index', 'material_value': layer['n'],
                          'thickness_um': layer['thickness_um']} for layer in parameters['layers']],
              'numerics': dict(NUMERICS),
              'workflow': {'subtract_incident': True, 'reference_amplitude': 1, 'reference_time_factor': 1},
              'origin': {'kind': 'experiment-deterministic-film-recipe-v1',
                         'experiment_candidate_sha256': digest(candidate), 'goal_sha256': digest(goal),
                         'patch_round': 0, 'generated_code_executed': False}}
    problem = task_problem(task) or candidate_problem(recipe)
    if problem:
        raise ValueError(problem['reason'])
    return task, recipe, {'kind': kind, 'note': note, 'fast_wavelengths_um': list(wave),
                          'requested_meep_wavelengths_um': validation_wave,
                          'interpolation_used': False, 'continuous_band_certified': False}


def _goal_from_observed(rows, goal, numerical_pass):
    if not rows:
        return {'status': 'NOT_EVALUATED', 'met': None, 'reason': 'No complete observed Meep spectrum.'}
    rows = sorted(rows, key=lambda row: row['wavelength_um'])
    data = {name: [r[key] for r in rows] for name, key in [('wavelengths_um','wavelength_um'),('R','R'),('T','T')]}
    metrics = {}
    for name, key in [('reflectance','R'), ('transmittance','T')]:
        metrics[name+'_min'] = min(data[key])
        metrics[name+'_mean'] = sum(data[key])/len(data[key])
    try:
        result = assess({'data': data, 'metrics': metrics,'engine':{'name':'Meep DFT flux'}}, goal)
    except ValueError as exc:
        return {'status': 'NOT_EVALUATED', 'met': None, 'reason': str(exc)}
    raw_met = result['met']
    result.update(status='EVALUATED_AT_ACTUAL_MEEP_SAMPLES', basis='ACTUAL_MEEP_DFT_SAMPLES_NO_INTERPOLATION',
                  raw_threshold_met=raw_met, met=raw_met if numerical_pass else None,
                  qualified_by_numerical_checks=bool(numerical_pass))
    return result


def verify_film(candidate, goal, out_dir):
    """Run exactly one complete eight-FDTD verification, without automatic retry.

    Callers enforce plan-level <=2 verification / <=16 FDTD caps. This function
    also takes a process-wide film-verifier lock, uses the existing legacy
    policy (1536 MiB per solver, 60 s per pair), and never changes that policy to
    fit the distinct lightweight-workbench worker budget.
    """
    task, recipe, coverage = _prepare(candidate, goal)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError('verification output directory must be empty; evidence is never overwritten')
    _write_new(root/'experiment-candidate.json', candidate)
    _write_new(root/'goal.json', goal)
    _write_new(root/'coverage.request.json', coverage)
    common = {'schema': 'photonguard.film-verification.v1', 'engine': 'Meep via trusted film1d-v1 worker',
              'fast_candidate_sha256': digest(candidate), 'goal_sha256': digest(goal),
              'coverage': coverage, 'policy_sha256': POLICY_HASH,
              'limitations': ['Ideal 1D lossless air-sided model; not a physical-device guarantee.',
                              'RUN_COMPLETED does not mean numerical PASS or design-target success.',
                              'Original frozen tolerances retained; no automatic retry or threshold change.',
                              'Meep and transfer-matrix calculations use different numerical methods; agreement is not a universal error certificate.'],
              'solver_policy': {'max_pair_seconds': POLICY['max_pair_seconds'],
                                'max_memory_mib': POLICY['max_memory_mib'],
                                'max_fdtd_runs': 8, 'numerics': dict(NUMERICS),
                                'separate_from_lightweight_worker_budget': True}}
    if task is None:
        result = {**common, 'status': 'UNSUPPORTED_COVERAGE', 'numerical_status': 'NOT_RUN',
                  'goal_meep': {'status': 'NOT_EVALUATED', 'met': None},
                  'resources': {'actual_fdtd_runs': 0, 'fdtd_attempts_reserved': 0}}
        _write_new(root/'verification.json', result)
        return result
    _write_new(root/'task.json', task)
    _write_new(root/'candidate.json', recipe)
    lock_task(root/'task.json', root/'task.lock.json')
    import fcntl
    lock_path = Path(tempfile.gettempdir())/('photonguard-experiment-meep-'+str(os.getuid())+'.lock')
    with lock_path.open('a') as solver_lock:
        try:
            fcntl.flock(solver_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result = {**common, 'status': 'RESOURCE_STOP', 'numerical_status': 'NOT_RUN',
                      'reason': 'Another experiment film verification already holds the solver lock.',
                      'goal_meep': {'status': 'NOT_EVALUATED', 'met': None},
                      'resources': {'actual_fdtd_runs': 0, 'fdtd_attempts_reserved': 0}}
            _write_new(root/'verification.json', result)
            return result
        try:
            from .executor import solver_mutex
            with solver_mutex():
                report, report_dir = run_case(root/'task.json', root/'candidate.json', root/'task.lock.json', root/'runs', max_fdtd_runs=8)
        finally:
            fcntl.flock(solver_lock.fileno(), fcntl.LOCK_UN)
    report_dir = Path(report_dir)
    if not verify_evidence(report_dir):
        raise ValueError('Meep evidence manifest verification failed')
    with (report_dir/'spectrum.csv').open(newline='', encoding='utf-8') as stream:
        rows = [{key: float(value) for key, value in row.items()} for row in csv.DictReader(stream)]
    observed = sorted(row['wavelength_um'] for row in rows)
    wanted = coverage['requested_meep_wavelengths_um']
    complete = len(wanted) == len(observed) and all(abs(a-b) <= 1e-12 for a,b in zip(wanted,observed))
    coverage.update(actual_meep_wavelengths_um=observed, requested_grid_observed=complete,
                    covers_all_fast_samples=all(any(abs(w-v) <= 1e-12 for v in observed) for w in coverage['fast_wavelengths_um']),
                    complete_for_goal=complete)
    numerical_pass = report['status'] == 'PASS' and complete
    numerical_status = 'NUMERICAL_PASS' if numerical_pass else 'NUMERICAL_FAIL' if report['status'] == 'FAIL' else 'NUMERICAL_INCONCLUSIVE'
    usage = report['resource_usage']
    result = {**common, 'status': 'RUN_COMPLETED', 'numerical_status': numerical_status,
              'legacy_report_status': report['status'], 'all_checks_passed': numerical_pass,
              'goal_meep': _goal_from_observed(rows, goal, numerical_pass),
              'checks': report['checks'], 'meep_version': report.get('environment',{}).get('meep_actual_version'),
              'report': _artifact(report_dir/'report.json', root),
              'manifest': _artifact(report_dir/'manifest.json', root),
              'spectrum': _artifact(report_dir/'spectrum.csv', root),
              'report_html': _artifact(report_dir/'report.html', root),
              'evidence_manifest_verified': True,
              'resources': {'actual_fdtd_runs': usage['fdtd_runs'],
                            'fdtd_attempts_reserved': usage['fdtd_attempts_reserved'],
                            'wall_seconds': usage['wall_seconds'],
                            'peak_worker_rss_kib': usage['peak_worker_rss_kib'],
                            'workers': usage['workers']}}
    _write_new(root/'verification.json', result)
    return result
