"""Offline interface tests, not model quality or independent held-out answers."""
import copy
import json
import socket
import unittest
from unittest.mock import patch
import requirements_intake as intake


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.data = {'schema_version': 1, 'documents': [
            {'id': 'spec', 'kind': 'independent_spec', 'lines': ['膜层折射率为2.35。', '厚度200 nm。']},
            {'id': 'script', 'kind': 'ast_observation', 'lines': ['脚本使用n=1.45。']}]}
        self.response = {'schema_version': 1, 'input_sha256': intake.pilot.digest(self.data),
            'fields': [{'path': p, 'state': 'unknown', 'value': None, 'unit': None, 'evidence': []}
                       for p in intake.pilot.PATHS],
            'questions': [{'path': p, 'text': '请依据独立需求补充'+p+'的值与单位。'} for p in intake.pilot.PATHS]}

    def test_export_never_sends_or_supplies_answer_keys(self):
        original = copy.deepcopy(self.data)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network')):
            request = intake.prepare(self.data)
        self.assertEqual(self.data, original)
        self.assertEqual(request['documents'], original['documents'])
        self.assertEqual(request['model_calls'], 0)
        self.assertNotIn('facts', request)
        self.assertNotIn('expected', request)

    def test_unknowns_and_questions_remain_unapproved(self):
        result = intake.validate_response(self.data, self.response)
        self.assertEqual(result['status'], 'CLARIFICATION_REQUIRED')
        self.assertEqual(len(result['questions']), 14)
        self.assertFalse(result['task_approved'])
        self.assertFalse(result['task_lock_created'])

    def proposed(self):
        field = next(f for f in self.response['fields'] if f['path'] == 'layers.0.thickness_um')
        field.update(state='proposed', value=200, unit='nm', evidence=[{
            'document_id': 'spec', 'line': 2, 'quote': self.data['documents'][0]['lines'][1]}])
        self.response['questions'] = [q for q in self.response['questions'] if q['path'] != field['path']]
        return field

    def test_explicit_unit_conversion_and_line_ref(self):
        field = self.proposed()
        result = intake.validate_response(self.data, self.response)
        saved = next(f for f in result['fields'] if f['path'] == field['path'])
        self.assertEqual(saved['suggested_value'], '0.200')
        self.assertFalse(result['source_semantics_verified'])

    def test_stale_hash_and_fabricated_reference_reject(self):
        field = self.proposed()
        for alteration in ['stale', 'quote', 'line', 'script']:
            with self.subTest(alteration=alteration):
                r = copy.deepcopy(self.response)
                f = next(f for f in r['fields'] if f['path'] == field['path'])
                if alteration == 'stale': r['input_sha256'] = 'wrong'
                if alteration == 'quote': f['evidence'][0]['quote'] = 'fabricated'
                if alteration == 'line': f['evidence'][0]['line'] = True
                if alteration == 'script': f['evidence'][0].update(document_id='script', line=1, quote='脚本使用n=1.45。')
                with self.assertRaises(ValueError): intake.validate_response(self.data, r)

    def test_missing_unit_and_invalid_field_types_reject(self):
        field = self.proposed()
        for name, value in [('unit', None), ('value', True), ('value', float('nan')), ('state', {}), ('path', [])]:
            with self.subTest(name=name, value=value):
                r = copy.deepcopy(self.response)
                next(f for f in r['fields'] if f['path'] == field['path'])[name] = value
                with self.assertRaises(ValueError): intake.validate_response(self.data, r)

    def test_unknown_value_autoapproval_and_missing_question_reject(self):
        for alteration in ['value', 'approval', 'question', 'duplicate']:
            r = copy.deepcopy(self.response)
            if alteration == 'value': r['fields'][0]['value'] = 1
            if alteration == 'approval': r['task_approved'] = True
            if alteration == 'question': r['questions'].pop()
            if alteration == 'duplicate': r['fields'][-1] = r['fields'][0]
            with self.assertRaises(ValueError): intake.validate_response(self.data, r)


if __name__ == '__main__': unittest.main()
