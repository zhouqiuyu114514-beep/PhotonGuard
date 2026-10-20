"""Adversarial offline response retention and complete-denominator accounting."""
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from photonguard.intake_response import parse_response, ResponseRejected
from photonguard import workflow_intake as intake, workflow_model as model, workflow as wf
from photonguard.comparison_report import summarize


class ResponseEvidenceTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('No network'))
        network.start(); self.addCleanup(network.stop)
        worker = patch('subprocess.Popen', side_effect=AssertionError('No solver or credential command'))
        worker.start(); self.addCleanup(worker.stop)
        self.view = intake.prepare('offline-security-v3', intake.DEMO)['view']

    def rejected(self, text, code):
        with self.assertRaises(ResponseRejected) as context:
            parse_response(text)
        error = context.exception
        self.assertEqual(error.reason_code, code)
        return error.evidence

    def test_invalid_syntax_omits_body_and_exception_snippet(self):
        marker = 'SYNTHETIC_MALFORMED_PRIVATE_ONLY'
        e = self.rejected('```json\n{"x":' + marker, 'INVALID_JSON')
        self.assertTrue(e['code_fence_present'])
        self.assertIsNone(e['body']); self.assertNotIn(marker, json.dumps(e))
        self.assertEqual(e['original_bytes'], 45)

    def test_duplicate_key_omits_names_and_values(self):
        raw = '{"SYNTHETIC_PRIVATE_KEY": 1, "SYNTHETIC_PRIVATE_KEY": 2}'
        e = self.rejected(raw, 'DUPLICATE_JSON_KEY')
        self.assertIsNone(e['body']); self.assertNotIn('SYNTHETIC_PRIVATE_KEY', json.dumps(e))

    def test_nonfinite_depth_size_and_unicode_are_controlled(self):
        for raw, code in [('NaN', 'NONFINITE_JSON_NUMBER'),
                          ('[' * 40 + '0' + ']' * 40, 'JSON_DEPTH_LIMIT'),
                          (' ' * 131073 + '{}', 'RESPONSE_TOO_LARGE'),
                          ('{"x":"\\ud800"}', 'INVALID_UNICODE'),
                          (None, 'RESPONSE_TYPE'), (' ', 'EMPTY_RESPONSE')]:
            with self.subTest(code=code):
                self.assertIsNone(self.rejected(raw, code)['body'])

    def test_credentials_in_json_property_name_quarantine_mapping(self):
        sentinel = 'sk-SYNTHETIC_KEY_NAME_123456'
        e = self.rejected(json.dumps({sentinel: 'safe'}), 'REDACTION_CHECK_REJECTED')
        self.assertNotIn(sentinel, json.dumps(e))
        self.assertEqual(e['body'], {'_redacted_mapping': '[REDACTED]'})

    def test_unicode_escaped_key_and_inner_json_secret_never_persist(self):
        sentinel = 'sk-SYNTHETIC_INNER_12345678'
        for raw in ['{"\\u0073\\u006b-SYNTHETIC_INNER_12345678": 1}',
                    json.dumps({'note': json.dumps({'secret': sentinel})}),
                    json.dumps({'note': r'\u0070assword=SYNTHETIC_ASSIGNMENT_ONLY'})]:
            with self.subTest(raw=raw):
                e = self.rejected(raw, 'REDACTION_CHECK_REJECTED')
                saved = json.dumps(e)
                self.assertNotIn('SYNTHETIC_INNER', saved)
                self.assertNotIn('SYNTHETIC_ASSIGNMENT', saved)

    def test_plain_assignment_inside_json_string_is_redacted(self):
        e = self.rejected(json.dumps({'note': '密钥=SYNTHETIC_ASSIGNMENT_ONLY'}), 'REDACTION_CHECK_REJECTED')
        self.assertEqual(e['body']['note'], '[REDACTED]')

    def test_valid_decimal_candidate_keeps_exact_value(self):
        candidate = intake.rule_candidate(self.view)
        candidate['fields']['film_thickness']['value'] = 'PRECISE_MARKER'
        raw = json.dumps(candidate).replace('"PRECISE_MARKER"', '300.12345678901234567890123456789')
        parsed, e = parse_response(raw)
        self.assertEqual(parsed['fields']['film_thickness']['value'], '300.12345678901234567890123456789')
        self.assertFalse(e['body_is_original_response'])
        self.assertEqual(e['body_storage'], 'SANITIZED_PARSED_JSON')

    def response(self, raw):
        return {'status': 'FINAL_RETURNED', 'raw_final': raw, 'actual_model_calls': 0,
                'audits': [], 'submissions': [], 'mode': 'ADAPTER_MOCK_NOT_AI',
                'solver_calls': 0, 'tool_calls': 0}

    def test_invalid_decision_types_create_rejection_evidence(self):
        for decision in ({}, []):
            c = intake.rule_candidate(self.view); c['decision'] = decision
            result = intake.model_result({'view': self.view}, self.response(json.dumps(c)))
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['rejection_code'], 'SEMANTIC_CONTRACT_REJECTED')
            self.assertEqual(result['response_evidence']['body']['decision'], decision)
            self.assertIsNone(result['result'])

    def test_wrong_evidence_quote_is_semantic_rejection_not_syntax(self):
        c = intake.rule_candidate(self.view)
        c['fields']['film_index']['evidence'][0]['quote'] = 'SYNTHETIC_UNSUPPORTED_QUOTE'
        r = intake.model_result({'view': self.view}, self.response(json.dumps(c)))
        self.assertEqual(r['rejection_code'], 'SEMANTIC_CITATION_INVALID')
        self.assertEqual(r['response_evidence']['body_storage'], 'SANITIZED_PARSED_JSON')

    def test_persisted_failure_does_not_leak_and_next_mock_clears_stale_evidence(self):
        sentinel = 'sk-SYNTHETIC_PERSISTENCE_12345678'
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        temp = temp_dir.name
        store = wf.WorkflowStore(Path(temp), allow_workers=False)
        self.addCleanup(store.close)
        case = store.create('own')
        def action(kind, **kw):
            nonlocal case
            case = store.action(case['id'], dict(type=kind, expected_revision=case['revision'], **kw))
            return case['intake']
        action('intake-save', text=intake.DEMO)
        result = action('intake-review', mode='offline', response_text=json.dumps({'api_key': sentinel}))
        self.assertEqual(result['rejection_code'], 'REDACTION_CHECK_REJECTED')
        for p in Path(temp).rglob('*.json'):
            self.assertNotIn(sentinel, p.read_text(encoding='utf-8'))
        next_result = action('intake-review', mode='mock')
        self.assertNotIn('response_evidence', next_result)
        self.assertNotIn('rejection_code', next_result)

    def test_both_adapter_arms_keep_safe_evidence_and_no_native_authority(self):
        for arm in ('A0', 'A1'):
            response = model.DeepSeekSemanticAdapter(mock_transport=model.RuleMockTransport()).run(self.view, mode='adapter_mock', arm=arm)
            r = intake.model_result({'view': self.view}, response)
            self.assertEqual(r['status'], 'REVIEW')
            self.assertEqual(r['response_evidence']['reason_code'], 'REVIEW_REQUIRED')
            self.assertFalse(r['result']['task_approved'])
            self.assertEqual(r['model_calls'], 0)
            self.assertEqual(len(r['adapter_audit']['submissions']), 2)
            for submission in r['adapter_audit']['submissions']:
                self.assertEqual(submission['response_evidence']['body_storage'], 'SANITIZED_PARSED_JSON')

    def test_changed_source_cannot_reuse_old_paid_batch_binding(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('offline_v3_paid_guard',
            Path(__file__).resolve().parents[1] / 'tools/run_gui_live_comparison.py')
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with patch.object(entry, 'read_key', side_effect=AssertionError('Must not read key')) as key:
            with self.assertRaisesRegex(ValueError, 'Validated source mismatch'):
                entry.run(None)
            key.assert_not_called()


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.plan = [{'slot': i + 1, 'case': case, 'arm': arm} for i, (case, arm) in enumerate(
            (('complete', 'A0'), ('complete', 'A1'), ('conflict', 'A0'), ('conflict', 'A1')))]

    def records(self):
        return [dict(self.plan[i], status='FINAL_RETURNED', review_status=status,
                     adapter_audit={'audits': [{'live_dispatch': True}] * 2})
                for i, status in enumerate(('REVIEW', 'FAILED'))]

    def test_rejected_return_counts_and_unrun_tasks_remain_in_denominator(self):
        r = summarize(self.plan, self.records())
        self.assertEqual((r['planned_tasks'], r['returned_final_candidates'], r['rejected_tasks'], r['not_run_tasks'], r['provider_requests']), (4, 2, 1, 2, 4))
        self.assertEqual(r['tasks'][1]['rejection_code'], 'LEGACY_UNSPECIFIED')
        self.assertFalse(r['semantic_correctness_scored'])

    def test_duplicate_or_mismatched_receipts_cannot_improve_counts(self):
        records = self.records()
        for wrong in (records + [records[0]], [dict(records[0], arm='A1')], [dict(records[0], slot=99)]):
            with self.assertRaises(ValueError): summarize(self.plan, wrong)

    def test_transport_stop_does_not_count_as_final_candidate(self):
        records = self.records(); records[1]['status'] = 'HTTP_FAILURE'
        r = summarize(self.plan, records)
        self.assertEqual(r['stopped_tasks'], 1)
        self.assertEqual(r['returned_final_candidates'], 1)


if __name__ == '__main__':
    unittest.main()
