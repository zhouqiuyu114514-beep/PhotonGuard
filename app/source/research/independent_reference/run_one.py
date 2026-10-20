"""Explicit one-case launcher for prepared Yee research; never imported by prepare."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def output_failure(folder, plan):
    files = [path for path in folder.iterdir() if path.is_file()]
    # Leave room to preserve the failed attempt's monitor receipt.
    if sum(path.stat().st_size for path in files) > plan['max_output_bytes'] - 64 * 1024:
        return 'OUTPUT_BUDGET_EXCEEDED'
    if any(path.stat().st_size > 1024**2 for path in files if path.suffix == '.log'):
        return 'LOG_FILE_LIMIT_EXCEEDED'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id', required=True)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    if sys.platform != 'linux':
        raise SystemExit('Run with Linux/WSL Python: /proc and worker resource limits are required.')
    freeze = json.loads((folder / 'freeze.json').read_text())
    for name, expected in freeze['files'].items():
        if Path(name).name != name or sha(folder / name) != expected:
            raise SystemExit('Prepared source or plan hash mismatch: ' + name)
    plan = json.loads((folder / 'plan.json').read_text())
    allowed = [case['id'] for case in plan['cases']]
    if args.id not in allowed or len(set(allowed)) != len(allowed):
        raise SystemExit('Case is outside the prepared whitelist.')
    # Exclusive file stays present if this launcher is forcibly terminated;
    # such a directory needs human inspection, never automatic lock recovery.
    lock = folder / '.active-worker.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    proc = None
    try:
        os.write(descriptor, (str(os.getpid()) + '\n').encode())
        os.close(descriptor)
        for path in folder.glob('*.monitor.json'):
            if json.loads(path.read_text())['returncode'] != 0:
                raise RuntimeError('A previous worker failed; this batch is stopped.')
        # A start receipt without a completed monitor is also a stopped batch.
        for path in folder.glob('*.monitor-start.json'):
            if not (folder / path.name.replace('.monitor-start.json', '.monitor.json')).exists():
                raise RuntimeError('An earlier launch is incomplete; no retry or resume.')
        if len(list(folder.glob('*.monitor-start.json'))) >= plan['max_registered_attempts']:
            raise RuntimeError('Registered attempt budget exhausted.')
        if (folder / (args.id + '.started.json')).exists() or (folder / (args.id + '.json')).exists():
            raise RuntimeError('This case was already started; no retry or overwrite.')
        available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                             if line.startswith('MemAvailable:'))) * 1024
        if plan['per_worker_address_space_bytes'] > available * plan['available_memory_fraction_max']:
            raise RuntimeError('Worker address-space limit exceeds half of available RAM.')
        current_bytes = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
        if current_bytes + plan['per_case_output_reserve_bytes'] + 64 * 1024 > plan['max_output_bytes']:
            raise RuntimeError('Output reservation would exceed the prepared budget.')
        save(folder / (args.id + '.monitor-start.json'), {
            'id': args.id, 'plan_sha256': freeze['files']['plan.json'],
            'available_memory_bytes': available, 'address_space_limit_bytes': plan['per_worker_address_space_bytes'],
            'launcher_sha256': sha(Path(__file__)), 'automatic_retry': False,
        })
        started = time.monotonic()
        peak_virtual = peak_rss = 0
        timed_out = False
        output_guard = None
        with (folder / (args.id + '.stdout.log')).open('x') as stdout, (folder / (args.id + '.stderr.log')).open('x') as stderr:
            proc = subprocess.Popen([sys.executable, '-B', str(folder / 'worker.py'),
                                     '--plan', str(folder / 'plan.json'), '--id', args.id], stdout=stdout, stderr=stderr)
            while proc.poll() is None:
                try:
                    for line in Path(f'/proc/{proc.pid}/status').read_text().splitlines():
                        if line.startswith('VmPeak:'):
                            peak_virtual = max(peak_virtual, int(line.split()[1]) * 1024)
                        elif line.startswith('VmHWM:'):
                            peak_rss = max(peak_rss, int(line.split()[1]) * 1024)
                except FileNotFoundError:
                    pass
                output_guard = output_failure(folder, plan)
                if output_guard:
                    proc.kill()
                    proc.wait()
                    break
                if time.monotonic() - started >= plan['per_worker_wall_seconds']:
                    timed_out = True
                    proc.kill()
                    proc.wait()
                    break
                time.sleep(.03)
        output_guard = output_guard or output_failure(folder, plan)
        returncode = proc.returncode if not (timed_out or output_guard) else 1
        result = {'id': args.id, 'returncode': returncode, 'worker_returncode': proc.returncode,
                  'parent_timeout': timed_out, 'output_guard_failure': output_guard,
                  'wall_seconds': time.monotonic() - started, 'observed_peak_virtual_bytes': peak_virtual,
                  'observed_peak_rss_bytes': peak_rss, 'plan_sha256': freeze['files']['plan.json'],
                  'automatic_retry': False}
        save(folder / (args.id + '.monitor.json'), result)
        print(json.dumps(result))
        if returncode:
            raise SystemExit(1)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        lock.unlink()


if __name__ == '__main__':
    main()
