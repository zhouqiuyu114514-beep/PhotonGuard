"""Cumulative continuation gates, replay protection and closed GUI authority."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from photonguard import approved_gui as gui
from photonguard import workflow_intake as intake, workflow_model as model
from photonguard import workflow as wf

ROOT = Path(__file__).resolve().parents[1]


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.original = Path(self.temp.name) / 'original'; self.original.mkdir()
        self.progress = Path(self.temp.name) / 'progress'
        self.manifest = {'git_commit': 'SYNTHETIC_COMMIT', 'files': {'fixture': '0' * 64}}
        source = patch.object(gui, 'source_manifest', return_value=self.manifest)
        source.start(); self.addCleanup(source.stop)
        clock = patch.object(gui, 'datetime', wraps=datetime)
        clock_mock = clock.start(); self.addCleanup(clock.stop)
        clock_mock.now.return_value = datetime(2026, 10, 6, 13, 0, tzinfo=timezone.utc)
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        network.start(); self.addCleanup(network.stop)
        self.plan = {'reference': gui.REFERENCE, 'model': 'deepseek-flash',
            'maximum_http_requests': 8, 'cny_approved_hard_limit': '3',
            'usd_reservation_cap': '0.3538944', 'official_usd_rates_per_million': ['0.30', '1.20'],
            'official_cny_rates_per_million_to_verify': ['2', '8'],
            'official_rates_checked_at': '2026-10-06T12:15:27+00:00',
            'cases': [{'name': 'conflict', 'case_id': 'PG-DEV-CONFLICT',
                       'input_sha256': '57d7191320717b5a283ca41cc3b92b769c18708ff46b7b7ba629d9ea28304e24'}]}
        self.write('plan.json', self.plan)
        ledger, _ = gui.authorization(self.original)
        value = ledger._empty()
        value.update(attempts=4, live_provider_attempts=4, settled_usd='0.0156648',
                     reserved_usd='0.0156648', settled_cny='0.104432000004', reserved_cny='0.104432000004')
        self.write('new-semantic-budget.ledger.json', value)
        for slot, arm in ((1, 'A0'), (2, 'A1')):
            self.write(f'slot-{slot:02d}-result.json', {'slot': slot, 'case': 'complete', 'arm': arm,
                                                      'status': 'FINAL_RETURNED'})

    def write(self, name, value):
        (self.original / name).write_text(json.dumps(value), encoding='utf-8')

    def prepared(self, supplier=None):
        gui.prepare_migration(ROOT, self.original, self.progress)
        return gui.ContinuationAdapter(ROOT, self.original, self.progress, supplier)

    def test_migration_keeps_original_budget_bytes_and_counts(self):
        path = self.original / 'new-semantic-budget.ledger.json'
        before = path.read_bytes()
        receipt = gui.prepare_migration(ROOT, self.original, self.progress)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(receipt['carried_cumulative_ledger']['attempts'], 4)
        self.assertFalse(receipt['budget_reset'])
        self.assertEqual(gui.prepare_migration(ROOT, self.original, self.progress), receipt)

    def test_lost_ledger_cannot_create_fresh_allowance(self):
        (self.original / 'new-semantic-budget.ledger.json').unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            gui.prepare_migration(ROOT, self.original, self.progress)
        self.assertFalse((self.original / 'new-semantic-budget.ledger.json').exists())

    def test_halted_or_pending_state_refuses_migration(self):
        path = self.original / 'new-semantic-budget.ledger.json'
        original = gui.read(path)
        for field, value in (('halted', True), ('attempts', 5)):
            changed = dict(original); changed[field] = value
            self.write(path.name, changed)
            with self.assertRaises(ValueError): gui.prepare_migration(ROOT, self.original, self.progress)

    def test_changed_source_or_plan_cannot_bind_again(self):
        self.prepared()
        with patch.object(gui, 'source_manifest', return_value={'git_commit': 'CHANGED', 'files': {}}):
            with self.assertRaises(ValueError): gui.prepare_migration(ROOT, self.original, self.progress)
        plan = dict(self.plan); plan['maximum_http_requests'] = 12
        self.write('plan.json', plan)
        with self.assertRaises(ValueError): gui.authorization(self.original)

    def test_wrong_material_precedes_key_or_slot_claim(self):
        supplier = Mock(side_effect=AssertionError('Must not read key'))
        adapter = self.prepared(supplier)
        view = intake.prepare('unapproved-own-material', '膜层折射率为2。')['view']
        with self.assertRaises(model.ModelGateError): adapter.run(view, mode='live', arm='A0')
        supplier.assert_not_called()
        self.assertFalse((self.progress / 'slot-03-start.json').exists())

    def test_rejected_final_is_persisted_and_cannot_replay(self):
        adapter = self.prepared(Mock(return_value='SYNTHETIC_MEMORY_ONLY'))
        response = {'status': 'FINAL_RETURNED', 'raw_final': '```json\n{}\n```',
            'actual_model_calls': 0, 'audits': [], 'submissions': [], 'mode': 'REAL_MODEL',
            'solver_calls': 0, 'tool_calls': 0}
        with patch.object(model.DeepSeekSemanticAdapter, 'run', return_value=response) as run:
            adapter.run(adapter.view, mode='live', arm='A0')
            with self.assertRaises(FileExistsError): adapter.run(adapter.view, mode='live', arm='A0')
            self.assertEqual(run.call_count, 1)
        record = gui.read(self.progress / 'slot-03-result.json')
        self.assertEqual(record['review_status'], 'FAILED')
        self.assertEqual(record['rejection_code'], 'INVALID_JSON')
        self.assertIsNone(record['response_evidence']['body'])

    def test_interrupt_retains_claim_and_generic_evidence_without_exception(self):
        adapter = self.prepared(Mock(return_value='SYNTHETIC_MEMORY_ONLY'))
        with patch.object(model.DeepSeekSemanticAdapter, 'run', side_effect=RuntimeError('SYNTHETIC_PRIVATE_EXCEPTION')):
            with self.assertRaises(model.ModelGateError): adapter.run(adapter.view, mode='live', arm='A1')
        evidence = (self.progress / 'slot-04-failure.json').read_text()
        self.assertNotIn('SYNTHETIC_PRIVATE_EXCEPTION', evidence)
        with self.assertRaises(FileExistsError): adapter.run(adapter.view, mode='live', arm='A1')

    def test_exhaustion_precedes_credential_and_claim(self):
        supplier = Mock(side_effect=AssertionError('Must not read key'))
        adapter = self.prepared(supplier)
        path = self.original / 'new-semantic-budget.ledger.json'
        value = gui.read(path); value['attempts'] = value['live_provider_attempts'] = 8
        self.write(path.name, value)
        self.assertFalse(adapter.status()['live_enabled'])
        with self.assertRaises(model.ModelGateError): adapter.run(adapter.view, mode='live', arm='A0')
        supplier.assert_not_called()
        self.assertFalse((self.progress / 'slot-03-start.json').exists())

    def test_seeded_gui_cases_keep_same_input_and_do_not_run(self):
        adapter = self.prepared(None)
        store = wf.WorkflowStore(Path(self.temp.name) / 'workspace', allow_workers=False, model_adapter=adapter)
        self.addCleanup(store.close)
        cases = gui.seed_cases(store, adapter)
        hashes = []
        for arm, ident in cases['cases'].items():
            state = store.get(ident)
            hashes.append(state['intake']['view']['input_sha256'])
            self.assertEqual(state['approved_comparison_arm'], arm)
            self.assertIsNone(state['approval']); self.assertIsNone(state['job'])
            self.assertEqual(state['intake']['model_calls'], 0)
        self.assertEqual(hashes, [adapter.view['input_sha256']] * 2)
        self.assertEqual(gui.seed_cases(store, adapter), cases)

    def test_json_output_parameter_is_shared_by_both_arms(self):
        view = intake.prepare('test-json-output', intake.DEMO)['view']
        for arm in ('A0', 'A1'):
            calls = []
            delegate = model.RuleMockTransport()
            def transport(request):
                calls.append(json.loads(request.body))
                return delegate(request)
            r = model.DeepSeekSemanticAdapter(mock_transport=transport).run(view, mode='adapter_mock', arm=arm)
            self.assertEqual(r['status'], 'FINAL_RETURNED')
            self.assertTrue(all(c['response_format'] == {'type': 'json_object'} for c in calls))

    def test_four_mock_http_turns_continue_four_to_eight_without_reset(self):
        supplier = Mock(return_value='SYNTHETIC_MEMORY_ONLY')
        adapter = self.prepared(supplier)
        provider = Mock(side_effect=model.RuleMockTransport())
        with (patch.object(model.wire, '_urllib_transport', provider),
              patch.object(model, 'datetime', wraps=datetime) as clock):
            clock.now.return_value = datetime(2026, 10, 6, 13, 0, tzinfo=timezone.utc)
            for arm in ('A0', 'A1'):
                result = adapter.run(adapter.view, mode='live', arm=arm)
                self.assertEqual(result['status'], 'FINAL_RETURNED')
            self.assertEqual(provider.call_count, 4)
            self.assertEqual(supplier.call_count, 2)
            self.assertEqual(adapter.ledger.snapshot()['attempts'], 8)
            self.assertFalse(adapter.status()['live_enabled'])
            with self.assertRaises(model.ModelGateError):
                adapter.run(adapter.view, mode='live', arm='A0')
            self.assertEqual(provider.call_count, 4)
        self.assertEqual(adapter.ledger.path, self.original / 'new-semantic-budget.ledger.json')
        self.assertGreater(float(adapter.ledger.snapshot()['settled_cny']), 0.104432)


if __name__ == '__main__':
    unittest.main()
