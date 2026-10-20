"""Offline tests of the new, separate context-bound CNY batch ledger."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from photonguard.backend import ApprovedRates, BackendAuthorization, TransportResponse
from photonguard.cny_budget import CnyApproval
from photonguard.gui_batch_ledger import GuiBatchLedger, CONTEXT_INPUT_BOUND, OUTPUT_BOUND
from photonguard import workflow_model as model
from tools import run_gui_live_comparison as batch


def approvals():
    checked = datetime.now(timezone.utc).isoformat()
    auth = BackendAuthorization(True, 'semantic-small-gui-20261006-approved-8req-3cny',
        'deepseek-flash', '0.3538944', 8,
        ApprovedRates('0.30', '1.20', checked,
                      'https://api-docs.deepseek.com/quick_start/pricing/'))
    cny = CnyApproval('3', '2', '8', checked,
                      'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/')
    return auth, cny


def compete(path, auth, cny, ready, queue):
    ledger = GuiBatchLedger(auth, path, cny)
    ready.wait()
    try:
        ledger.reserve_worst(True)
        queue.put('reserved')
    except ValueError:
        queue.put('blocked')


def compete_settle(path, auth, cny, reservation_id, ready, queue):
    ledger = GuiBatchLedger(auth, path, cny)
    ready.wait()
    try:
        ledger.settle_usage(reservation_id,
            {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200})
        queue.put('settled')
    except ValueError:
        queue.put('blocked')


class GuiBatchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'new-semantic-budget.ledger.json'
        self.auth, self.cny = approvals()
        self.guard = threading.RLock()
        if os.name == 'nt':
            @contextmanager
            def locked(_ledger):
                with self.guard:
                    yield
            def write(ledger, value):
                ledger.path.write_text(json.dumps(value), encoding='utf-8')
            for target, name, replacement in ((GuiBatchLedger, '_locked', locked),
                                               (GuiBatchLedger, '_write', write),
                                               (os, 'O_NOFOLLOW', 0)):
                slot = patch.object(target, name, replacement, create=True)
                slot.start()
                self.addCleanup(slot.stop)
        self.ledger = GuiBatchLedger(self.auth, self.path, self.cny)
        with self.ledger._locked():
            self.ledger._write(self.ledger._read())

    def usage(self, prompt=100, completion=100):
        return {'prompt_tokens': prompt, 'completion_tokens': completion,
                'total_tokens': prompt + completion}

    def test_worst_quote_and_lock_settlement_release(self):
        self.assertEqual(self.ledger.worst_quote(),
                         (Decimal('0.319488'), Decimal('2.129920000001')))
        first = self.ledger.reserve_worst(True)
        self.assertEqual(first['reserved_cny'], '2.129920000001')
        self.assertEqual(first['attempts'], 1)
        settled = self.ledger.settle_usage(first['pending']['id'], self.usage())
        self.assertIsNone(settled['pending'])
        self.assertEqual(Decimal(settled['reserved_cny']), Decimal('0.001000000001'))
        second = self.ledger.reserve_worst(True)
        self.assertEqual(second['attempts'], 2)
        self.assertLessEqual(Decimal(second['reserved_cny']), Decimal('3'))

    def test_pending_survives_crash_and_blocks_restart(self):
        first = self.ledger.reserve_worst(True)
        reopened = GuiBatchLedger(self.auth, self.path, self.cny)
        self.assertEqual(reopened.snapshot()['pending']['id'], first['pending']['id'])
        with self.assertRaises(ValueError):
            reopened.reserve_worst(True)
        self.assertEqual(reopened.snapshot()['attempts'], 1)
        self.assertEqual(Decimal(reopened.snapshot()['reserved_cny']), Decimal('2.129920000001'))

    def test_bad_usage_does_not_release_and_halt_keeps_reservation(self):
        bad = [None, {}, self.usage(CONTEXT_INPUT_BOUND + 1, 0),
               self.usage(0, OUTPUT_BOUND + 1),
               {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 3},
               dict(self.usage(), completion_tokens_details={'reasoning_tokens': 1}),
               dict(self.usage(), prompt_cache_hit_tokens=60,
                    prompt_cache_miss_tokens=60)]
        first = self.ledger.reserve_worst(True)
        token = first['pending']['id']
        for entry in bad:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.ledger.settle_usage(token, entry)
            self.assertEqual(self.ledger.snapshot()['pending']['id'], token)
        self.ledger.halt()
        stopped = self.ledger.snapshot()
        self.assertTrue(stopped['halted'])
        self.assertEqual(stopped['reserved_cny'], first['reserved_cny'])
        with self.assertRaises(ValueError):
            self.ledger.reserve_worst(True)

    def test_duplicate_and_stale_settlement_cannot_release_twice(self):
        first = self.ledger.reserve_worst(True)
        old_id = first['pending']['id']
        self.ledger.settle_usage(old_id, self.usage())
        with self.assertRaises(ValueError):
            self.ledger.settle_usage(old_id, self.usage())
        second = self.ledger.reserve_worst(True)
        before = self.ledger.snapshot()
        with self.assertRaises(ValueError):
            self.ledger.settle_usage(old_id, self.usage())
        self.assertEqual(self.ledger.snapshot(), before)
        self.ledger.settle_usage(second['pending']['id'], self.usage())

    def test_eight_total_attempts_even_after_each_settlement(self):
        for _ in range(8):
            value = self.ledger.reserve_worst(True)
            self.ledger.settle_usage(value['pending']['id'], self.usage())
        self.assertEqual(self.ledger.snapshot()['attempts'], 8)
        self.assertEqual(self.ledger.snapshot()['live_provider_attempts'], 8)
        with self.assertRaises(ValueError):
            self.ledger.reserve_worst(True)

    def test_next_worst_quote_stops_after_expensive_valid_usage(self):
        first = self.ledger.reserve_worst(True)
        self.ledger.settle_usage(first['pending']['id'], self.usage(450000, 100))
        self.assertLess(Decimal(self.ledger.snapshot()['reserved_cny']), Decimal('3'))
        with self.assertRaises(ValueError):
            self.ledger.reserve_worst(True)
        self.assertEqual(self.ledger.snapshot()['attempts'], 1)

    def test_transport_failure_and_invalid_usage_keep_worst_reservation(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                path = Path(self.folder.name) / ('bad' if invalid else 'failed')
                path.mkdir()
                ledger = GuiBatchLedger(self.auth, path / self.path.name, self.cny)
                with ledger._locked():
                    ledger._write(ledger._read())
                payload = {'model': 'deepseek-flash', 'messages': [{'role': 'user', 'content': 'synthetic'}],
                           'tools': [], 'max_tokens': OUTPUT_BOUND,
                           'thinking': {'type': 'disabled'}, 'stream': False}
                if invalid:
                    def send(_request):
                        return TransportResponse(200, json.dumps({
                            'model': 'deepseek-flash', 'choices': [{'finish_reason': 'stop',
                            'message': {'role': 'assistant', 'content': 'synthetic'}}],
                            'usage': {'prompt_tokens': 2}}).encode())
                else:
                    def send(_request):
                        raise OSError('synthetic transport failure')
                result = model.wire.complete(payload, 'SYNTHETIC-ONLY', ledger,
                                             transport=send, require_existing_ledger=True)
                self.assertIn(result['audit']['status'], ('TRANSPORT_FAILURE', 'INVALID_USAGE'))
                state = ledger.snapshot()
                self.assertTrue(state['halted'])
                self.assertIsNotNone(state['pending'])
                self.assertEqual(Decimal(state['reserved_cny']), Decimal('2.129920000001'))

    def test_transport_releases_only_complete_matching_response(self):
        payload = {'model': 'deepseek-flash', 'messages': [{'role': 'user', 'content': 'synthetic'}],
                   'tools': [], 'max_tokens': OUTPUT_BOUND,
                   'thinking': {'type': 'disabled'}, 'stream': False}
        def send(_request):
            return TransportResponse(200, json.dumps({
                'model': 'deepseek-flash', 'choices': [{'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': 'synthetic only'}}],
                'usage': self.usage()}).encode())
        result = model.wire.complete(payload, 'SYNTHETIC-ONLY', self.ledger,
                                     transport=send, require_existing_ledger=True)
        self.assertEqual(result['audit']['status'], 'ASSISTANT_RETURNED')
        self.assertTrue(result['audit']['usage_settled'])
        state = self.ledger.snapshot()
        self.assertIsNone(state['pending'])
        self.assertEqual(state['attempts'], 1)
        self.assertEqual(Decimal(state['reserved_cny']), Decimal('0.001000000001'))

    def test_wrong_provider_model_never_releases(self):
        payload = {'model': 'deepseek-flash', 'messages': [{'role': 'user', 'content': 'synthetic'}],
                   'tools': [], 'max_tokens': OUTPUT_BOUND,
                   'thinking': {'type': 'disabled'}, 'stream': False}
        def send(_request):
            return TransportResponse(200, json.dumps({
                'model': 'different-model', 'choices': [{'finish_reason': 'stop',
                    'message': {'role': 'assistant', 'content': 'synthetic only'}}],
                'usage': self.usage()}).encode())
        result = model.wire.complete(payload, 'SYNTHETIC-ONLY', self.ledger,
                                     transport=send, require_existing_ledger=True)
        self.assertEqual(result['audit']['status'], 'MODEL_ID_MISMATCH')
        state = self.ledger.snapshot()
        self.assertTrue(state['halted'])
        self.assertIsNotNone(state['pending'])

    def test_thread_competition_allows_one_unsettled_request(self):
        results = []
        def reserve():
            try:
                self.ledger.reserve_worst(True)
                results.append('reserved')
            except ValueError:
                results.append('blocked')
        threads = [threading.Thread(target=reserve) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count('reserved'), 1)
        self.assertEqual(self.ledger.snapshot()['attempts'], 1)

    def test_one_shot_four_slot_runner_with_mock_http_only(self):
        session = Path(self.folder.name) / 'one-shot'
        fixture = model.RuleMockTransport()
        calls = []
        def mock_http(request):
            calls.append(request)
            return fixture(request)
        with (patch.object(batch, 'SESSION', session),
              patch.object(batch, 'source_check'),
              patch.object(batch, 'read_key', return_value='SYNTHETIC-ONLY'),
              patch('live_transport._urllib_transport', side_effect=mock_http)):
            result = batch.run(datetime.now(timezone.utc).isoformat())
            self.assertFalse(result['partial'])
            self.assertEqual(result['ledger']['attempts'], 8)
            self.assertEqual(len(calls), 8)
            self.assertEqual(result['solver_calls'], 0)
            with self.assertRaises(ValueError):
                batch.run(datetime.now(timezone.utc).isoformat())
            self.assertEqual(len(calls), 8)

    def test_one_shot_runner_reports_partial_when_next_worst_cost_will_not_fit(self):
        session = Path(self.folder.name) / 'partial'
        fixture = model.RuleMockTransport()
        calls = []
        def mock_http(request):
            calls.append(request)
            envelope = json.loads(fixture(request).body)
            envelope['usage'] = self.usage(450000, 100)
            return TransportResponse(200, json.dumps(envelope).encode())
        with (patch.object(batch, 'SESSION', session),
              patch.object(batch, 'source_check'),
              patch.object(batch, 'read_key', return_value='SYNTHETIC-ONLY'),
              patch('live_transport._urllib_transport', side_effect=mock_http)):
            result = batch.run(datetime.now(timezone.utc).isoformat())
        self.assertTrue(result['partial'])
        self.assertEqual(result['ledger']['attempts'], 1)
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(Decimal(result['ledger']['reserved_cny']), Decimal('3'))

    @unittest.skipUnless(os.name == 'posix', 'Real POSIX flock requires Linux')
    def test_process_competition_uses_one_atomic_reservation(self):
        context = multiprocessing.get_context('fork')
        ready, queue = context.Event(), context.Queue()
        workers = [context.Process(target=compete,
                    args=(self.path, self.auth, self.cny, ready, queue)) for _ in range(8)]
        for worker in workers:
            worker.start()
        ready.set()
        results = [queue.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(results.count('reserved'), 1)
        self.assertEqual(self.ledger.snapshot()['attempts'], 1)

    @unittest.skipUnless(os.name == 'posix', 'Real POSIX flock requires Linux')
    def test_process_competition_settles_only_once(self):
        reservation = self.ledger.reserve_worst(True)
        context = multiprocessing.get_context('fork')
        ready, queue = context.Event(), context.Queue()
        workers = [context.Process(target=compete_settle,
            args=(self.path, self.auth, self.cny, reservation['pending']['id'],
                  ready, queue)) for _ in range(8)]
        for worker in workers:
            worker.start()
        ready.set()
        results = [queue.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(results.count('settled'), 1)
        self.assertEqual(Decimal(self.ledger.snapshot()['reserved_cny']),
                         Decimal('0.001000000001'))


if __name__ == '__main__':
    unittest.main()
