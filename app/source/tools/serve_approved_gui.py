"""Bound cumulative-approval GUI; input credential once, only in memory."""
import argparse
import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photonguard.approved_gui import (prepare_migration, ContinuationAdapter, seed_cases,
    DEFAULT_ORIGINAL, DEFAULT_PROGRESS)
from photonguard.workflow import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Offline source/ledger binding; no credential')
    parser.add_argument('--offline', action='store_true', help='No key and no paid requests')
    parser.add_argument('--port', type=int, default=8778)
    parser.add_argument('--data', type=Path, default=ROOT / 'workspace-data')
    args = parser.parse_args(argv)
    try:
        migration = prepare_migration(ROOT)
        if args.prepare:
            print(json.dumps({k: migration[k] for k in ('reference', 'carried_cumulative_ledger',
                'remaining_slots', 'budget_reset')}, ensure_ascii=False, indent=2))
            return 0
        key = None
        if not args.offline:
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise ValueError('Interactive hidden input required')
            key = getpass.getpass('DeepSeek credential (hidden; memory only): ')
            if not key or len(key) > 1024:
                raise ValueError('No in-memory credential')
        adapter = ContinuationAdapter(ROOT, DEFAULT_ORIGINAL, DEFAULT_PROGRESS,
                                      (lambda: key) if key else None)
        with make_server(args.data, port=args.port, allow_workers=True, model_adapter=adapter) as server:
            cases = seed_cases(server.store, adapter)
            print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/',
                'cases': cases['cases'], 'batch': adapter.status()['batch'],
                'credential_in_process_memory_only': bool(key), 'automatic_requests': False},
                ensure_ascii=False), flush=True)
            try:
                server.serve_forever(poll_interval=.2)
            except KeyboardInterrupt:
                pass
        key = None
        return 0
    except Exception:
        print('Stopped safely; inspect source binding, migration and cumulative ledger. No automatic retry.',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
