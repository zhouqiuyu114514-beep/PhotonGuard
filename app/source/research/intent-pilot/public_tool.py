"""Common offline review wrapper; identical version and call limit for all arms.

The coordinator assigns one writable session directory per arm/case. Directory
and command isolation must be enforced externally before any real evaluation.
SPDX-License-Identifier: GPL-2.0-or-later
"""
import argparse
import json
from pathlib import Path
import socket
import time
import semantic_intake as adapter
import intent_pilot as legacy
import requirements_intake as intake
from photonguard.backend import _redact

OPERATIONS = ('semantic-export', 'semantic-import', 'legacy-review',
              'legacy-export', 'legacy-import')


def run(operation, source, candidate, trusted_hash):
    if operation.startswith('semantic-'):
        view = adapter.read(source)
        adapter.validate_view(view, trusted_hash)
        if operation == 'semantic-export':
            return view
        return adapter.receipt(view, adapter.read(candidate, decimal_numbers=True), trusted_hash)
    if operation == 'legacy-review':
        return legacy.review(legacy.read_json(source), legacy.read_json(candidate))
    if operation == 'legacy-export':
        return intake.prepare(legacy.read_json(source))
    if operation == 'legacy-import':
        return intake.validate_response(legacy.read_json(source), legacy.read_json(candidate))
    raise ValueError('operation not allowed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=OPERATIONS)
    parser.add_argument('--source', required=True)
    parser.add_argument('--candidate')
    parser.add_argument('--expected-input-sha256')
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    session = Path(args.session)
    session.mkdir(parents=True, exist_ok=True)
    call = None
    for i in range(1, 9):
        try:
            call = session / ('call-%02d' % i)
            call.mkdir(exist_ok=False)
            break
        except FileExistsError:
            call = None
    if call is None:
        parser.exit(4, 'BUDGET_STOP: all eight calls reserved, including failures\n')
    start = time.perf_counter()
    event = {'operation': args.operation, 'call_number': i, 'status': 'INCOMPLETE',
             'model_calls': 0, 'solver_calls': 0, 'task_approved': False,
             'task_lock_created': False, 'elapsed_seconds': None}
    def save():
        (call / 'event.json').write_text(json.dumps(event, indent=2)+'\n', encoding='utf-8')
    save()
    def blocked(*unused, **kwargs):
        raise ValueError('offline network disabled')
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    try:
        result = run(args.operation, args.source, args.candidate, args.expected_input_sha256)
        (call / 'output.json').write_text(json.dumps(_redact(result, None), ensure_ascii=False,
                                        indent=2, allow_nan=False)+'\n', encoding='utf-8')
        event['status'] = 'RETURNED_STRUCTURAL_REVIEW_ONLY'
        code = 0
    except (ValueError, TypeError, OSError, UnicodeError, RecursionError):
        event['status'] = 'REJECTED'
        code = 3
    finally:
        event['elapsed_seconds'] = time.perf_counter() - start
        save()
    print(event['status'])
    raise SystemExit(code)


if __name__ == '__main__':
    main()
