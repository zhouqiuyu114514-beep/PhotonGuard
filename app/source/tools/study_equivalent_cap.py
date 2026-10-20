"""Exact two-worker equivalent-cap experiment, separate from product acceptance.

Prepare freezes sources, old fields and resources. Execute requires its digest;
an existing start marker prohibits replay. No model transport is imported.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
import os
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photonguard.core import digest, load
from photonguard.approved_gui import source_manifest
from photonguard.mode_numerical_review import POLICY, EVIDENCE_POLICY, load_research_evidence
from tools.review_mode_numerics import input_context, geometry_proof

MAIN = Path('/home/zhou/projects/PhotonGuard-development')
PREVIOUS = ROOT / 'local-validation/pro-numerical-review-20261007'
LEDGER = MAIN / 'local-validation/development-phase-20cny/development-budget.ledger.json'
RESERVE = 28 * 1024**2


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def files(folder):
    return {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob('*')) if p.is_file()}


def size(folder):
    return sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def old_context():
    failed = PREVIOUS / 'new-window-v1'
    completed = PREVIOUS / 'recovery-window-v2'
    summary = load(completed / 'summary.json')
    failure = load(failed / 'HALTED.json')
    require(len(failure['attempts']) == 1, 'CAP_PRIOR_FAILURE_ACCOUNTING')
    require(summary['cumulative_initialization_attempts'] == 5 and summary['find_k_invocations'] == 2,
            'CAP_PRIOR_COUNT_MISMATCH')
    return {
        'completed_directory': str(completed), 'failed_directory': str(failed),
        'completed_summary_sha256': sha(completed / 'summary.json'),
        'failure_sha256': sha(failed / 'HALTED.json'),
        'initialization_attempts': 5, 'failed_initializations': 1,
        'find_k_invocations': 2, 'eigenproblem_solves': summary['eigenproblem_solves'],
        'failed_wall_seconds_reserved': 60, 'failed_output_bytes_reserved': 4 * 1024**2,
        'historical_cap_tensor_results': {str(completed / ('I2-' + str(wave)) / 'result.json'):
            sha(completed / ('I2-' + str(wave)) / 'result.json') for wave in (1.55, .775)},
        'prior_evidence_bytes': size(failed) + size(completed),
        'old_windows_remain_closed': True, 'old_deadline_not_reset': True,
    }


def make_plan():
    task, goal, baseline = input_context()
    binding = source_manifest(ROOT)
    require(not binding.get('git_dirty', binding.get('dirty', False)), 'CAP_SOURCE_DIRTY')
    require(not subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True).strip(),
            'CAP_SOURCE_NOT_COMMITTED')
    original = next(b for b in baseline if b['resolution'] == 80)
    parent = Path(original['folder'])
    require(sha(parent / 'manifest.json') == original['manifest_sha256'], 'CAP_OLD_MANIFEST_CHANGED')
    manifest = load(parent / 'manifest.json')['files']
    require(all(sha(parent / name) == expected for name, expected in manifest.items()), 'CAP_OLD_FIELDS_CHANGED')
    settings = [{'id': 'C2-cap', 'wavelength_um': wave, 'resolution': 80, 'domain_um': [4, 4],
                 'mesh_size': 7, 'geometry': 'equivalent_cap', 'shift_x_um': 0.,
                 'eigen_tolerance': 1e-9, 'root_tolerance': 1e-9}
                for wave in task['requirements']['wavelengths_um']]
    old = old_context()
    require(old['prior_evidence_bytes'] + old['failed_output_bytes_reserved'] + 2 * RESERVE + 1024**2
            <= POLICY['persistent_output_max_bytes'], 'CAP_CUMULATIVE_PERSISTENCE_BUDGET')
    return {'schema_version': 1, 'kind': 'EQUIVALENT_CAP_TWO_WORKER_RESEARCH',
            'task': task, 'task_sha256': digest(task),
            'physical_requirements_sha256': digest(task['requirements']),
            'qpm_goal': goal, 'qpm_goal_sha256': digest(goal),
            'policy': POLICY, 'policy_sha256': digest(POLICY),
            'source_binding': binding, 'source_binding_sha256': digest(binding),
            'baseline': original, 'old_manifest_files': manifest,
            'initializations': [], 'find_k_settings': settings,
            'evidence_persistence': EVIDENCE_POLICY,
            'carry_forward': old,
            'new_window': {'find_k_workers_max': 2, 'initialization_processes_max': 0,
                           'total_wall_seconds': 660, 'worker_seconds_each': 300,
                           'output_reservation_per_worker_bytes': RESERVE,
                           'additional_model_requests': 0, 'automatic_retries': 0},
            'unexecuted': ['mesh15', 'tight tolerance', 'r120 translation', 'directional domain'],
            'not_product_repair_or_acceptance': True,
            'interpretation': 'Quantify representation sensitivity at two fixed r80 points; no continuous beta error bound',
            'old_qpm_status': 'INCONCLUSIVE', 'old_goal_status': 'NOT_EVALUATED'}


def verify_baseline(plan):
    for name, expected in plan.get('carry_forward', {}).get('historical_cap_tensor_results', {}).items():
        require(sha(name) == expected, 'CAP_HISTORICAL_TENSOR_RECORD_CHANGED')
    parent = Path(plan['baseline']['folder'])
    require(sha(parent / 'manifest.json') == plan['baseline']['manifest_sha256'], 'CAP_OLD_MANIFEST_CHANGED')
    require(all(sha(parent / name) == expected for name, expected in plan['old_manifest_files'].items()),
            'CAP_OLD_FIELDS_CHANGED')


def worker_limits():
    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                         if line.startswith('MemAvailable:'))) * 1024
    bound = min(POLICY['address_space_max_bytes'], available // 2)
    resource.setrlimit(resource.RLIMIT_AS, (bound, bound))
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def execute(out, supplied_hash):
    plan = load(out / 'plan.json')
    require(supplied_hash == digest(plan), 'CAP_EXACT_PLAN_REVIEW_REQUIRED')
    require(plan == make_plan(), 'CAP_PLAN_SOURCE_OR_OLD_EVIDENCE_CHANGED')
    require(not (out / 'execution-started.json').exists(), 'CAP_NO_RETRY_OR_REPLAY')
    require(load(LEDGER)['pending'] is None, 'CAP_FINANCE_PENDING')
    ledger_before = sha(LEDGER)
    state_before = sha(MAIN / 'local-validation/CURRENT_STATE.json')
    workspace_before = files(MAIN / 'workspace-data')
    require(size(MAIN / 'workspace-data') + POLICY['persistent_output_max_bytes']
            <= POLICY['existing_workspace_guard_bytes'], 'CAP_EXISTING_WORKSPACE_LIMIT')
    require(shutil.disk_usage(out).free >= POLICY['persistent_output_max_bytes'] * 2, 'CAP_FREE_DISK')
    save(out / 'OWNER_DELEGATED_EXACT_PLAN_REVIEW.json', {
        'actor': 'Codex', 'confirmation_kind': 'SIMULATED',
        'authority': 'Owner instruction 2026-10-08: continue autonomously, solve problems and execute development revalidation',
        'not_a_human_UI_click': True, 'plan_sha256': digest(plan),
        'new_workers': 2, 'new_initialization_processes': 0, 'new_model_calls': 0,
        'prior_failures_and_reservations_retained': True})
    save(out / 'execution-started.json', {'at_utc': datetime.now(timezone.utc).isoformat(),
         'plan_sha256': digest(plan), 'ledger_sha256': ledger_before,
         'canonical_state_sha256': state_before, 'workspace_files': workspace_before})
    started = time.monotonic()
    attempts, rows = [], []
    env = {'PATH': str(Path(sys.executable).parent) + ':/usr/bin:/bin', 'PYTHONNOUSERSITE': '1',
           'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    try:
        for setting in plan['find_k_settings']:
            require(source_manifest(ROOT) == plan['source_binding'], 'CAP_SOURCE_CHANGED_DURING_EXECUTION')
            require(sha(LEDGER) == ledger_before, 'CAP_LEDGER_CHANGED')
            verify_baseline(plan)
            require(time.monotonic() - started + 300 <= 660, 'CAP_TOTAL_DEADLINE')
            require(len(attempts) < 2 and plan['carry_forward']['find_k_invocations'] + len(attempts) < 8,
                    'CAP_CUMULATIVE_WORKER_COUNT')
            require(size(out) + RESERVE + plan['carry_forward']['prior_evidence_bytes']
                    + plan['carry_forward']['failed_output_bytes_reserved'] <= POLICY['persistent_output_max_bytes'],
                    'CAP_CUMULATIVE_OUTPUT_LIMIT')
            wave = setting['wavelength_um']
            name = 'C2-cap-' + str(wave)
            baseline = Path(plan['baseline']['folder']) / ('base-' + str(wave))
            request = {'kind': 'find_k', 'setting': setting, 'plan': plan,
                       'baseline': {'folder': str(baseline)}, 'persist_evidence': True}
            save(out / (name + '.request.json'), request)
            save(out / (name + '.reservation.json'), {
                'reserved_before_process_creation': True, 'wall_seconds_reserved': 300,
                'output_bytes_reserved': RESERVE, 'automatic_retry': False})
            t = time.monotonic()
            with (out / (name + '.stdout.log')).open('x') as stdout, (out / (name + '.stderr.log')).open('x') as stderr:
                try:
                    completed = subprocess.run([sys.executable, '-B',
                        str(ROOT / 'photonguard/adapters/mpb_research_worker.py'),
                        str(out / (name + '.request.json')), str(out / name)],
                        cwd=ROOT, env=env, stdout=stdout, stderr=stderr, timeout=300, preexec_fn=worker_limits)
                    code = completed.returncode
                except subprocess.TimeoutExpired:
                    code = 'TIMEOUT'
            attempt = {'id': name, 'kind': 'find_k', 'returncode': code,
                       'wall_seconds': time.monotonic() - t, 'source_commit': plan['source_binding']['git_commit']}
            attempts.append(attempt)
            save(out / (name + '.attempt.json'), attempt)
            print(json.dumps(attempt), flush=True)
            require(code == 0, 'CAP_WORKER_FAILED_NO_AUTOMATIC_RETRY')
            result = load(out / name / 'result.json')
            require(result['identity_clear_within_four_bands'], 'CAP_UNCLEAR_IDENTITY_STOP')
            evidence = result['persisted_evidence']
            load_research_evidence(out / name / evidence['folder'], expected_manifest_sha256=evidence['manifest_sha256'])
            require(size(out / name) <= RESERVE, 'CAP_WORKER_OUTPUT_EXCEEDS_RESERVATION')
            require(all(p.stat().st_size <= 1024**2 for p in (out / name).rglob('*') if p.is_file()),
                    'CAP_SINGLE_FILE_HARD_LIMIT')
            require(result['physical_requirements_sha256'] == plan['physical_requirements_sha256']
                    and result['qpm_goal_sha256'] == plan['qpm_goal_sha256'], 'CAP_PHYSICAL_BINDING')
            old = load(baseline / 'result.json')
            require(result['material'] == old['material'], 'CAP_MATERIAL_CHANGED')
            dn = result['selected_mode']['neff'] - result['old_selected_mode']['neff']
            coefficient = 4 * math.pi * plan['qpm_goal']['length_um'] / plan['qpm_goal']['pump_wavelength_um']
            rows.append({'wavelength_um': wave, 'original_neff': result['old_selected_mode']['neff'],
                         'cap_neff': result['selected_mode']['neff'], 'delta_neff': dn,
                         'delta_beta_rad_per_um': 2 * math.pi * dn / wave,
                         'absolute_phase_contribution_rad': coefficient * abs(dn),
                         'signed_phase_contribution_rad': coefficient * dn * (-1 if wave == plan['qpm_goal']['pump_wavelength_um'] else 1),
                         'identity': result['selected_identity'], 'solver_counts': result['solver_counts'],
                         'peak_rss_kib': result['peak_rss_kib'], 'worker_result_sha256': sha(out / name / 'result.json')})
        verify_baseline(plan)
        require(files(MAIN / 'workspace-data') == workspace_before and sha(LEDGER) == ledger_before
                and sha(MAIN / 'local-validation/CURRENT_STATE.json') == state_before, 'CAP_OLD_STATE_PRESERVATION')
        total_output = size(out) + plan['carry_forward']['prior_evidence_bytes'] + plan['carry_forward']['failed_output_bytes_reserved']
        require(total_output + 65536 <= POLICY['persistent_output_max_bytes'], 'CAP_FINAL_OUTPUT_LIMIT')
        result = {'status': 'COMPLETED_TWO_POINT_REPRESENTATION_STUDY',
                  'at_utc': datetime.now(timezone.utc).isoformat(), 'plan_sha256': digest(plan),
                  'source_commit': plan['source_binding']['git_commit'], 'rows': rows,
                  'absolute_phase_contributions_sum_rad': sum(r['absolute_phase_contribution_rad'] for r in rows),
                  'signed_phase_change_rad': sum(r['signed_phase_contribution_rad'] for r in rows),
                  'representation_effect_exceeds_diagnostic_budget': any(r['absolute_phase_contribution_rad'] > .01 for r in rows),
                  'diagnostic_budget_is_not_acceptance_threshold': True,
                  'new_initialization_processes': 0, 'new_find_k_invocations': len(attempts),
                  'new_eigenproblem_solves': sum(r['solver_counts']['eigenproblem_solves'] for r in rows),
                  'cumulative_initialization_attempts': 5, 'cumulative_find_k_invocations': 2 + len(attempts),
                  'failed_attempts_carried': 1, 'carry_forward': plan['carry_forward'],
                  'total_wall_seconds': time.monotonic() - started,
                  'new_bytes_before_summary': size(out), 'cumulative_bytes_plus_failure_reserve': total_output,
                  'old_workspace_ledger_and_state_unchanged': True,
                  'new_model_requests': 0, 'new_fdtd_runs': 0,
                  'old_qpm_status': 'INCONCLUSIVE', 'old_design_goal_status': 'NOT_EVALUATED',
                  'continuous_beta_error_bound_available': False,
                  'full_selected_fields_and_effective_tensors_saved': True,
                  'all_competitor_fields_saved': False, 'not_AI_gain_evidence': True,
                  'stop_reason': 'Exact two-worker plan completed; no other stages scheduled'}
        save(out / 'summary.json', result)
        save(out / 'manifest.json', {'files': files(out), 'not_product_acceptance': True})
        print(json.dumps({k: v for k, v in result.items() if k not in ('rows', 'carry_forward')}, indent=2))
    except BaseException as exc:
        save(out / 'HALTED.json', {'at_utc': datetime.now(timezone.utc).isoformat(),
             'reason': type(exc).__name__ + ': ' + str(exc), 'attempts': attempts,
             'reservations_retained': True, 'automatic_retry': False,
             'old_qpm_status': 'INCONCLUSIVE', 'old_goal_status': 'NOT_EVALUATED'})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--owner-delegated-plan-sha256')
    args = parser.parse_args()
    out = args.out.resolve()
    require(out.is_relative_to(ROOT / 'local-validation'), 'CAP_OUTPUT_SCOPE')
    if args.prepare:
        plan = make_plan()
        out.mkdir(exist_ok=False)
        save(out / 'plan.json', plan)
        save(out / 'continuous-geometry-equivalence.json', geometry_proof(plan['task']['requirements']))
        print(json.dumps({'plan_sha256': digest(plan), 'source_commit': plan['source_binding']['git_commit'],
                          'new_workers': 2, 'new_model_requests': 0}))
    else:
        execute(out, args.owner_delegated_plan_sha256)


if __name__ == '__main__':
    main()
