"""Prepare a frozen independent Yee research directory; never run a worker."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sys

SOURCE = Path(__file__).resolve().parents[1] / 'research' / 'independent_reference'
PROFILES_SHA256 = '1e7981be0236068536bbd6d18645ac89b11593c7bc4eb7f458fb337cc0548bee'
WORKER_SHA256 = {
    'yee_reference_v2.py': '86705bd8aaac3c4b8b1eecee84608b4c7d31771b926aa015b136d868bfb31f5e',
    'yee_reference_r80_v4.py': '5d4e95358d1f3a00db363e04f45e8e965d851af2d98917e6a4bc9ff63de03964',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def prepare(output, profile='calibration'):
    """Copy immutable sources and fixed profiles, returning unexecuted commands."""
    if profile not in ('calibration', 'ridge', 'ridge80'):
        raise ValueError('Unknown research profile: ' + str(profile))
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Refusing existing output path: ' + str(output))
    profile_bytes = (SOURCE / 'profiles.json').read_bytes()
    if sha(profile_bytes) != PROFILES_SHA256:
        raise ValueError('Frozen profile source hash mismatch')
    config = json.loads(profile_bytes)[profile]
    worker_name = config['worker']
    worker = (SOURCE / worker_name).read_bytes()
    if sha(worker) != WORKER_SHA256[worker_name]:
        raise ValueError('Executed worker source hash mismatch')
    launcher = (SOURCE / 'run_one.py').read_bytes()
    ids = [case['id'] for case in config['cases']]
    if len(set(ids)) != len(ids) or len(ids) != config['max_registered_attempts']:
        raise ValueError('Frozen profile case-count mismatch')
    plan = {
        'schema': 'prepared-independent-yee-research-v1', 'status': 'PREPARED_NOT_EXECUTED',
        'profile': profile, **config, 'worker_sha256': sha(worker),
        'launcher_sha256': sha(launcher), 'profile_source_sha256': PROFILES_SHA256,
        'prepare_tool_sha256': sha(Path(__file__).read_bytes()),
        'available_memory_fraction_max': .5, 'simultaneous_workers': 1,
        'per_case_output_reserve_bytes': (13 if profile == 'ridge80' else 9) * 1024**2,
        'no_retries': True, 'stop_after_worker_failure': True,
        'locked_long_device_length_um': 1000,
        'new_solver_calls_during_prepare': 0, 'new_API_calls_during_prepare': 0,
        'scientific_scope': 'Independent exploratory full-vector discretization; no continuous beta certificate or production acceptance.',
        'attempt_limit_scope': 'Immutable v2 worker ceiling is 12; the case whitelist and launcher enforce the smaller profile count. Immutable v4 ceiling is four.',
        'resource_enforcement': 'Worker enforces address-space/CPU/alarm limits. Explicit launcher enforces available-RAM fraction, directory lock, parent wall timeout, exact frozen file hashes, output reservation and monitored/final output checks. Output overflow or a log exceeding 1 MiB marks the batch failed; monitoring is not a filesystem quota.',
    }
    plan_bytes = encoded(plan)
    files = {'worker.py': worker, 'run_one.py': launcher, 'plan.json': plan_bytes}
    freeze = {'schema': 1, 'profile': profile, 'status': 'PREPARED_NOT_EXECUTED',
              'files': {name: sha(data) for name, data in files.items()}}
    commands = [[sys.executable, '-B', str(output / 'run_one.py'), '--id', name] for name in ids]
    instructions = ['Prepared only: no solver has run.',
                    'Use Linux/WSL Python with existing numpy/scipy. Run ONE command, inspect its result, then the next.',
                    'A worker failure stops the batch. Do not run worker.py directly or remove receipts to retry.',
                    *[shlex.join(command) for command in commands]]
    files.update({'freeze.json': encoded(freeze), 'commands.json': encoded(commands),
                  'RUN_COMMANDS.txt': ('\n'.join(instructions) + '\n').encode('utf-8')})
    # Validation precedes directory creation. A partial write fails closed;
    # an existing or partially prepared directory is never silently replaced.
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        with (output / name).open('xb') as stream:
            stream.write(data)
    return {'status': 'PREPARED_NOT_EXECUTED', 'output': str(output), 'profile': profile,
            'registered_cases': len(ids), 'worker_sha256': sha(worker), 'plan_sha256': sha(plan_bytes),
            'commands': commands, 'solver_calls': 0, 'API_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--profile', choices=('calibration', 'ridge', 'ridge80'), default='calibration')
    args = parser.parse_args()
    try:
        result = prepare(args.out, args.profile)
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
