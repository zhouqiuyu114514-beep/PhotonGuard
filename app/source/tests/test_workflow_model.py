"""No sockets, real credentials or paid ledgers; exercise actual protocol adapter."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from photonguard import workflow as wf
from photonguard import workflow_intake as intake
from photonguard import workflow_model as model
from photonguard.backend import TransportResponse


def envelope(message, finish='stop', **extras):
    value = {'model': 'deepseek-flash', 'choices': [{'finish_reason': finish, 'message': message}],
             'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}, **extras}
    return TransportResponse(200, json.dumps(value).encode())


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.view = intake.prepare('case-test', intake.DEMO)['view']
        for target in ('socket.socket.connect', 'socket.create_connection', 'subprocess.Popen',
                       'live_transport._urllib_transport'):
            p = patch(target, side_effect=AssertionError('No real network/process permitted'))
            p.start(); self.addCleanup(p.stop)

    def test_a0_and_a1_use_shared_transport_and_tools(self):
        from semantic_protocol import TOOLS
        for arm in ('A0', 'A1'):
            calls = []
            delegate = model.RuleMockTransport()
            def transport(request): calls.append(json.loads(request.body)); return delegate(request)
            a = model.DeepSeekSemanticAdapter(mock_transport=transport)
            result = a.run(self.view, mode='adapter_mock', arm=arm)
            self.assertEqual(result['status'], 'FINAL_RETURNED')
            self.assertEqual(len(calls), 2); self.assertEqual(result['tool_calls'], 1)
            self.assertEqual(calls[0]['tools'], TOOLS)
            self.assertEqual(calls[1]['tool_choice'], 'none')
            self.assertTrue(any(x['role'] == 'tool' for x in calls[1]['messages']))
            self.assertEqual(result['actual_model_calls'], 0)
            self.assertTrue(all(not x['live_dispatch'] for x in result['audits']))

    def test_live_gate_precedes_secret_supplier_and_transport(self):
        supplier = Mock(side_effect=AssertionError('Must not read a key'))
        a = model.DeepSeekSemanticAdapter(key_supplier=supplier)
        with self.assertRaises(model.ModelGateError): a.run(self.view, mode='live')
        supplier.assert_not_called()

    def test_stale_binding_cannot_read_key_or_reuse_old_authorization(self):
        for reference, input_hash in [('old-twenty-yuan', self.view['input_sha256']), ('semantic-small-gui-new', '0' * 64)]:
            b = model.ApprovedBinding(reference, 'case-test', input_hash, 'A1', approved=True)
            supplier = Mock(side_effect=AssertionError('no key'))
            a = model.DeepSeekSemanticAdapter(binding=b, key_supplier=supplier)
            with self.assertRaises(model.ModelGateError): a.run(self.view, mode='live')
            supplier.assert_not_called()

    def test_http_failure_has_no_retry_and_keeps_reservation(self):
        transport = Mock(return_value=TransportResponse(503, b'raw body must not escape'))
        ledger = model.MockLedger()
        r = model.DeepSeekSemanticAdapter(mock_transport=transport, mock_ledger=ledger).run(self.view, mode='adapter_mock')
        self.assertEqual(r['status'], 'HTTP_FAILURE'); self.assertEqual(transport.call_count, 1)
        self.assertEqual(ledger.calls, 1); self.assertNotIn('raw body', json.dumps(r))

    def test_timeout_does_not_leak_exception(self):
        t = Mock(side_effect=TimeoutError('SYNTHETIC_INTERNAL_DETAIL'))
        r = model.DeepSeekSemanticAdapter(mock_transport=t).run(self.view, mode='adapter_mock')
        self.assertEqual(r['status'], 'TRANSPORT_FAILURE')
        self.assertNotIn('SYNTHETIC_INTERNAL_DETAIL', json.dumps(r))

    def test_request_and_cny_caps_stop_before_transport(self):
        for ledger in (model.MockLedger(max_calls=0), model.MockLedger(cap_cny='0.01')):
            t = Mock(side_effect=AssertionError('No dispatch past cap'))
            r = model.DeepSeekSemanticAdapter(mock_transport=t, mock_ledger=ledger).run(self.view, mode='adapter_mock')
            self.assertEqual(r['status'], 'PREFLIGHT_OR_BUDGET_STOP'); t.assert_not_called()

    def test_concurrent_adapter_requests_share_budget(self):
        ledger = model.MockLedger(max_calls=2)
        a = model.DeepSeekSemanticAdapter(mock_transport=model.RuleMockTransport(), mock_ledger=ledger)
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: a.run(self.view, mode='adapter_mock')['status'], range(4)))
        self.assertEqual(results.count('FINAL_RETURNED'), 1)
        self.assertEqual(ledger.calls, 2)

    def test_secret_content_and_unknown_envelope_omitted(self):
        secret = 'sk-SYNTHETIC_REPLY_ONLY_987654'
        t = Mock(return_value=envelope({'role': 'assistant', 'content': secret}, secret=secret))
        r = model.DeepSeekSemanticAdapter(mock_transport=t).run(self.view, mode='adapter_mock')
        self.assertEqual(r['status'], 'SAFETY_STOP'); self.assertNotIn(secret, json.dumps(r))
        t = Mock(return_value=envelope({'role': 'assistant', 'content': '{}'}, secret=secret))
        r = model.DeepSeekSemanticAdapter(mock_transport=t).run(self.view, mode='adapter_mock')
        self.assertNotIn(secret, json.dumps(r))

    def test_bad_usage_and_wrong_model_stop(self):
        for extra, expected in [({'usage': None}, 'USAGE_OR_BUDGET_STOP'), ({'model': 'unapproved-model'}, 'MODEL_ID_MISMATCH')]:
            t = Mock(return_value=envelope({'role': 'assistant', 'content': '{}'}, **extra))
            r = model.DeepSeekSemanticAdapter(mock_transport=t).run(self.view, mode='adapter_mock')
            self.assertEqual(r['status'], expected)

    def test_unknown_tool_cannot_read_files_and_max_tool_calls(self):
        tool = model.PublicTools(self.view)
        for name, args in [('read_public_material', {'name': '../../.env'}), ('run_solver', {}), ('approve_task', {}),
                           ('export_visible_input', {'case_id': 'another-case'})]:
            self.assertEqual(tool.invoke({'function': {'name': name, 'arguments': json.dumps(args)}})['status'], 'REJECTED')
        for _ in range(5): result = tool.invoke({'function': {'name': 'export_visible_input', 'arguments': '{}'}})
        self.assertEqual(result['status'], 'BUDGET_STOP')

    def test_exact_candidate_tool_numeric_lexemes(self):
        c = intake.rule_candidate(self.view)
        c['fields']['film_thickness']['value'] = 'EXACT'
        raw = json.dumps({'candidate': c}).replace('"EXACT"', '300.12345678901234567890123456789')
        r = model.PublicTools(self.view).invoke({'function': {'name': 'review_public_candidate', 'arguments': raw}})
        self.assertEqual(r['normalized_response']['fields']['film_thickness']['value'], '300.12345678901234567890123456789')

    def test_model_failure_removes_prior_draft_without_raw_leak(self):
        saved = intake.prepare('case-test', intake.DEMO)
        saved['result'] = intake.review(saved, 'mock')
        t = Mock(return_value=TransportResponse(500, b'secret provider detail'))
        r = model.DeepSeekSemanticAdapter(mock_transport=t).run(self.view, mode='adapter_mock')
        saved = intake.model_result(saved, r)
        self.assertEqual(saved['status'], 'FAILED'); self.assertIsNone(saved['result'])
        self.assertNotIn('secret provider detail', json.dumps(saved))


class StoreAdapterTests(unittest.TestCase):
    def test_unexpected_supplier_error_is_recorded_without_secret_or_replay(self):
        secret = 'DEV-SYNTHETIC-SUPPLIER-SECRET'
        adapter = Mock()
        adapter.status.return_value = {'live_enabled': True}
        adapter.run.side_effect = RuntimeError(secret)
        with tempfile.TemporaryDirectory() as d:
            store = wf.WorkflowStore(Path(d) / 'store', allow_workers=False, model_adapter=adapter)
            try:
                state = store.create('own')
                state = store.action(state['id'], {'type': 'intake-save',
                    'expected_revision': state['revision'], 'text': intake.DEMO})
                state = store.action(state['id'], {'type': 'intake-review', 'mode': 'live',
                    'expected_revision': state['revision'], 'arm': 'A1'})
                self.assertEqual(state['intake']['status'], 'FAILED')
                self.assertIsNone(state['intake']['result'])
                self.assertEqual(adapter.run.call_count, 1)
                saved = (Path(d) / 'store' / state['id'])
                self.assertNotIn(secret, ''.join(p.read_text(encoding='utf-8')
                    for p in saved.glob('*.json')))
                with self.assertRaises(wf.WorkflowError):
                    store.action(state['id'], {'type': 'intake-review', 'mode': 'live',
                        'expected_revision': state['revision'] - 1, 'arm': 'A1'})
                self.assertEqual(adapter.run.call_count, 1)
            finally:
                store.close()

    def test_frontend_action_to_tool_continuation_and_manual_handoff(self):
        with tempfile.TemporaryDirectory() as d:
            store = wf.WorkflowStore(Path(d) / 'store', allow_workers=False)
            try:
                state = store.create('own')
                def action(kind, **kwargs):
                    nonlocal state
                    state = store.action(state['id'], dict(type=kind, expected_revision=state['revision'], **kwargs))
                with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')):
                    action('intake-save', text=intake.DEMO)
                    old_revision = state['revision']
                    action('intake-review', mode='adapter_mock', arm='A1')
                    self.assertEqual(state['intake']['adapter_audit']['tool_calls'], 1)
                    self.assertEqual(state['intake']['result']['mode'], 'MODEL_ADAPTER_MOCK_TRANSPORT')
                    with self.assertRaises(wf.WorkflowError): store.action(state['id'], {'type': 'intake-review', 'mode': 'adapter_mock', 'expected_revision': old_revision})
                    action('intake-confirm', approve=True, result_sha256=state['intake']['result_sha256'])
                    handoff = intake.mapping_handoff(state['intake'])
                    self.assertTrue(all(v is None for v in handoff['decisions_to_document'].values()))
                    self.assertFalse(handoff['task_lock_created'])
                    self.assertEqual(state['task']['units_um'], None)
            finally: store.close()

    def test_interrupted_running_record_does_not_redispatch(self):
        with tempfile.TemporaryDirectory() as d:
            store = wf.WorkflowStore(Path(d) / 'store', allow_workers=False)
            try:
                s = store.create('own'); raw = store._load(s['id'])
                raw['intake'] = intake.prepare(s['id'], intake.DEMO); raw['intake']['status'] = 'MODEL_RUNNING'
                store._save(raw)
                with patch.object(store.model_adapter, 'run', side_effect=AssertionError('No replay')):
                    with self.assertRaises(wf.WorkflowError): store.action(s['id'], {'type': 'intake-review', 'mode': 'adapter_mock', 'expected_revision': raw['revision']})
            finally: store.close()


if __name__ == '__main__': unittest.main()
