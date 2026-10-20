"""Explicit source-bound continuation of an existing cumulative approval.

No copied/reinitialized budget, arbitrary case dispatch, replay or automatic retry.
The old immutable result receipts remain in their original session directory.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import threading

from .backend import ApprovedRates, BackendAuthorization
from .cny_budget import CnyApproval
from .gui_batch_ledger import GuiBatchLedger
from . import workflow_intake as intake
from . import workflow_model as model
from .workflow import write_once

REFERENCE = 'semantic-small-gui-20261006-approved-8req-3cny'
FROZEN_BASE = '87f113727e155f4a86d417507474014c2525bb1f'
EXPECTED_ORIGINAL_APPROVAL = '903157915b60d8d6e993b28ae4bec7c6a1df9d328f79193a62ca78b85c813a00'
DEFAULT_ORIGINAL = Path('/home/zhou/projects/PhotonGuard-live-approved-20261006/local-validation/gui-live-approved-20261006')
DEFAULT_PROGRESS = Path('/home/zhou/projects/PhotonGuard-development/local-validation/approved-gui-continuation')


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_manifest(root):
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True).strip():
        raise ValueError('Source must be committed and clean before binding')
    subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', FROZEN_BASE, head], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # NUL-delimited names preserve Unicode, quotes and embedded newlines; Git's
    # human-readable quoting is not a filesystem path.
    names = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z'], text=True).split('\0')[:-1]
    hashes = {}
    for name in names:
        p = root / name
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root.resolve()):
            raise ValueError('Source path is not an owned regular file')
        hashes[name] = digest_file(p)
    return {'git_commit': head, 'files': hashes}


def authorization(original):
    plan = read(original / 'plan.json')
    if (plan.get('reference') != REFERENCE or plan.get('model') != 'deepseek-flash'
            or plan.get('maximum_http_requests') != 8 or plan.get('cny_approved_hard_limit') != '3'
            or plan.get('usd_reservation_cap') != '0.3538944'
            or plan.get('official_usd_rates_per_million') != ['0.30', '1.20']
            or plan.get('official_cny_rates_per_million_to_verify') != ['2', '8']):
        raise ValueError('Original approval differs; do not create a fresh allowance')
    checked = plan['official_rates_checked_at']
    auth = BackendAuthorization(True, REFERENCE, 'deepseek-flash', '0.3538944', 8,
        ApprovedRates('0.30', '1.20', checked, 'https://api-docs.deepseek.com/quick_start/pricing/'))
    cny = CnyApproval('3', '2', '8', checked, 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
    ledger = GuiBatchLedger(auth, original / 'new-semantic-budget.ledger.json', cny)
    if ledger._binding() != EXPECTED_ORIGINAL_APPROVAL:
        raise ValueError('Original cumulative authorization binding differs')
    return ledger, plan


def remaining_view(root, plan):
    # Rebuild only released public documents, without facts/private answers.
    fixture = read(root / 'research/intent-pilot/fixtures/needs-clarification.bundle.json')
    if fixture.get('kind') != 'synthetic_development':
        raise ValueError('Public fixture is not synthetic development material')
    documents = [{'id': d['id'], 'title': d['kind'], 'lines': d['lines']}
                 for d in fixture['documents']]
    text = '\n'.join(line for d in documents for line in d['lines'])
    view = intake.prepare('PG-DEV-CONFLICT', text)['view']
    view['packet'].update(synthetic=True,
        request_zh='项目合成开发材料；只生成供人工核对的参数草稿，不执行任何操作。', documents=documents)
    view.pop('input_sha256')
    view['input_sha256'] = intake.semantic.digest(view)
    expected = next(c for c in plan['cases'] if c['name'] == 'conflict')
    if (view['packet']['case_id'] != expected['case_id']
            or view['input_sha256'] != expected['input_sha256'] or model.wire.credential_risk(view)):
        raise ValueError('Continuation input differs from the approved material')
    intake.semantic.validate_view(view, view['input_sha256'], allow_user_material=True)
    return view, text


def prepare_migration(root, original=DEFAULT_ORIGINAL, progress=DEFAULT_PROGRESS):
    manifest = source_manifest(root)
    ledger, plan = authorization(original)
    view, _ = remaining_view(root, plan)
    progress.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = progress / 'migration.json'
    if receipt.exists():
        migration = read(receipt)
        if migration['source'] != manifest or migration['original_session'] != str(original.resolve()):
            raise ValueError('Existing migration is bound to another source/session')
        return migration
    # Use the very same POSIX budget lock as all dispatches. No ledger write.
    with ledger._locked():
        snapshot = ledger._read(require_existing=True)
        if (snapshot['halted'] or snapshot['pending'] is not None or snapshot['attempts'] != 4
                or snapshot['settled_cny'] != '0.104432000004'):
            raise ValueError('Actual cumulative state requires reconciliation before continuation')
        for slot, arm in ((1, 'A0'), (2, 'A1')):
            record = read(original / f'slot-{slot:02d}-result.json')
            if record['case'] != 'complete' or record['arm'] != arm or record['status'] != 'FINAL_RETURNED':
                raise ValueError('Completed task identities differ')
        if any((original / f'slot-{slot:02d}-start.json').exists() for slot in (3, 4)):
            raise ValueError('A remaining task has already started in the old entry')
        migration = {'schema_version': 1, 'at_utc': datetime.now(timezone.utc).isoformat(),
            'reason': 'Owner explicitly authorized version-bound GUI continuation of remaining tasks',
            'source': manifest, 'frozen_base': FROZEN_BASE, 'reference': REFERENCE,
            'original_session': str(original.resolve()), 'ledger_path': str(ledger.path.resolve()),
            'ledger_before_sha256': digest_file(ledger.path), 'carried_cumulative_ledger': snapshot,
            'remaining_input_sha256': view['input_sha256'],
            'completed_tasks_not_replayed': [1, 2], 'remaining_slots': [{'slot': 3, 'arm': 'A0'}, {'slot': 4, 'arm': 'A1'}],
            'maximum_requests_total': 8, 'maximum_cny_total': '3',
            'budget_reset': False, 'automatic_retry': False, 'credential_retained': False}
        write_once(receipt, migration)
    return migration


class ContinuationAdapter:
    def __init__(self, root, original, progress, key_supplier, *, mock_transport=None):
        self.root, self.original, self.progress = Path(root), Path(original), Path(progress)
        self.key_supplier = key_supplier
        self.mock_transport = mock_transport
        self.lock = threading.Lock()
        self.source = source_manifest(self.root)
        migration = read(self.progress / 'migration.json')
        if migration['source'] != self.source or migration['original_session'] != str(self.original.resolve()):
            raise ValueError('GUI continuation source is not bound to its migration')
        self.ledger, plan = authorization(self.original)
        self.view, self.text = remaining_view(self.root, plan)

    def status(self):
        try:
            snapshot = self.ledger.snapshot()
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.ledger.authorization.rates.checked_at)).total_seconds()
            available = (0 <= age <= 86400 and callable(self.key_supplier) and not snapshot['halted'] and snapshot['pending'] is None
                         and snapshot['attempts'] < 8
                         and any(not (self.progress / f'slot-{i:02d}-start.json').exists() for i in (3, 4)))
            budget = {'reference': REFERENCE, 'requests_used': snapshot['attempts'], 'requests_maximum': 8,
                      'estimated_cny': snapshot['settled_cny'], 'reserved_cny': snapshot['reserved_cny'], 'cny_maximum': '3',
                      'pending': snapshot['pending'] is not None, 'halted': snapshot['halted']}
        except (ValueError, OSError):
            available, budget = False, {'halted': True, 'reason': '账本无法核验，已停止派发。'}
        return {'adapter_implemented': True, 'live_configured': callable(self.key_supplier),
                'live_enabled': available, 'mock_transport_available': True, 'batch': budget,
                'reason': '只续接获批的两项公开合成资料；自有需求仍可离线整理。'}

    def run(self, view, *, mode, arm='A1'):
        if mode == 'adapter_mock':
            return model.DeepSeekSemanticAdapter(mock_transport=model.RuleMockTransport()).run(view, mode=mode, arm=arm)
        if mode != 'live' or arm not in ('A0', 'A1') or view != self.view:
            raise model.ModelGateError('此付费授权只覆盖已绑定的公开合成材料；未派发。')
        if source_manifest(self.root) != self.source:
            raise model.ModelGateError('源码已改变，须重新验证和绑定；未读取凭据。')
        slot = 3 if arm == 'A0' else 4
        with self.lock:
            if self.mock_transport is not None:
                raise model.ModelGateError('Mock injection belongs only to offline tests')
            # Validate financial/freshness gates before claiming a slot or key.
            snapshot = self.ledger.snapshot()
            instant = datetime.fromisoformat(self.ledger.authorization.rates.checked_at)
            age = (datetime.now(timezone.utc) - instant).total_seconds()
            usd, cny = self.ledger.worst_quote()
            if (not 0 <= age <= 86400 or snapshot['halted'] or snapshot['pending'] is not None
                    or snapshot['attempts'] >= 8
                    or Decimal(snapshot['reserved_usd']) + usd > Decimal('0.3538944')
                    or Decimal(snapshot['reserved_cny']) + cny > Decimal('3')):
                raise model.ModelGateError('累计次数、预留费用或价格期限门禁未通过；未派发。')
            write_once(self.progress / f'slot-{slot:02d}-start.json',
                {'slot': slot, 'case': 'conflict', 'arm': arm, 'status': 'CLAIMED_NO_REPLAY',
                 'input_sha256': view['input_sha256'], 'git_commit': self.source['git_commit'],
                 'cumulative_ledger_before': snapshot})
            binding = model.ApprovedBinding(REFERENCE, view['packet']['case_id'], view['input_sha256'], arm,
                                            approved=True, max_turns=2)
            try:
                response = model.DeepSeekSemanticAdapter(binding=binding, ledger=self.ledger,
                    key_supplier=self.key_supplier).run(view, mode='live', arm=arm)
                reviewed = intake.model_result({'view': view}, response)
                record = {'slot': slot, 'case': 'conflict', 'arm': arm, 'status': response['status'],
                    'review_status': reviewed['status'], 'result': reviewed.get('result'),
                    'error': reviewed.get('error'), 'rejection_code': reviewed.get('rejection_code'),
                    'response_evidence': reviewed.get('response_evidence'), 'adapter_audit': reviewed['adapter_audit'],
                    'ledger': self.ledger.snapshot(), 'solver_calls': 0,
                    'source_commit': self.source['git_commit'], 'human_confirmation_required': True}
                write_once(self.progress / f'slot-{slot:02d}-result.json', record)
                return response
            except Exception:
                path = self.progress / f'slot-{slot:02d}-failure.json'
                if not path.exists():
                    write_once(path, {'slot': slot, 'arm': arm, 'status': 'GENERIC_FAILURE_NO_REPLAY',
                                     'exception_text_retained': False, 'automatic_retry': False})
                raise model.ModelGateError('本项安全停止，保留累计账本和失败证据；不自动重试。') from None


def seed_cases(store, adapter):
    path = adapter.progress / 'gui-cases.json'
    if path.exists():
        existing = read(path)
        for ident in existing['cases'].values():
            store.case_dir(ident)
        return existing
    cases = {}
    for arm in ('A0', 'A1'):
        case = store.create('own')
        state = store._load(case['id'])
        state['label'] = '获批缺项/冲突对照 · ' + arm
        value = intake.prepare(adapter.view['packet']['case_id'], adapter.text)
        value['view'] = adapter.view
        state['intake'] = value
        state['approved_comparison_arm'] = arm
        store._snapshot(state, 'approved-public-input', value)
        store._save(state)
        cases[arm] = state['id']
    result = {'cases': cases, 'input_sha256': adapter.view['input_sha256'],
              'data_root': str(store.root), 'no_model_calls': True}
    write_once(path, result)
    return result
