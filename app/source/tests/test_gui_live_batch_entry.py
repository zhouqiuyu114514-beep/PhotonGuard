"""Offline-only checks for the one-shot authorized comparison entrypoint."""
from decimal import Decimal
from datetime import datetime, timezone
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from photonguard import workflow_intake as intake
from photonguard import workflow_model as model
from tools import run_gui_live_comparison as batch


class LiveBatchEntryTests(unittest.TestCase):
    def test_frozen_preflight_refuses_updated_source_before_key_or_network(self):
        with (patch.object(socket.socket, 'connect',
                           side_effect=AssertionError('network forbidden')),
              patch('getpass.getpass', side_effect=AssertionError('key forbidden'))):
            with self.assertRaisesRegex(ValueError, 'Validated source mismatch'):
                batch.preflight()
        self.assertFalse(batch.SESSION.exists())

    def test_single_worst_case_fits_but_two_unsettled_do_not(self):
        usd, cny = batch.reservation()
        self.assertEqual(usd, Decimal('0.3194880'))
        self.assertEqual(cny, Decimal('2.129920'))
        self.assertLess(cny, batch.CNY_CAP)
        self.assertGreater(cny * 2, batch.CNY_CAP)

    def test_four_synthetic_views_use_adapter_mock_only(self):
        with patch('live_transport._urllib_transport',
                   side_effect=AssertionError('provider network forbidden')):
            for _, view in batch.views():
                self.assertIs(view['packet']['synthetic'], True)
                intake.semantic.validate_view(view, view['input_sha256'],
                                              allow_user_material=True)
                for arm in ('A0', 'A1'):
                    answer = model.DeepSeekSemanticAdapter(
                        mock_transport=model.RuleMockTransport()).run(
                            view, mode='adapter_mock', arm=arm)
                    self.assertEqual(answer['status'], 'FINAL_RETURNED')
                    self.assertEqual(answer['actual_model_calls'], 0)
                    self.assertEqual(len(answer['audits']), 2)
                    self.assertEqual(intake.model_result({'view': view}, answer)['status'],
                                     'REVIEW')

    def test_old_live_run_is_closed_on_updated_source_before_key_or_session(self):
        with patch('getpass.getpass', side_effect=AssertionError('key forbidden')):
            with self.assertRaises(ValueError):
                batch.run('2026-10-06T10:00:00+00:00')
        self.assertFalse(batch.SESSION.exists())

    def test_unproven_cost_bound_blocks_before_session_key_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / 'must-not-exist'
            with (patch.object(batch, 'SOFTWARE_COST_BOUND_PROVEN', False),
                  patch.object(batch, 'SESSION', session),
                  patch.object(batch, 'source_check'),
                  patch.object(batch, 'checked_at', return_value='2026-10-06T10:00:00+00:00'),
                  patch('getpass.getpass', side_effect=AssertionError('key forbidden')),
                  patch.object(socket.socket, 'connect',
                               side_effect=AssertionError('network forbidden'))):
                with self.assertRaisesRegex(ValueError, 'prompt-token bound'):
                    batch.run('2026-10-06T10:00:00+00:00')
            self.assertFalse(session.exists())

    @unittest.skipUnless(os.name == 'posix', 'POSIX ledger integration requires Linux')
    def test_one_shot_runner_with_mock_provider_counts_eight_and_refuses_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder) / 'dev-batch'
            mock = model.RuleMockTransport()
            calls = []
            def send(request):
                calls.append(request)
                return mock(request)
            # Historical accounting fixture only; production source refusal is
            # tested separately above. All dispatches here use injected mock.
            with (patch.object(batch, 'SOFTWARE_COST_BOUND_PROVEN', True),
                  patch.object(batch, 'source_check'),
                  patch.object(batch, 'SESSION', session),
                  patch.object(batch, 'read_key', return_value='DEV-SYNTHETIC-ONLY'),
                  patch('live_transport._urllib_transport', side_effect=send)):
                summary = batch.run(datetime.now(timezone.utc).isoformat())
                self.assertEqual(len(summary['completed_slots']), 4)
                self.assertFalse(summary['partial'])
                self.assertEqual(summary['ledger']['attempts'], 8)
                self.assertEqual(summary['ledger']['live_provider_attempts'], 8)
                self.assertEqual(len(calls), 8)
                self.assertEqual(summary['solver_calls'], 0)
                with self.assertRaises(ValueError):
                    batch.run(datetime.now(timezone.utc).isoformat())
                self.assertEqual(len(calls), 8)


if __name__ == '__main__':
    unittest.main()
