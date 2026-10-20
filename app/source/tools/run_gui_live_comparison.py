"""One authorized GUI-adapter comparison batch; no unattended replay.

--preflight is offline and never reads a key. --run requires the original
authorized Linux session and fresh official tariff verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from photonguard import workflow_intake as intake
from photonguard import workflow_model as model
from photonguard.backend import ApprovedRates, BackendAuthorization
from photonguard.cny_budget import CnyApproval
from photonguard.gui_batch_ledger import GuiBatchLedger, CONTEXT_INPUT_BOUND, OUTPUT_BOUND
from photonguard.workflow import write_once


BASE_COMMIT = '2835f6d864fc302503dd8c439a7348b153bd7272'
REFERENCE = 'semantic-small-gui-20261006-approved-8req-3cny'
SESSION = ROOT / 'local-validation/gui-live-approved-20261006'
MODEL = 'deepseek-flash'
MAX_REQUESTS = 8
USD_CAP = Decimal('0.3538944')
CNY_CAP = Decimal('3')
USD_INPUT, USD_OUTPUT = Decimal('0.30'), Decimal('1.20')
CNY_INPUT, CNY_OUTPUT = Decimal('2'), Decimal('8')
USD_SOURCE = 'https://api-docs.deepseek.com/quick_start/pricing/'
CNY_SOURCE = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
# The published deepseek-flash context is 1M tokens. One Mi input tokens
# conservatively covers the entire prompt, including tools and continuation.
SOFTWARE_COST_BOUND_PROVEN = True
FIXTURE = ROOT / 'research/intent-pilot/fixtures/needs-clarification.bundle.json'
SOURCE_SHA256 = {
    'photonguard/workflow.py': 'a10927b822e3a590100adbebcb9662a5a695d82e74b671e6742be7351e6a7434',
    'photonguard/workflow_model.py': '1a042b710e01dda4e0e24a3a4ef987e230e706a085a4b36c20940dba2d33d43b',
    'photonguard/workflow_intake.py': 'fefcfb2dcca07714582c6da9d1a116a4bc2f34fda6c2e434ed0ab60bcc950ff7',
    'photonguard/gui_batch_ledger.py': '27667eeba53a26131c314ac4fcb8a1c0e3a76d2078f713531eb7a7156ec415db',
    'photonguard/cny_budget.py': '25d9343c19cc9283ac9c9f5b9377de6949d2d6064e9228b918bcc073bfbb8c83',
    'research/evaluation-coordinator/live_transport.py': 'abd4fcd242cac349cc88cd93824e53076dc328ca22663c2f2f48141ee6eacd8f',
    'research/evaluation-coordinator/batch_ledger.py': 'c45f92adcfff6a0fc36dcfd5a4129a399deb490306403de22e4551674bdd736a',
    'research/intent-pilot/fixtures/needs-clarification.bundle.json': '6dc27f098078327086677597463c0cbc3f710498aee78f9d3a13b700ada0ea45',
    'research/intent-pilot/public-contract/semantic_contract.json': '9085ed2ff3b817db8404a492a253408dc4ea89fb2005a1e0b36b7a49c159cb9a',
}


def source_check(*, require_git=False):
    for relative, expected in SOURCE_SHA256.items():
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('Validated source mismatch: ' + relative)
    if require_git:
        if os.name != 'posix':
            raise ValueError('Live batch requires the authorized Linux checkout')
        head = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        changed = set(subprocess.check_output(['git', '-C', str(ROOT), 'diff', 'HEAD',
                                              '--name-only'], text=True).splitlines())
        # The isolated patch deliberately changes this tracked transport. Its
        # exact bytes are pinned above; all other tracked changes are refused.
        if head != BASE_COMMIT or changed != {'research/evaluation-coordinator/live_transport.py'}:
            raise ValueError('Validated commit or tracked source differs')


def _synthetic_view(case_id, source_text, documents=None):
    view = intake.prepare(case_id, source_text)['view']
    view['packet']['synthetic'] = True
    view['packet']['request_zh'] = '项目合成开发材料；只生成供人工核对的参数草稿，不执行任何操作。'
    if documents is not None:
        view['packet']['documents'] = documents
    else:
        view['packet']['documents'][0]['title'] = '项目合成单膜开发案例'
    view.pop('input_sha256')
    view['input_sha256'] = intake.semantic.digest(view)
    intake.semantic.validate_view(view, view['input_sha256'], allow_user_material=True)
    if model.wire.credential_risk(view):
        raise ValueError('Synthetic material failed credential screening')
    return view


def views():
    complete = _synthetic_view('PG-DEV-COMPLETE', intake.DEMO)
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    if fixture.get('kind') != 'synthetic_development':
        raise ValueError('Second input is not a project synthetic fixture')
    docs = [{'id': doc['id'], 'title': doc['kind'], 'lines': doc['lines']}
            for doc in fixture['documents']]
    for doc in docs:
        if any(intake.scrub(line) != line for line in doc['lines']):
            raise ValueError('Synthetic fixture contains credential-shaped text')
    incomplete = _synthetic_view('PG-DEV-CONFLICT',
        '\n'.join(line for doc in docs for line in doc['lines']), docs)
    return [('complete', complete), ('conflict', incomplete)]


def reservation():
    usd = (Decimal(CONTEXT_INPUT_BOUND) * USD_INPUT +
           Decimal(OUTPUT_BOUND) * USD_OUTPUT) / Decimal(1000000)
    cny = (Decimal(CONTEXT_INPUT_BOUND) * CNY_INPUT +
           Decimal(OUTPUT_BOUND) * CNY_OUTPUT) / Decimal(1000000)
    if usd > USD_CAP or cny >= CNY_CAP:
        raise ValueError('A worst-case provider-context request exceeds the approval')
    return usd, cny


def checked_at(value):
    if not value:
        raise ValueError('Official USD and CNY prices must be checked before running')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - instant).total_seconds()
    except (TypeError, ValueError):
        raise ValueError('Invalid UTC price-check timestamp') from None
    if instant.tzinfo is None or not 0 <= age <= 86400:
        raise ValueError('Official price check must be within the past 24 hours')
    return instant.astimezone(timezone.utc).isoformat()


def preflight():
    source_check()
    pairs = views()
    usd, cny = reservation()
    return {'base_commit': BASE_COMMIT, 'model': MODEL, 'source_kind': 'PROJECT_SYNTHETIC_ONLY',
            'cases': [{'name': name, 'case_id': view['packet']['case_id'],
                       'input_sha256': view['input_sha256']} for name, view in pairs],
            'arms': ['A0', 'A1'], 'maximum_http_requests': MAX_REQUESTS,
            'maximum_turns_per_arm': 2, 'automatic_retries': 0,
            'context_input_token_reservation': CONTEXT_INPUT_BOUND,
            'output_token_reservation': OUTPUT_BOUND,
            'usd_peak_per_request_reservation': str(usd),
            'cny_peak_per_request_reservation_before_rounding': str(cny),
            'usd_reservation_cap': str(USD_CAP), 'cny_approved_hard_limit': str(CNY_CAP),
            'official_usd_rates_per_million': [str(USD_INPUT), str(USD_OUTPUT)],
            'official_cny_rates_per_million_to_verify': [str(CNY_INPUT), str(CNY_OUTPUT)],
            'official_sources': [USD_SOURCE, CNY_SOURCE],
            'requires_fresh_official_cny_verification': True,
            'software_cost_bound_proven': SOFTWARE_COST_BOUND_PROVEN,
            'live_entry_enabled': SOFTWARE_COST_BOUND_PROVEN,
            'native_bridge_enabled': False, 'solver_calls_allowed': 0}


def safe_ledger_snapshot(ledger):
    try:
        return ledger.snapshot()
    except Exception:
        return {'status': 'LEDGER_UNREADABLE_STOP'}


def read_key():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError('A local interactive terminal is required for hidden credential input')
    key = getpass.getpass('DeepSeek API credential (hidden; process memory only): ')
    if not key or len(key) > 1024:
        raise ValueError('No valid in-memory credential was supplied')
    return key


def run(verified_at):
    source_check(require_git=True)
    verified_at = checked_at(verified_at)
    plan = preflight()
    if not SOFTWARE_COST_BOUND_PROVEN:
        raise ValueError('Pre-dispatch billed prompt-token bound is unproven; live entry closed')
    if SESSION.exists():
        raise ValueError('This approved batch already has a session; inspect it, do not restart')
    SESSION.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    SESSION.mkdir(mode=0o700)
    plan.update(reference=REFERENCE, official_rates_checked_at=verified_at,
                session_status='ONE_SHOT_NO_REPLAY')
    write_once(SESSION / 'plan.json', plan)
    auth = BackendAuthorization(True, REFERENCE, MODEL, str(USD_CAP), MAX_REQUESTS,
        ApprovedRates(str(USD_INPUT), str(USD_OUTPUT), verified_at, USD_SOURCE))
    cny_approval = CnyApproval(str(CNY_CAP), str(CNY_INPUT), str(CNY_OUTPUT),
                               verified_at, CNY_SOURCE)
    ledger = GuiBatchLedger(auth,
        SESSION / 'new-semantic-budget.ledger.json', cny_approval)
    with ledger._locked():
        ledger._write(ledger._read())
    key = read_key()
    completed = []
    for case_name, view in views():
        for arm in ('A0', 'A1'):
            slot = len(completed) + 1
            start = {'slot': slot, 'case': case_name, 'arm': arm,
                     'input_sha256': view['input_sha256'], 'status': 'STARTED_NO_REPLAY'}
            write_once(SESSION / f'slot-{slot:02d}-start.json', start)
            binding = model.ApprovedBinding(REFERENCE, view['packet']['case_id'],
                view['input_sha256'], arm, approved=True, max_turns=2)
            adapter = model.DeepSeekSemanticAdapter(binding=binding, ledger=ledger,
                                                    key_supplier=lambda: key)
            try:
                response = adapter.run(view, mode='live', arm=arm)
                reviewed = intake.model_result({'view': view, 'result': None,
                    'confirmation': None}, response)
                record = {'slot': slot, 'case': case_name, 'arm': arm,
                    'status': response['status'], 'review_status': reviewed['status'],
                    'result': reviewed.get('result'), 'error': reviewed.get('error'),
                    'adapter_audit': reviewed['adapter_audit'],
                    'ledger': safe_ledger_snapshot(ledger), 'native_bridge_enabled': False,
                    'human_confirmation_required': True, 'solver_calls': 0}
            except Exception:
                record = {'slot': slot, 'case': case_name, 'arm': arm,
                    'status': 'GENERIC_FAILURE_STOP', 'error': 'See local ledger and start receipt; no automatic retry.',
                    'ledger': safe_ledger_snapshot(ledger), 'native_bridge_enabled': False,
                    'human_confirmation_required': True, 'solver_calls': 0}
            write_once(SESSION / f'slot-{slot:02d}-result.json', record)
            completed.append({'slot': slot, 'case': case_name, 'arm': arm,
                              'status': record['status'], 'review_status': record.get('review_status')})
            if record['status'] != 'FINAL_RETURNED' or record.get('review_status') != 'REVIEW':
                break
        else:
            continue
        break
    complete = (len(completed) == 4 and all(
        item['status'] == 'FINAL_RETURNED' and item.get('review_status') == 'REVIEW'
        for item in completed))
    summary = {'completed_slots': completed, 'planned_slots': 4,
               'partial': not complete, 'ledger': safe_ledger_snapshot(ledger),
               'native_bridge_enabled': False, 'solver_calls': 0,
               'no_automatic_retry_or_resume': True}
    write_once(SESSION / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='Single approved synthetic comparison batch')
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--preflight', action='store_true')
    choice.add_argument('--run', action='store_true')
    parser.add_argument('--official-rates-verified-at', metavar='UTC_TIMESTAMP')
    args = parser.parse_args(argv)
    try:
        result = run(args.official_rates_verified_at) if args.run else preflight()
    except Exception:
        print('Stopped safely. Inspect the local plan, ledger and receipts; no automatic retry.',
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
