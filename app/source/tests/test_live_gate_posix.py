"""Offline POSIX release gates for the GUI model path. No key or socket is used."""
import datetime
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from photonguard import workflow_intake as intake
from photonguard import workflow_model as model
from photonguard.backend import ApprovedRates, BackendAuthorization, TransportResponse
from photonguard.cny_budget import CnyApproval


# Use the same configured token bounds as the bounded transport. The old
# 0.0417792 fixture understated a request and stopped the second tool turn.
RESERVATION_USD = (Decimal(model.wire.INPUT_BOUND) * Decimal('0.30') +
                   Decimal(model.wire.OUTPUT_BOUND) * Decimal('1.20')) / Decimal(1000000)


def ledger_at(path, checked_at):
    reference = 'semantic-small-gui-DEV-POSIX-GATE'
    auth = BackendAuthorization(True, reference, 'deepseek-flash', '0.09', 8,
        ApprovedRates('0.30', '1.20', checked_at,
            'https://api-docs.deepseek.com/quick_start/pricing/'))
    # Synthetic limits allow exactly two current reservations, never three.
    cny = CnyApproval('0.60', '2', '8', checked_at,
        'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
    return model.SemanticBatchLedger(auth, path, cny)


def reserve_in_process(path, checked_at, start, results):
    start.wait()
    try:
        ledger_at(path, checked_at).reserve(RESERVATION_USD, True,
                                            require_existing=True)
        results.put('reserved')
    except ValueError:
        results.put('rejected')
    except Exception as exc:
        results.put('unexpected:' + type(exc).__name__)


class LiveGatePortableTests(unittest.TestCase):
    def test_missing_preprovisioned_ledger_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new-semantic-budget.ledger.json'
            checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
            ledger = ledger_at(path, checked)
            with self.assertRaisesRegex(ValueError, 'Existing approval ledger required'):
                ledger._read(require_existing=True)
            self.assertFalse(path.exists())

    def test_live_transport_requests_existing_ledger_at_reservation(self):
        class RecordingLedger(model.MockLedger):
            def reserve(self, amount, live, *, require_existing=False):
                self.required = require_existing
                return super().reserve(amount, False)
        ledger = RecordingLedger(max_calls=1)
        payload = {'model': 'deepseek-flash', 'messages': [], 'max_tokens': 4096,
            'thinking': {'type': 'disabled'}, 'stream': False}
        with patch('live_transport._urllib_transport',
                   return_value=TransportResponse(503, b'DEV')) as send:
            result = model.wire.complete(payload, 'DEV-SYNTHETIC-SENTINEL', ledger,
                require_existing_ledger=True)
        self.assertTrue(ledger.required)
        self.assertEqual(ledger.calls, 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(result['audit']['status'], 'HTTP_FAILURE')


@unittest.skipUnless(os.name == 'posix', 'POSIX fcntl/fsync gate requires Linux')
class LiveGatePosixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'new-semantic-budget.ledger.json'
        self.checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.ledger = ledger_at(self.path, self.checked_at)
        # Simulate a separately provisioned, unused approval ledger.
        with self.ledger._locked():
            self.ledger._write(self.ledger._read())

    def adapter(self, supplier=lambda: 'DEV-SYNTHETIC-SENTINEL'):
        view = intake.prepare('case-test', intake.DEMO)['view']
        binding = model.ApprovedBinding(self.ledger.authorization.reference,
            'case-test', view['input_sha256'], 'A1', approved=True)
        return view, model.DeepSeekSemanticAdapter(binding=binding,
            ledger=self.ledger, key_supplier=supplier)

    def test_separate_processes_share_one_atomic_cap_and_restart_does_not_reset(self):
        ctx = multiprocessing.get_context('spawn')
        start, results = ctx.Event(), ctx.Queue()
        workers = [ctx.Process(target=reserve_in_process,
            args=(str(self.path), self.checked_at, start, results)) for _ in range(8)]
        for worker in workers:
            worker.start()
        start.set()
        try:
            outcomes = [results.get(timeout=30) for _ in workers]
            for worker in workers:
                worker.join(timeout=30)
            self.assertTrue(all(worker.exitcode == 0 for worker in workers))
            self.assertEqual(outcomes.count('reserved'), 2, outcomes)
            self.assertEqual(outcomes.count('rejected'), 6, outcomes)
            state = ledger_at(self.path, self.checked_at).snapshot()
            self.assertEqual(state['attempts'], 2)
            self.assertEqual(state['live_provider_attempts'], 2)
            self.assertEqual(Decimal(state['reserved_usd']), 2 * RESERVATION_USD)
            with self.assertRaises(ValueError):
                ledger_at(self.path, self.checked_at).reserve(RESERVATION_USD,
                    True, require_existing=True)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=5)
            results.close()

    def test_missing_ledger_after_gui_preflight_cannot_be_recreated(self):
        def remove_then_supply():
            self.path.unlink()
            return 'DEV-SYNTHETIC-SENTINEL'
        view, adapter = self.adapter(remove_then_supply)
        with patch('live_transport._urllib_transport', side_effect=AssertionError('network forbidden')) as send:
            result = adapter.run(view, mode='live')
        self.assertEqual(result['status'], 'PREFLIGHT_OR_BUDGET_STOP')
        send.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_tool_continuation_consumes_two_persistent_attempts(self):
        view, adapter = self.adapter()
        calls = []
        def mock_send(request):
            payload = json.loads(request.body)
            calls.append(payload)
            if len(calls) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                    'id': 'dev-tool-1', 'type': 'function', 'function': {
                        'name': 'export_visible_input', 'arguments': '{}'}}]}
                finish = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': json.dumps(intake.rule_candidate(view))}
                finish = 'stop'
            body = {'model': 'deepseek-flash', 'choices': [{'finish_reason': finish,
                'message': message}], 'usage': {'prompt_tokens': 1,
                'completion_tokens': 1, 'total_tokens': 2}}
            return TransportResponse(200, json.dumps(body).encode())
        with patch('live_transport._urllib_transport', side_effect=mock_send):
            result = adapter.run(view, mode='live')
        self.assertEqual(result['status'], 'FINAL_RETURNED')
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.ledger.snapshot()['attempts'], 2)
        with patch('live_transport._urllib_transport', side_effect=AssertionError('cap exceeded')) as send:
            stopped = adapter.run(view, mode='live')
        self.assertEqual(stopped['status'], 'PREFLIGHT_OR_BUDGET_STOP')
        send.assert_not_called()
        self.assertEqual(self.ledger.snapshot()['attempts'], 2)

    def test_http_failure_consumes_one_attempt_without_secret_or_retry(self):
        view, adapter = self.adapter()
        secret = 'DEV-SYNTHETIC-PROVIDER-DETAIL'
        with patch('live_transport._urllib_transport',
                   return_value=TransportResponse(503, secret.encode())) as send:
            result = adapter.run(view, mode='live')
        self.assertEqual(result['status'], 'HTTP_FAILURE')
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.ledger.snapshot()['attempts'], 1)
        self.assertNotIn(secret, json.dumps(result))


if __name__ == '__main__':
    unittest.main()
