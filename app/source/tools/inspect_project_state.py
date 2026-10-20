"""Read actual local state; no credential, model call or ledger write."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from photonguard.approved_gui import authorization, DEFAULT_ORIGINAL, DEFAULT_PROGRESS
from photonguard.comparison_report import summarize
from photonguard.workflow import atomic_json


def recorded_state(root, commit, ledger_snapshot, source_clean):
    """A saved milestone is current only while both code and ledger still match."""
    path = root / 'local-validation/CURRENT_STATE.json'
    if not path.exists():
        return {'status': 'NO_CANONICAL_SNAPSHOT', 'path': str(path)}
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(saved, dict):
            raise ValueError('State must be an object')
        finance = saved.get('finance') or {}
        same_source = saved.get('source_commit') == commit and source_clean
        same_ledger = finance.get('ledger') == ledger_snapshot
        return {'status': 'CURRENT' if same_source and same_ledger else 'STALE_SNAPSHOT',
            'path': str(path), 'recorded_at_utc': saved.get('at_utc'),
            'source_matches_clean_checkout': same_source, 'ledger_matches_live_snapshot': same_ledger,
            'recorded_source_commit': saved.get('source_commit'),
            'recorded_status': saved.get('status'),
            'recorded_validation': saved.get('validation'),
            'recorded_paired_evaluation': saved.get('paired_evaluation'),
            'recorded_science': saved.get('science'),
            'runtime_binding_rechecked': False}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'status': 'UNREADABLE_CANONICAL_SNAPSHOT', 'path': str(path)}


def main():
    ledger, _ = authorization(DEFAULT_ORIGINAL)
    closed_batch = ledger.snapshot()
    phase_folder = ROOT / 'local-validation/development-phase-20cny'
    if (phase_folder / 'phase.json').exists():
        from photonguard.development_phase import ledger_for
        phase = json.loads((phase_folder / 'phase.json').read_text())
        ledger = ledger_for(phase_folder, phase['official_rates_checked_at'])
    product_folder=ROOT/'local-validation/product-phase-26cny'
    product_phase=None
    if (product_folder/'authorization.json').exists():
        from photonguard.product_phase import ProductLedger
        ledger=ProductLedger(product_folder);product_phase=ledger.phase
    snapshot = ledger.snapshot()
    records = []
    for parent in (DEFAULT_ORIGINAL, DEFAULT_PROGRESS):
        records.extend(json.loads(p.read_text(encoding='utf-8')) for p in parent.glob('slot-*-result.json'))
    plan = [{'slot': i + 1, 'case': case, 'arm': arm} for i, (case, arm) in enumerate(
        (('complete', 'A0'), ('complete', 'A1'), ('conflict', 'A0'), ('conflict', 'A1')))]
    result = {'at_utc': datetime.now(timezone.utc).isoformat(), 'development_directory': str(ROOT),
        'git_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        'git_branch': subprocess.check_output(['git', '-C', str(ROOT), 'branch', '--show-current'], text=True).strip(),
        'gui_url': 'http://127.0.0.1:8778/', 'workspace_data': str(ROOT / 'workspace-data'),
        'ledger_path': str(ledger.path), 'ledger': snapshot,
        'old_closed_batch_ledger': closed_batch,
        'old_short_term_caps_superseded': True, 'active_development_budget_cny': '20',
        'development_credit_authorized_by_owner_cny': '20', 'provider_balance_verified': False,
        'comparison': summarize(plan, records), 'r0_available': False, 'human_cost_available': False,
        'old_source_and_evidence_archives_preserved': True, 'automatic_retry': False}
    if product_phase:
        result.update(active_development_budget_cny=product_phase['cumulative_cap_cny'],
            development_credit_authorized_by_owner_cny='26 additional',
            product_phase_authorization=product_phase,
            product_incremental_requests=snapshot['attempts']-product_phase['carried']['attempts'])
    if (phase_folder / 'phase.json').exists():
        phase_records = [json.loads(p.read_text()) for p in phase_folder.glob('task-*-result.json')]
        result['historical_phase_comparison'] = summarize(plan, phase_records)
    release=ROOT/'local-validation/ai-repair-release'
    if (release/'VALIDATION_RESULTS.json').exists():
        result['historical_repair_milestone']=json.loads((release/'VALIDATION_RESULTS.json').read_text())
    if (ROOT/'workspace-data/repair-trials.json').exists():
        result['historical_user_trial_setup']=json.loads((ROOT/'workspace-data/repair-trials.json').read_text())
    clean = not subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    result['canonical_state'] = recorded_state(ROOT, result['git_commit'], snapshot, clean)
    result['history_note'] = 'Earlier comparison, milestone and trial setup records are historical; only canonical_state is checked against the current source and ledger. Runtime availability is not checked.'
    root = ROOT / 'local-validation'; root.mkdir(exist_ok=True)
    atomic_json(root / 'project-state.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
