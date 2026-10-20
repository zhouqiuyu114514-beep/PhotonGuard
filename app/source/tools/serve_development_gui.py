"""Single canonical GUI and cumulative 20 CNY development budget."""
import argparse
import getpass
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photonguard.development_phase import prepare_phase, PhaseAdapter, seed_phase_cases, PHASE
from photonguard.workflow import make_server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--official-rates-verified-at')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--port', type=int, default=8778)
    args = parser.parse_args(argv)
    try:
        manifest = PHASE / 'phase.json'
        if args.prepare:
            phase = prepare_phase(ROOT, args.official_rates_verified_at)
            print(json.dumps({'reference': phase['reference'], 'cny_limit': '20',
                'carried_attempts': phase['carried_attempts'],
                'carried_cost_upper_cny': phase['carried_cost_upper_cny'],
                'old_short_term_caps_superseded': True, 'old_ledgers_edited': False}, ensure_ascii=False))
            return 0
        if not manifest.exists():
            raise ValueError('Explicit phase migration must be prepared before credentials')
        # All source and existing-ledger checks happen before obtaining a key.
        PhaseAdapter(ROOT, PHASE, None)
        key = None
        if not args.offline:
            if not sys.stdin.isatty() or not sys.stderr.isatty():
                raise ValueError('Hidden terminal input required')
            key = getpass.getpass('DeepSeek credential (hidden; memory only): ')
            if not key or len(key) > 1024:
                raise ValueError('Invalid memory credential')
        adapter = PhaseAdapter(ROOT, PHASE, (lambda: key) if key else None)
        with make_server(ROOT / 'workspace-data', port=args.port, allow_workers=True, model_adapter=adapter) as server:
            cases = seed_phase_cases(server.store, adapter)
            print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/',
                'cases': cases['cases'], 'batch': adapter.status()['batch'],
                'credential_in_process_memory_only': bool(key), 'automatic_requests': False}, ensure_ascii=False), flush=True)
            try:
                server.serve_forever(poll_interval=.2)
            except KeyboardInterrupt:
                pass
        key = None
        return 0
    except Exception:
        print('Stopped safely. Inspect phase source binding and cumulative ledger. No automatic retry.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
