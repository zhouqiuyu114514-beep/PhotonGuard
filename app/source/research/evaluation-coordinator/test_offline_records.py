"""Coordinator DEV tests only; no P01-P06 labels, model output or human timing."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import offline_records as records
from test_semantic_scalar_roundtrip import dev_view_candidate


class RecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        path = Path(os.environ['PG_DEV_EVALUATOR'])
        spec = importlib.util.spec_from_file_location('frozen_dev_evaluator', path)
        cls.ev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.ev)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.view, self.candidate = dev_view_candidate('1e128')
        self.case = self.view['packet']['case_id']
        self.fixture = self.root / 'fixture'
        (self.fixture/'inputs/cases').mkdir(parents=True)
        (self.fixture/'coordinator').mkdir()
        def write(p, value): p.write_text(json.dumps(value), encoding='utf-8')
        write(self.fixture/'inputs/semantic_contract.json', self.view['semantic_contract'])
        write(self.fixture/('inputs/cases/'+self.case+'.json'), self.view['packet'])
        fields = {k: {'status': v['status'], 'value': v['value'], 'unit': v['unit'],
                      'accepted_evidence': v['evidence']} for k, v in self.candidate['fields'].items()}
        label = {'clarifications': [], 'refusal_reasons': [], 'initial': {'fields': fields}, 'resolved': {'fields': fields}}
        write(self.fixture/'coordinator/labels.json', {'cases': {self.case: label}})
        self.attempts = self.root/'attempts'

    def record(self, identifier, raw, **kwargs):
        return records.record_attempt(self.attempts, attempt_id=identifier, arm=kwargs.pop('arm', 'A1'),
            stage=kwargs.pop('stage', 'raw_initial'), view=self.view, trusted_hash=self.view['input_sha256'],
            raw=raw, evaluator=self.ev, evaluator_root=self.fixture,
            candidate_content_attested=True, **kwargs)

    def test_rejected_candidate_keeps_original_score_and_partial_fields(self):
        c = copy.deepcopy(self.candidate)
        c['fields']['film_index']['evidence'] = []
        raw = json.dumps(c).encode()
        path = self.record('no-citation', raw)
        self.assertEqual((path/'raw-candidate.bin').read_bytes(), raw)
        self.assertEqual(json.loads((path/'tool-receipt.json').read_text())['status'], 'REJECTED')
        score = json.loads((path/'raw-score.json').read_text())
        self.assertEqual(score['fields']['film_index']['objective_outcome'], 'partial')
        self.assertEqual(records.summarize(self.attempts, [self.case])['arms']['A1']['attempt_denominator'], 1)

    def test_all_three_arms_count_malformed_and_rejected_returns(self):
        for arm in records.ARMS:
            good = json.dumps(self.candidate).encode()
            bad = dict(self.candidate, approved=True)
            for i, raw in enumerate((good, json.dumps(bad).encode(), b'{broken')):
                self.record(arm+str(i), raw, arm=arm)
        summary = records.summarize(self.attempts, [self.case, 'DEV-NOT-STARTED'])
        for arm in records.ARMS:
            value = summary['arms'][arm]
            self.assertEqual(value['planned_case_denominator'], 2)
            self.assertEqual(value['attempt_denominator'], 3)
            self.assertEqual(value['raw_outcomes']['OUTPUT_CONTRACT_FAILURE'], 2)
            self.assertEqual(value['tool_outcomes']['REJECTED'], 2)
            self.assertEqual(value['pending_cases'], ['DEV-NOT-STARTED'])
            self.assertIsNone(value['human_active_seconds'])

    def test_normalization_and_manual_correction_never_replace_raw_stage(self):
        raw = json.dumps(self.candidate).encode()
        path = self.record('first', raw)
        self.record('corrected', raw, stage='human_corrected')
        self.assertEqual((path/'raw-candidate.bin').read_bytes(), raw)
        self.assertTrue((path/'tool-normalized.json').exists())
        summary = records.summarize(self.attempts, [self.case])['arms']['A1']
        self.assertEqual(summary['attempt_denominator'], 1)
        self.assertEqual(summary['stages']['human_corrected'], 1)

    def test_stops_and_interrupted_processing_remain_in_denominator(self):
        self.record('budget', None, stop_reason='BUDGET_STOP')
        path = self.record('interrupted', b'{')
        (path/'result.json').unlink()
        value = records.summarize(self.attempts, [self.case])['arms']['A1']
        self.assertEqual(value['attempt_denominator'], 2)
        self.assertEqual(value['raw_outcomes'], {'BUDGET_STOP': 1, 'INCOMPLETE': 1})

    def test_secret_and_unicode_escaped_key_are_counted_without_raw_storage(self):
        for i, raw in enumerate((b'{"sk-fakecredential12345": 1}',
                                b'{"note":"\\u0073\\u006b-fakecredential12345"}')):
            path = self.record('secret'+str(i), raw)
            self.assertFalse((path/'raw-candidate.bin').exists())
            self.assertEqual(json.loads((path/'raw-score.json').read_text())['outcome'], 'SAFETY_STOP')
            self.assertNotIn('fakecredential', ''.join(p.read_text() for p in path.glob('*.json')))
        self.assertEqual(records.summarize(self.attempts, [self.case])['arms']['A1']['attempt_denominator'], 2)

    def test_real_observations_and_duplicate_attempts_cannot_enter_dev_records(self):
        with self.assertRaises(ValueError):
            self.record('real', b'{}', provenance='OBSERVED_MODEL')
        self.record('once', b'{}')
        with self.assertRaises(FileExistsError): self.record('once', b'{}')


if __name__ == '__main__': unittest.main(verbosity=2)
