"""Owner-authorized 20 CNY phase; carry all old reservations, never reset.

Older v2 ledgers lack usage settlement: carry their full upper reservations.
This overestimates prior expenditure rather than forgiving ambiguous charges.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import threading

from .backend import ApprovedRates, BackendAuthorization, _iso_timestamp
from .cny_budget import CnyApproval
from .gui_batch_ledger import GuiBatchLedger
from .approved_gui import source_manifest, authorization, digest_file, DEFAULT_ORIGINAL
from . import workflow_model as model, workflow_intake as intake
from .workflow import write_once

REFERENCE = 'photonguard-development-20cny-20261006'
# Internal integer overflow/abuse guard, not a renewed old 8-request allowance.
MAX_COUNTER = 1_000_000
PHASE = Path('/home/zhou/projects/PhotonGuard-development/local-validation/development-phase-20cny')
LEGACY = [
    (Path('/home/zhou/projects/PhotonGuard/local-validation/deepseek-budget.ledger.json'),
     '37bf879de4707ed6a24ce9f217d67431f58b3946705d6fa0df5a7208521c0e67'),
    (Path('/home/zhou/projects/PhotonGuard/local-validation/semantic-live-small-20261006/new-semantic-budget.ledger.json'),
     'feeadbe19eb40dc2719e48397d66b43f68249b7a6bf8fd8305aa03708e30f178'),
]


class DevelopmentLedger(GuiBatchLedger):
    def snapshot(self):
        with self._locked():
            return self._read(require_existing=True)

    def _binding(self):
        a, c = self.authorization, self.cny
        if (a.approved is not True or a.reference != REFERENCE or a.model != 'deepseek-flash'
                or a.max_calls != MAX_COUNTER or a.total_budget_usd != '3'
                or c.total_budget_cny != '20' or self.path.name != 'development-budget.ledger.json'
                or (a.rates.input_usd_per_million, a.rates.output_usd_per_million) != ('0.30', '1.20')
                or (c.input_cny_per_million, c.output_cny_per_million) != ('2', '8')
                or a.rates.source != 'https://api-docs.deepseek.com/quick_start/pricing/'
                or c.source != 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
                or not _iso_timestamp(a.rates.checked_at) or a.rates.checked_at != c.checked_at):
            raise ValueError('Development phase authorization differs')
        value = {'reference': REFERENCE, 'budget_cny': '20', 'budget_usd': '3',
                 'rates': ['0.30', '1.20', '2', '8'], 'checked_at': a.rates.checked_at,
                 'model': a.model, 'counter_guard': MAX_COUNTER}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def ledger_for(folder, checked):
    auth = BackendAuthorization(True, REFERENCE, 'deepseek-flash', '3', MAX_COUNTER,
        ApprovedRates('0.30', '1.20', checked, 'https://api-docs.deepseek.com/quick_start/pricing/'))
    cny = CnyApproval('20', '2', '8', checked, 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
    return DevelopmentLedger(auth, folder / 'development-budget.ledger.json', cny)


def public_cases():
    complete = (intake.DEMO.replace('膜层折射率为2。', '膜层折射率为1.7。')
        .replace('膜厚为300 nm。', '膜厚为250 nm。').replace('1300 nm', '1350 nm')
        .replace('1700 nm', '1650 nm').replace('采样点数为41', '采样点数为35'))
    incomplete = complete.replace('膜厚为250 nm。\n', '') + '\n另一版资料：膜层折射率为1.9，优先级尚未确认。'
    result = {}
    for name, text in (('complete', complete), ('conflict', incomplete)):
        view = intake.prepare('PG-DEV-PHASE-' + name.upper(), text)['view']
        view['packet']['synthetic'] = True
        view['packet']['request_zh'] = '公开合成开发需求，只生成待人工审核草稿；不批准任务或执行求解。'
        view.pop('input_sha256'); view['input_sha256'] = intake.semantic.digest(view)
        result[name] = {'view': view, 'text': text}
    return result


def prepare_phase(root, checked, folder=PHASE, legacy=LEGACY, original=DEFAULT_ORIGINAL):
    source = source_manifest(root)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(checked)).total_seconds()
    if not 0 <= age <= 86400:
        raise ValueError('Fresh official price verification required')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest_path = folder / 'phase.json'
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing['source'] != source:
            raise ValueError('Phase source changed; an explicit preserved-counter version transition is required')
        ledger = ledger_for(folder, existing['official_rates_checked_at'])
        ledger._read(require_existing=True)
        return existing
    ledger = ledger_for(folder, checked)
    if ledger.path.exists() or (folder / 'migration-start.json').exists():
        raise ValueError('Incomplete migration exists; do not recreate a ledger')
    carried_usd, carried_cny, attempts, live = Decimal('0'), Decimal('0'), 0, 0
    history = []
    for path, expected in legacy:
        if digest_file(path) != expected:
            raise ValueError('Frozen legacy ledger differs')
        value = json.loads(path.read_text())
        if value['schema_version'] != 2 or value['halted']:
            raise ValueError('Legacy financial state needs reconciliation')
        carried_usd += Decimal(value['reserved_usd']); carried_cny += Decimal(value['reserved_cny'])
        attempts += value['attempts']; live += value['live_provider_attempts']
        history.append({'path': str(path), 'sha256': expected, 'ledger': value,
                        'carry_policy': 'FULL_LEGACY_RESERVATION_NOT_PROVIDER_BILL'})
    old, _ = authorization(original)
    with old._locked():
        value = old._read(require_existing=True)
        if value['halted'] or value['pending'] is not None:
            raise ValueError('Unsettled old dispatch cannot be silently migrated')
        carried_usd += Decimal(value['reserved_usd']); carried_cny += Decimal(value['reserved_cny'])
        attempts += value['attempts']; live += value['live_provider_attempts']
        history.append({'path': str(old.path), 'sha256': digest_file(old.path), 'ledger': value,
                        'carry_policy': 'CHECKED_USAGE_SETTLED_CUMULATIVE'})
        result = {'schema_version': 1, 'reference': REFERENCE, 'source': source,
            'official_rates_checked_at': checked, 'owner_approved_budget_cny': '20',
            'old_short_term_caps_superseded': True, 'request_cap_from_old_batch_reused': False,
            'legacy_ledgers': history, 'carried_attempts': attempts,
            'carried_cost_upper_cny': str(carried_cny), 'old_ledgers_edited': False,
            'cases': {name: {'input_sha256': case['view']['input_sha256'],
                             'case_id': case['view']['packet']['case_id']} for name, case in public_cases().items()},
            'automatic_retry': False, 'model_credentials_retained': False}
        write_once(folder / 'migration-start.json', result)
        with ledger._locked():
            initial = ledger._empty()
            initial.update(attempts=attempts, live_provider_attempts=live,
                settled_usd=str(carried_usd), reserved_usd=str(carried_usd),
                settled_cny=str(carried_cny), reserved_cny=str(carried_cny))
            ledger._write(initial)
            ledger._read(require_existing=True)
        write_once(manifest_path, result)
    return result


class PhaseModel(model.DeepSeekSemanticAdapter):
    def _session(self, view, mode, arm):
        if mode == 'adapter_mock':
            return super()._session(view, mode, arm)
        b = self.binding
        if (mode != 'live' or not isinstance(self.ledger, DevelopmentLedger) or b is None
                or b.approved is not True or b.reference != REFERENCE
                or b.case_id != view['packet']['case_id'] or b.input_sha256 != view['input_sha256']
                or b.arm != arm or b.model != 'deepseek-flash' or b.destination != model.wire.ENDPOINT
                or b.max_turns != 2 or not callable(self.key_supplier)):
            raise model.ModelGateError('Development source/material/approval binding differs')
        self.ledger._binding()
        snapshot = self.ledger._read(require_existing=True)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.ledger.authorization.rates.checked_at)).total_seconds()
        if not 0 <= age <= 86400 or snapshot['halted'] or snapshot['pending'] is not None:
            raise model.ModelGateError('Development financial or price freshness gate closed')
        key = self.key_supplier()
        if type(key) is not str or not key or len(key) > 1024:
            raise model.ModelGateError('In-memory credential unavailable')
        return self.ledger, key, None, 2


class PhaseAdapter:
    def __init__(self, root, folder, key_supplier):
        self.root, self.folder, self.key_supplier = Path(root), Path(folder), key_supplier
        self.phase = json.loads((self.folder / 'phase.json').read_text())
        self.source = self.phase['source']
        if source_manifest(self.root) != self.source:
            raise ValueError('Live phase source is not the validated source')
        self.ledger = ledger_for(self.folder, self.phase['official_rates_checked_at'])
        self.ledger._read(require_existing=True)
        self.cases, self.lock = public_cases(), threading.Lock()

    def status(self):
        try:
            s = self.ledger.snapshot()
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.phase['official_rates_checked_at'])).total_seconds()
            available = (callable(self.key_supplier) and 0 <= age <= 86400 and not s['halted'] and s['pending'] is None
                and any(not (self.folder / f'task-{i:02d}-start.json').exists() for i in range(1, 5)))
            budget = {'reference': REFERENCE, 'requests_used': s['attempts'], 'requests_maximum': None,
                'estimated_cny': s['settled_cny'], 'reserved_cny': s['reserved_cny'],
                'carried_legacy_upper_cny': self.phase['carried_cost_upper_cny'], 'cny_maximum': '20',
                'pending': s['pending'] is not None, 'halted': s['halted']}
        except (ValueError, OSError):
            available, budget = False, {'halted': True, 'reason': '开发账本无法核验。'}
        return {'adapter_implemented': True, 'live_configured': callable(self.key_supplier),
                'live_enabled': bool(available), 'mock_transport_available': True, 'batch': budget,
                'reason': '20元开发阶段，只发送已绑定的公开合成资料。'}

    def preflight(self, view, *, mode, arm='A1'):
        if mode == 'adapter_mock':
            return
        name = next((name for name, case in self.cases.items() if case['view'] == view), None)
        if mode != 'live' or name is None or arm not in ('A0', 'A1') or not callable(self.key_supplier):
            raise model.ModelGateError('这份资料没有外部发送绑定；可保留需求或离线整理。')
        if source_manifest(self.root) != self.source:
            raise model.ModelGateError('源码已改变，尚未重新绑定；未派发。')
        number = (1 if name == 'complete' else 3) + (arm == 'A1')
        if (self.folder / f'task-{number:02d}-start.json').exists():
            raise model.ModelGateError('本项已执行或中断，已有草稿与证据保留；不重复派发。')
        snapshot = self.ledger._read(require_existing=True)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(self.phase['official_rates_checked_at'])).total_seconds()
        usd, cny = self.ledger.worst_quote()
        if (not 0 <= age <= 86400 or snapshot['halted'] or snapshot['pending'] is not None
                or Decimal(snapshot['reserved_cny']) + cny > Decimal('20')
                or Decimal(snapshot['reserved_usd']) + usd > Decimal('3')):
            raise model.ModelGateError('费用占用、未结算请求或价格期限门禁未通过；保留当前草稿。')

    def run(self, view, *, mode, arm='A1'):
        if mode == 'adapter_mock':
            return model.DeepSeekSemanticAdapter(mock_transport=model.RuleMockTransport()).run(view, mode=mode, arm=arm)
        self.preflight(view, mode=mode, arm=arm)
        name = next(name for name, case in self.cases.items() if case['view'] == view)
        if source_manifest(self.root) != self.source:
            raise model.ModelGateError('Phase source changed before dispatch')
        number = (1 if name == 'complete' else 3) + (arm == 'A1')
        with self.lock:
            write_once(self.folder / f'task-{number:02d}-start.json',
                {'case': name, 'arm': arm, 'input_sha256': view['input_sha256'],
                 'source_commit': self.source['git_commit'], 'status': 'CLAIMED_NO_REPLAY'})
            binding = model.ApprovedBinding(REFERENCE, view['packet']['case_id'], view['input_sha256'], arm,
                                            approved=True, max_turns=2)
            try:
                response = PhaseModel(binding=binding, ledger=self.ledger, key_supplier=self.key_supplier).run(view, mode='live', arm=arm)
                reviewed = intake.model_result({'view': view}, response)
                record = {'slot': number, 'case': name, 'arm': arm, 'status': response['status'],
                    'review_status': reviewed['status'], 'result': reviewed.get('result'),
                    'error': reviewed.get('error'), 'rejection_code': reviewed.get('rejection_code'),
                    'response_evidence': reviewed.get('response_evidence'), 'adapter_audit': reviewed['adapter_audit'],
                    'ledger': self.ledger.snapshot(), 'solver_calls': 0, 'source_commit': self.source['git_commit']}
                write_once(self.folder / f'task-{number:02d}-result.json', record)
                return response
            except Exception:
                write_once(self.folder / f'task-{number:02d}-failure.json',
                    {'slot': number, 'case': name, 'arm': arm, 'status': 'GENERIC_FAILURE_NO_REPLAY',
                     'exception_text_retained': False})
                raise model.ModelGateError('Development task stopped; preserve reservation and evidence') from None


def seed_phase_cases(store, adapter):
    path = adapter.folder / 'gui-cases.json'
    if path.exists():
        return json.loads(path.read_text())
    cases = {}
    for name, case in adapter.cases.items():
        for arm in ('A0', 'A1'):
            state = store._load(store.create('own')['id'])
            state['label'] = '开发阶段 · ' + ('完整需求' if name == 'complete' else '缺项与冲突') + ' · ' + arm
            value = intake.prepare(case['view']['packet']['case_id'], case['text'])
            value['view'] = case['view']; state['intake'] = value
            state['approved_comparison_arm'] = arm
            store._snapshot(state, 'phase-public-input', value); store._save(state)
            cases[name + '-' + arm] = state['id']
    result = {'cases': cases, 'data_root': str(store.root), 'no_model_calls': True}
    write_once(path, result)
    return result
