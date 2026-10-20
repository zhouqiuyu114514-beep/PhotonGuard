"""20 CNY migration, refusal-contract regressions and semantic boundaries."""
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from photonguard import development_phase as phase
from photonguard import workflow_intake as intake, workflow_model as model
from photonguard.approved_gui import authorization
from photonguard.response_contract import response_schema
from photonguard.intake_response import ResponseRejected

ROOT = Path(__file__).resolve().parents[1]


class ContractRegressionTests(unittest.TestCase):
    def test_real_rejected_refusal_returns_specific_controlled_reason(self):
        from tools.run_gui_live_comparison import views
        view = views()[1][1]
        for arm in ('a0', 'a1'):
            c = json.loads((ROOT / f'tests/fixtures/rejected-{arm}-sanitized.json').read_text())
            with self.assertRaises(ResponseRejected) as caught:
                intake.review({'view': view}, 'offline', json.dumps(c))
            self.assertEqual(caught.exception.reason_code, 'SEMANTIC_REFUSAL_CODES')

    def test_only_refusal_fix_still_cannot_confirm_frequency_as_wavelength(self):
        from tools.run_gui_live_comparison import views
        view = views()[1][1]
        c = json.loads((ROOT / 'tests/fixtures/rejected-a0-sanitized.json').read_text())
        c['refusal'] = {'reason_codes': [], 'text': None}
        r = intake.review({'view': view}, 'offline', json.dumps(c))
        self.assertFalse(r['confirmable'])
        self.assertTrue(any('频率点数不能代替' in p for p in r['scope_problems']))
        self.assertEqual(c['fields']['wavelength_samples']['value'], 21)  # Never rewrite the original mistake.

    def test_review_and_prompt_publish_same_aligned_schema(self):
        view = intake.prepare('schema-test', intake.DEMO)['view']
        schema = response_schema(intake)
        result = model.PublicTools(view).invoke({'function': {'name': 'read_public_material',
            'arguments': json.dumps({'name': 'response_schema'})}})
        self.assertEqual(json.loads(result['text']), schema)
        self.assertNotEqual(schema['$id'], 'urn:photonguard:semantic-intake-response:1')
        self.assertEqual(set(schema['properties']['fields']['required']), set(intake.semantic.KEYS))

    def test_only_script_evidence_is_blocked_without_guessing(self):
        view = intake.prepare('source-test', intake.DEMO)['view']
        view['packet']['documents'][0]['title'] = 'ast_observation'
        view.pop('input_sha256'); view['input_sha256'] = intake.semantic.digest(view)
        candidate = intake.rule_candidate(view)
        r = intake.review({'view': view}, 'offline', json.dumps(candidate))
        self.assertFalse(r['confirmable'])
        self.assertTrue(any('只有待检脚本' in p for p in r['scope_problems']))

    def test_a1_must_review_candidate_before_final_while_a0_has_same_tools(self):
        view = intake.prepare('shared-tools-test', intake.DEMO)['view']
        first = {}
        for arm in ('A0', 'A1'):
            delegate = model.RuleMockTransport()
            def send(request):
                first.setdefault(arm, json.loads(request.body))
                return delegate(request)
            model.DeepSeekSemanticAdapter(mock_transport=send).run(view, mode='adapter_mock', arm=arm)
        self.assertEqual(first['A0']['tools'], first['A1']['tools'])
        self.assertEqual(first['A0']['messages'][1], first['A1']['messages'][1])
        self.assertEqual(first['A0']['tool_choice'], 'auto')
        self.assertEqual(first['A1']['tool_choice']['function']['name'], 'review_public_candidate')


class PhaseFinancialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'phase'
        self.original = self.root / 'old-gui'; self.original.mkdir()
        self.checked = '2026-10-06T13:00:00+00:00'
        source = patch.object(phase, 'source_manifest', return_value={'git_commit': 'SYNTHETIC', 'files': {}})
        source.start(); self.addCleanup(source.stop)
        clock = patch.object(phase, 'datetime', wraps=datetime)
        now = clock.start(); self.addCleanup(clock.stop)
        now.now.return_value = datetime(2026, 10, 6, 13, 10, tzinfo=timezone.utc)
        block = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        block.start(); self.addCleanup(block.stop)
        plan = {'reference': 'semantic-small-gui-20261006-approved-8req-3cny', 'model': 'deepseek-flash',
            'maximum_http_requests': 8, 'cny_approved_hard_limit': '3', 'usd_reservation_cap': '0.3538944',
            'official_usd_rates_per_million': ['0.30', '1.20'], 'official_cny_rates_per_million_to_verify': ['2', '8'],
            'official_rates_checked_at': '2026-10-06T12:15:27+00:00'}
        self.write(self.original / 'plan.json', plan)
        old, _ = authorization(self.original)
        state = old._empty(); state.update(attempts=6, live_provider_attempts=6,
            reserved_cny='0.142144000006', settled_cny='0.142144000006',
            reserved_usd='0.0213216', settled_usd='0.0213216')
        self.write(old.path, state)
        self.legacy = []
        for number, usd, cny, attempts in ((1, '0.0417792', '0.278528000001', 1),
                                            (2, '0.5308416', '3.538944000012', 12)):
            p = self.root / f'legacy-{number}.json'
            self.write(p, {'schema_version': 2, 'halted': False, 'attempts': attempts,
                           'live_provider_attempts': attempts, 'reserved_usd': usd, 'reserved_cny': cny})
            self.legacy.append((p, hashlib.sha256(p.read_bytes()).hexdigest()))

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def prepared(self):
        record = phase.prepare_phase(ROOT, self.checked, self.folder, self.legacy, self.original)
        return record, phase.ledger_for(self.folder, self.checked)

    def test_all_old_counts_and_full_upper_reservations_are_carried(self):
        before = [(p, p.read_bytes()) for p, _ in self.legacy]
        old_path = self.original / 'new-semantic-budget.ledger.json'; before.append((old_path, old_path.read_bytes()))
        record, ledger = self.prepared()
        self.assertEqual(ledger.snapshot()['attempts'], 19)
        self.assertEqual(ledger.snapshot()['reserved_cny'], '3.959616000019')
        self.assertEqual(record['carried_attempts'], 19)
        self.assertTrue(record['old_short_term_caps_superseded'])
        self.assertTrue(all(p.read_bytes() == data for p, data in before))

    def test_new_requests_exceed_old_eight_ceiling_but_settle_within_twenty(self):
        _, ledger = self.prepared()
        old = Decimal(ledger.snapshot()['reserved_cny'])
        for _ in range(10):
            reservation = ledger.reserve_worst(True)
            ledger.settle_usage(reservation['pending']['id'], {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200})
        self.assertEqual(ledger.snapshot()['attempts'], 29)
        self.assertGreater(Decimal(ledger.snapshot()['reserved_cny']), old)
        self.assertLess(Decimal(ledger.snapshot()['reserved_cny']), Decimal('20'))

    def test_twenty_cny_limit_precedes_dispatch_and_is_not_refunded(self):
        _, ledger = self.prepared()
        with ledger._locked():
            state = ledger._read(require_existing=True)
            state.update(reserved_usd='2.9', settled_usd='2.9', reserved_cny='19.333333333334', settled_cny='19.333333333334')
            ledger._write(state)
        with self.assertRaises(ValueError): ledger.reserve_worst(True)
        self.assertEqual(ledger.snapshot()['attempts'], 19)

    def test_deleted_or_incomplete_phase_cannot_be_reinitialized(self):
        _, ledger = self.prepared(); ledger.path.unlink()
        with self.assertRaises(ValueError): ledger.snapshot()
        with self.assertRaises(ValueError): self.prepared()
        self.assertFalse(ledger.path.exists())

    def test_changed_legacy_hash_or_pending_gui_stops_migration(self):
        p, _ = self.legacy[0]; p.write_text('{}')
        with self.assertRaises(ValueError): self.prepared()
        self.assertFalse((self.folder / 'development-budget.ledger.json').exists())

    def test_interruption_retains_full_reservation_and_blocks_further_requests(self):
        _, ledger = self.prepared()
        reservation = ledger.reserve_worst(True)
        reopened = phase.ledger_for(self.folder, self.checked)
        self.assertEqual(reopened.snapshot()['pending'], reservation['pending'])
        with self.assertRaises(ValueError): reopened.reserve_worst(True)


if __name__ == '__main__':
    unittest.main()
