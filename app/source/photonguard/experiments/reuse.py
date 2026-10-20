"""Versioned, offline inverse-workflow facade. No UI, API client or hidden object.

This module deliberately wraps the existing bounded plans and worker. It does not
implement another fitter. An output directory is one cumulative local workflow;
resuming it never refits the original CSV or restores spent allowances.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from ..core import digest
from ..workflow import atomic_json
from . import inverse_models as models
from .observation_group import parse, group_entry

SCHEMA = 'photonguard.offline-inverse.v1'
LIMITS = {'fits': 2, 'profiles': 1, 'followups': 1,
          'residual_calls_reserved': 90000, 'model_requests': 0}


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 16 * 1024 ** 2:
        raise ValueError('JSON exceeds the 16 MiB input limit')
    return json.loads(path.read_text(encoding='utf-8'))


def validate_spec(spec, expected_model=None):
    allowed = {'schema', 'settings', 'source', 'constraints', 'research_goal',
               'profile', 'baseline', 'policy', 'acquisition', 'followup_acquisition'}
    if not isinstance(spec, dict) or set(spec) - allowed or spec.get('schema') != SCHEMA:
        raise ValueError('Expected an explicit photonguard.offline-inverse.v1 plan')
    if spec['settings'].get('model') not in models.MODELS:
        raise ValueError('Unsupported inverse model')
    if expected_model and spec['settings']['model'] != expected_model:
        raise ValueError('Plan model does not match this example entry point')
    if not isinstance(spec.get('source'), dict) or not spec['source'].get('source_name'):
        raise ValueError('CSV provenance is required; no teaching defaults are inferred')
    profile = spec.get('profile')
    if profile is not None:
        if not isinstance(profile, dict) or set(profile) != {'parameter', 'grid_points'}:
            raise ValueError('Declare exactly one optional profile and its grid size')
        if spec['settings']['model'] == models.FILM:
            raise ValueError('Film uses its existing finite thickness search, not an extra profile')
    if spec.get('policy', 'conservative') not in ('conservative', 'local_exploration'):
        raise ValueError('Unknown selection policy')
    for key in ('acquisition', 'followup_acquisition'):
        value = spec.get(key, {})
        if not isinstance(value, dict) or set(value) - {'observation', 'noise', 'scale', 'scale_source'}:
            raise ValueError('Acquisition metadata may only declare observation/noise and residual scale')
    return copy.deepcopy(spec)


def public_state(groups, spec, fit, profiles, proposal):
    """Only supplied observations, declared facts and saved numerical evidence."""
    value = {'schema': 'photonguard.public-strategy-state.v1',
             'groups': copy.deepcopy(groups), 'settings': copy.deepcopy(spec['settings']),
             'constraints': copy.deepcopy(spec['constraints']),
             'research_goal': copy.deepcopy(spec.get('research_goal')),
             'fit_result': copy.deepcopy(fit), 'profiles': copy.deepcopy(profiles),
             'proposal': copy.deepcopy(proposal)}
    value['sha256'] = digest(value)
    return value


def fixed_strategy(state):
    """Replace goal selection with an already validated, source-labelled baseline."""
    proposal = state['proposal']
    if state['settings']['model'] == models.FILM:
        chosen = proposal['plans'][0]
    else:
        baseline_id = proposal.get('baseline_id')
        choices = [p for p in proposal['plans'] if p['id'] == baseline_id]
        if not choices:
            raise ValueError('No executable baseline: inspect baseline_catalog before proceeding')
        chosen = choices[0]
    key = 'wavelengths_nm' if state['settings']['model'] == models.FILM else 'positions_mm'
    return {'input_sha256': state['sha256'], key: copy.deepcopy(chosen.get('wavelengths_nm', chosen.get('prediction_x_mm'))),
            'reason': 'Explicit fixed strategy selects the existing first wavelength / declared baseline; no adaptive-benefit claim.'}


def validate_strategy(state, recommendation):
    """One finite output contract shared by replacement strategies.

    Trusted local Python supplies the callback; a plan file cannot name/import code.
    Positions must obey the same physical, sampling and instrument constraints.
    No fit, observation or hidden truth is consulted to validate a proposal.
    """
    film = state['settings']['model'] == models.FILM
    key = 'wavelengths_nm' if film else 'positions_mm'
    if not isinstance(recommendation, dict) or set(recommendation) != {'input_sha256', key, 'reason'}:
        raise ValueError('Strategy must return input_sha256, finite positions and reason only')
    if recommendation['input_sha256'] != state['sha256']:
        raise ValueError('Strategy recommendation belongs to a different public state')
    reason = recommendation['reason']
    x = recommendation[key]
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise ValueError('A short selection reason is required')
    if not isinstance(x, list) or any(type(v) not in (int, float) or not math.isfinite(v) for v in x):
        raise ValueError('Positions must be finite numbers')
    if any(b <= a for a, b in zip(x, x[1:])):
        raise ValueError('Positions must be strictly increasing, without duplicates')
    c = state['constraints']
    if film:
        if len(x) != 1 or any(v not in c['wavelengths_nm'] for v in x):
            raise ValueError('Select one wavelength from the explicitly available catalogue')
    else:
        if len(x) != c['points'] or any(abs(v) > c['max_abs_x_mm'] for v in x):
            raise ValueError('Positions violate the approved point count or range')
        if any(b - a < c['min_step_mm'] - 1e-12 for a, b in zip(x, x[1:])):
            raise ValueError('Positions violate the minimum instrument step')
        old = state['groups'][0]['dataset']['x_mm']
        if not c['allow_extension'] and (x[0] < old[0] or x[-1] > old[-1]):
            raise ValueError('Range extension was not authorized')
        if not c['stable_exposure_background']:
            raise ValueError('A proposed scan requires stable exposure and background')
        cfg = state['settings']
        if cfg['model'] == models.SLIT:
            centers = cfg['bounds'].get('center_shift_mm', [cfg['fixed'].get('center_shift_mm', 0)])
            if max(abs(v - center) for v in (x[0], x[-1]) for center in centers) / cfg['fixed']['focal_length_mm'] > .1:
                raise ValueError('Positions violate the declared paraxial model')
    return copy.deepcopy(recommendation)


def propose(groups, spec, fit, profiles, strategy=None):
    if spec['settings']['model'] == models.FILM:
        from .film_inverse import propose as generate
        proposal = generate(groups, spec['settings'], fit, spec['constraints'])
    else:
        from .baseline_design import propose as generate
        proposal = generate(groups, spec['settings'], fit, profiles, spec['constraints'],
                           spec.get('research_goal'), baseline=spec.get('baseline'),
                           policy=spec.get('policy', 'conservative'))
    state = public_state(groups, spec, fit, profiles, proposal)
    if strategy:
        selected = validate_strategy(state, strategy(copy.deepcopy(state)))
        proposal['replacement_strategy'] = selected
        proposal['original_sha256'] = proposal.pop('sha256')
        proposal['sha256'] = digest(proposal)
    return proposal


def selected_positions(proposal, model):
    key = 'wavelengths_nm' if model == models.FILM else 'positions_mm'
    if proposal.get('replacement_strategy'):
        return proposal['replacement_strategy'][key]
    selected = next(p for p in proposal['plans'] if p['id'] == proposal['recommended_id'])
    return selected['wavelengths_nm' if model == models.FILM else 'prediction_x_mm']


def _save(folder, state):
    state['sha256'] = digest({k: v for k, v in state.items() if k != 'sha256'})
    atomic_json(folder / 'workflow.json', state)


def _load(folder):
    state = read_json(folder / 'workflow.json')
    if state.get('sha256') != digest({k: v for k, v in state.items() if k != 'sha256'}):
        raise ValueError('Saved workflow changed; approval and cumulative allowances are invalid')
    for name, expected in state['files'].items():
        p = folder / name
        if p.is_symlink() or not p.resolve().is_relative_to(folder.resolve()) or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('Saved input or evidence changed: ' + name)
    if state['limits'] != LIMITS:
        raise ValueError('Saved resource limits cannot be enlarged')
    return state


def _record_file(folder, state, relative):
    state['files'][relative] = hashlib.sha256((folder / relative).read_bytes()).hexdigest()


def _group(dataset, spec, filename, followup=False):
    metadata = spec.get('followup_acquisition' if followup else 'acquisition', {})
    return group_entry(dataset, spec['settings'], filename) | copy.deepcopy(metadata) | {'approved': True}


def _preflight_design(groups, spec):
    """Reject a malformed intended design before consuming a solver allowance."""
    cfg = spec['settings']
    if cfg['model'] == models.FILM:
        c = spec.get('constraints')
        if not isinstance(c, dict) or set(c) != {'wavelengths_nm'}:
            raise ValueError('Film planning requires the available wavelength catalogue')
        x = c['wavelengths_nm']
        if not isinstance(x, list) or not 2 <= len(x) <= 9 or any(not models.finite(v) or not 500 <= v <= 2000 for v in x) or len(set(x)) != len(x):
            raise ValueError('Declare 2–9 distinct available wavelengths between 500 and 2000 nm')
    else:
        from . import goal_design
        goal_design.templates(groups, cfg, spec.get('constraints'))
        goal_design.goal(cfg['model'], spec.get('research_goal'))
    if spec.get('profile'):
        p = spec['profile']
        physical = ('slit_width_um', 'slit_separation_um') if cfg['model'] == models.SLIT else models.GAUSSIAN_PARAMETERS
        if p['parameter'] not in physical or p['parameter'] not in cfg['bounds'] or type(p['grid_points']) is not int or not 3 <= p['grid_points'] <= 21:
            raise ValueError('Profile needs one free physical parameter and 3–21 predeclared points')


def _solve(folder, state, groups, operation='fit', reference=None):
    field = 'fits' if operation == 'fit' else 'profiles'
    if state['reserved'][field] >= LIMITS[field]:
        raise ValueError('Cumulative local workflow limit exhausted: ' + field)
    kwargs = state['spec'].get('profile') or {}
    plan = models.plan(groups, state['spec']['settings'], operation,
                       reference=reference, **(kwargs if operation == 'profile' else {}))
    cap = plan['budget']['max_residual_calls']
    if state['reserved']['residual_calls_reserved'] + cap > LIMITS['residual_calls_reserved']:
        raise ValueError('Cumulative residual allowance exhausted')
    name = operation + '-' + str(state['reserved'][field] + 1)
    work = folder / name
    work.mkdir(exist_ok=False)
    state['reserved'][field] += 1
    state['reserved']['residual_calls_reserved'] += cap
    _save(folder, state)  # reserve before launching; failures do not refund or retry
    atomic_json(work / 'request.json', {'plan': plan, 'reference': reference})
    _record_file(folder, state, name + '/request.json')
    _save(folder, state)
    from .executor import solver_mutex
    from ..runner import clean_environment
    env = clean_environment()
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]), OMP_NUM_THREADS='1',
               OPENBLAS_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    try:
        with solver_mutex(), (work / 'worker.log').open('wb') as log:
            proc = subprocess.run([sys.executable, '-B', '-m', 'photonguard.experiments.inverse_worker', str(work)],
                                  env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=plan['budget']['seconds'] + 5)
        if proc.returncode:
            raise ValueError('Bounded worker stopped; inspect saved log; no automatic retry')
        result = read_json(work / 'result.json')
        if result.get('plan_sha256') != plan['sha256']:
            raise ValueError('Worker result is not bound to this plan')
        _record_file(folder, state, name + '/result.json')
        state['actual_residual_calls'] += result['resources']['actual_residual_calls']
        _save(folder, state)
        return result
    except Exception as exc:
        state['status'] = 'STOPPED_WITH_RESERVED_BUDGET'
        state['failure'] = type(exc).__name__ + ': ' + str(exc)
        _save(folder, state)
        raise


def run(csv_path, spec, out, *, approve=False, expected_model=None, strategy=None):
    """One approved initial fit, optional single profile and bounded recommendation."""
    if approve is not True:
        raise ValueError('Explicit approve=True / --approve is required before local computation')
    spec = validate_spec(spec, expected_model)
    if Path(csv_path).stat().st_size > 2 * 1024 ** 2:
        raise ValueError('CSV exceeds 2 MiB')
    raw = Path(csv_path).read_bytes()
    ds = parse(raw.decode('utf-8'), spec['settings']['model'], spec['source'])
    groups = [_group(ds, spec, 'initial.csv')]
    models.validate(groups, spec['settings'])
    _preflight_design(groups, spec)
    folder = Path(out).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'initial.csv').write_bytes(raw)
    atomic_json(folder / 'input-plan.json', spec)
    state = {'schema': SCHEMA, 'spec': spec, 'groups': groups, 'profiles': {}, 'limits': dict(LIMITS),
             'reserved': {'fits': 0, 'profiles': 0, 'followups': 0, 'residual_calls_reserved': 0},
             'actual_residual_calls': 0, 'status': 'APPROVED_INITIAL_COMPUTATION', 'files': {},
             'model_requests': 0, 'independent_of_web_store': True}
    for name in ('initial.csv', 'input-plan.json'):
        _record_file(folder, state, name)
    _save(folder, state)
    fit = _solve(folder, state, groups)
    state['initial_fit'] = fit
    _save(folder, state)
    if spec.get('profile'):
        profile = _solve(folder, state, groups, 'profile', fit)
        state['profiles'][profile['parameter']] = profile
    try:
        state['proposal'] = propose(groups, spec, fit, state['profiles'], strategy)
    except Exception as exc:
        state['status'] = 'STOPPED_WITH_RESERVED_BUDGET'
        state['failure'] = type(exc).__name__ + ': ' + str(exc)
        _save(folder, state)
        raise
    state['approved_observation_positions'] = selected_positions(state['proposal'], spec['settings']['model'])
    state['status'] = 'PLAN_READY_AWAITING_SEPARATE_FOLLOWUP_APPROVAL'
    atomic_json(folder / 'proposal.json', state['proposal'])
    _record_file(folder, state, 'proposal.json')
    _save(folder, state)
    return state


def followup(out, csv_path, *, approve=False):
    """Append one separately approved observation at the saved selected positions."""
    if approve is not True:
        raise ValueError('Follow-up analysis requires its own explicit approval')
    folder = Path(out).resolve()
    state = _load(folder)
    if state['status'] != 'PLAN_READY_AWAITING_SEPARATE_FOLLOWUP_APPROVAL':
        raise ValueError('Only the saved ready plan can accept one follow-up; no automatic retries')
    if state['reserved']['followups'] >= LIMITS['followups']:
        raise ValueError('Follow-up allowance exhausted')
    if Path(csv_path).stat().st_size > 2 * 1024 ** 2:
        raise ValueError('CSV exceeds 2 MiB')
    raw = Path(csv_path).read_bytes()
    spec = state['spec']
    ds = parse(raw.decode('utf-8'), spec['settings']['model'], spec['source'])
    if any(ds['raw_sha256'] == g['dataset']['raw_sha256'] for g in state['groups']):
        raise ValueError('Duplicating the same CSV does not create an independent observation')
    actual = ds['x_nm'] if spec['settings']['model'] == models.FILM else ds['x_mm']
    expected = state['approved_observation_positions']
    if len(actual) != len(expected) or any(abs(a - b) > max(1e-8, abs(b) * 1e-10) for a, b in zip(actual, expected)):
        raise ValueError('Follow-up coordinates do not match the saved plan; make a new explicit plan instead')
    groups = state['groups'] + [_group(ds, spec, 'followup.csv', followup=True)]
    models.validate(groups, spec['settings'])
    (folder / 'followup.csv').write_bytes(raw)
    _record_file(folder, state, 'followup.csv')
    state['reserved']['followups'] += 1
    state['groups'] = groups
    state['status'] = 'APPROVED_JOINT_COMPUTATION'
    _save(folder, state)
    state['joint_fit'] = _solve(folder, state, groups)
    state['comparison'] = {'initial_parameters': state['initial_fit']['estimated_parameters'],
                           'joint_parameters': state['joint_fit']['estimated_parameters'],
                           'initial_warnings': state['initial_fit']['warnings'],
                           'joint_warnings': state['joint_fit']['warnings'],
                           'note': 'Actual joint estimates; no hidden truth, accuracy or independent-validation claim.'}
    state['status'] = 'JOINT_ANALYSIS_COMPLETED'
    _save(folder, state)
    return state


def inspect(out):
    """Read and verify saved results without approval, dependencies, AI or new fits."""
    return _load(Path(out).resolve())
