"""Constructed DEV fixtures only; no P01-P06 answers or coordinator assets."""
import copy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import semantic_intake as adapter


class PublicAdapterTests(unittest.TestCase):
    def setUp(self):
        self.view = {'semantic_contract': adapter.read(adapter.PUBLIC / 'semantic_contract.json'),
            'packet': {'schema_version': 1, 'case_id': 'DEV-CONSTRUCTED', 'synthetic': True,
                'request_zh': '仅用于接口结构的开发素材，非正式题目。',
                'documents': [{'id': 'DEV1', 'title': '开发素材', 'lines': ['构造接口测试数据。']},
                              {'id': 'DEV2', 'title': '开发素材二', 'lines': ['第二条构造接口数据。']}]},
            'clarification_documents': []}
        self.hash = adapter.digest(self.view)
        self.view['input_sha256'] = self.hash
        values = ['1D', 0, '1', True, True, True, 1, '1', '2.35', '1', 200, 650, 1100, 41]
        units = [None, 'deg', None, None, None, None, None, None, None, None, 'nm', 'nm', 'nm', None]
        self.response = {'case_id': 'DEV-CONSTRUCTED', 'input_sha256': self.hash,
            'review_status': 'REVIEW_REQUIRED', 'fields': {}, 'questions': [], 'conflicts': [],
            'refusal': {'reason_codes': [], 'text': None}}
        for k, v, u in zip(adapter.KEYS, values, units):
            self.response['fields'][k] = {'status': 'proposed', 'value': v, 'unit': u,
                'evidence': [{'document': 'DEV1', 'line': 1, 'quote': '构造接口测试数据。'}]}

    def receipt(self, response=None): return adapter.receipt(self.view, response or self.response, self.hash)

    def test_public_fields_accepted_but_task_bridge_is_blocked(self):
        result = self.receipt()
        self.assertEqual(set(result['normalized_response']['fields']), set(adapter.KEYS))
        self.assertEqual(result['normalized_response']['fields']['layer_count']['value'], 1)
        projection = result['implementation_projection']
        self.assertEqual(next(f for f in projection['fields'] if f['implementation_key'] == 'units_um')['value'], None)
        self.assertEqual(next(f for f in projection['fields'] if f['implementation_key'] == 'physics.dispersive')['value'], False)
        self.assertIn('UNIFORM_WAVELENGTH_IS_NOT_NATIVE_UNIFORM_FREQUENCY', projection['blocked'])
        self.assertFalse(projection['task_approved'])
        self.assertFalse(result['semantic_entailment_verified'])

    def test_unresolved_bool_never_negated_into_known_value(self):
        f = self.response['fields']['nondispersive']
        f.update(status='unknown', value=None, unit=None)
        self.response['review_status'] = 'CLARIFICATION_REQUIRED'
        self.response['questions'] = [{'targets': ['nondispersive'], 'text': '请补充色散要求。'}]
        f = next(f for f in self.receipt()['implementation_projection']['fields'] if f['implementation_key'] == 'physics.dispersive')
        self.assertEqual(f['status'], 'unknown')
        self.assertIsNone(f['value'])

    def test_grouped_questions_conflicts_and_nulls_preserved(self):
        for key in ['film_index', 'film_thickness']:
            self.response['fields'][key].update(status='unknown', value=None, unit=None)
        field = self.response['fields']['wavelength_max']
        field.update(status='conflict', value=None, unit=None)
        field['evidence'].append({'document': 'DEV2', 'line': 1, 'quote': '第二条构造接口数据。'})
        self.response.update(review_status='CLARIFICATION_REQUIRED', conflicts=['wavelength_max'],
            questions=[{'targets': ['film_index', 'film_thickness'], 'text': '请补充这两个缺项。'},
                       {'targets': ['wavelength_max'], 'text': '请确认资料优先级。'}])
        result = self.receipt()['normalized_response']
        self.assertEqual(result['questions'], self.response['questions'])
        self.assertIsNone(result['fields']['wavelength_max']['value'])

    def test_exact_conversion_without_decimal_context_rounding(self):
        value = '0.' + '1234567890' * 9
        with localcontext() as context:
            context.prec = 6
            self.response['fields']['film_thickness'].update(value=value, unit='µm')
            result = self.receipt()['normalized_response']['fields']['film_thickness']
        n = Decimal(value)
        expected = Decimal((n.as_tuple().sign, n.as_tuple().digits, n.as_tuple().exponent+3))
        self.assertEqual(Decimal(result['value']), expected)
        self.assertEqual(result['unit'], 'nm')

    def test_length_units_and_angle_aliases(self):
        for unit in ('nm', 'um', 'µm', 'μm', 'm'):
            with self.subTest(unit=unit):
                self.response['fields']['film_thickness'].update(value='1', unit=unit)
                self.assertEqual(self.receipt()['normalized_response']['fields']['film_thickness']['value'], adapter.shift('1', adapter.LENGTH[unit]))
        self.response['fields']['incidence_angle']['unit'] = '°'
        self.assertEqual(self.receipt()['normalized_response']['fields']['incidence_angle']['unit'], 'deg')

    def test_decimal_boundary_and_numeric_bool_reject(self):
        for value in (True, '1e1001', '1e-1001', '9'*129, 'NaN', {}, [], '1/2'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): adapter.number(value)
        self.assertEqual(Decimal(adapter.shift('1e-1000')), Decimal('1e-1000'))

    def test_unit_conversion_at_exponent_bound_remains_publicly_representable(self):
        self.response['fields']['film_thickness'].update(value='1e1000', unit='m')
        field = self.receipt()['normalized_response']['fields']['film_thickness']
        self.assertEqual(field['unit'], 'm')
        self.assertEqual(adapter.number(field['value']), Decimal('1e1000'))
        self.response['fields']['film_thickness'].update(value='1e-1000', unit='um')
        field = self.receipt()['normalized_response']['fields']['film_thickness']
        self.assertEqual(field['unit'], 'nm')
        self.assertEqual(adapter.number(field['value']), Decimal('1e-997'))

    def test_closed_schema_and_non_string_states(self):
        for target in ('root', 'field', 'reference', 'state', 'review'):
            with self.subTest(target=target):
                r = copy.deepcopy(self.response)
                if target == 'root': r['approved'] = True
                if target == 'field': r['fields']['film_index']['task_lock'] = {}
                if target == 'reference': r['fields']['film_index']['evidence'][0]['document_id'] = 'DEV1'
                if target == 'state': r['fields']['film_index']['status'] = {}
                if target == 'review': r['review_status'] = []
                with self.assertRaises(ValueError): self.receipt(r)

    def test_stale_hash_unreleased_doc_forged_quote_and_boolean_line(self):
        for mode in ('hash', 'doc', 'quote', 'line'):
            with self.subTest(mode=mode):
                r = copy.deepcopy(self.response)
                ref = r['fields']['film_index']['evidence'][0]
                if mode == 'hash': r['input_sha256'] = '0'*64
                if mode == 'doc': ref['document'] = 'UNRELEASED'
                if mode == 'quote': ref['quote'] = 'invented'
                if mode == 'line': ref['line'] = True
                with self.assertRaises(ValueError): self.receipt(r)

    def test_trusted_hash_required_independently_of_self_declared_view(self):
        altered = copy.deepcopy(self.view)
        altered['clarification_documents'] = [{'id': 'UNAPPROVED', 'title': 'not released', 'lines': ['数据']}]
        altered['input_sha256'] = adapter.digest({k:v for k,v in altered.items() if k != 'input_sha256'})
        with self.assertRaises(ValueError): adapter.validate_view(altered, self.hash)
        adapter.validate_view(altered, altered['input_sha256'])  # Only coordinator may release this new trusted hash.

    def test_out_of_scope_preserves_known_fields_and_refusal(self):
        self.response.update(review_status='OUT_OF_SCOPE', refusal={'reason_codes': ['oblique_incidence'], 'text': '明确角度超出范围。'})
        self.response['fields']['incidence_angle']['value'] = 15
        result = self.receipt()['normalized_response']
        self.assertEqual(result['fields']['incidence_angle']['value'], '15')
        self.assertEqual(result['fields']['film_index']['status'], 'proposed')

    def test_old_response_shape_and_bad_conflict_declarations_reject(self):
        with self.assertRaises(ValueError): self.receipt({'schema_version': 1, 'fields': []})
        self.response['conflicts'] = ['film_index']
        with self.assertRaises(ValueError): self.receipt()

    def test_parser_duplicate_nonfinite_surrogate_and_decimal_numbers(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'candidate.json'
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":"\\ud800"}', b'{"x":1e1001}'):
                with self.subTest(raw=raw):
                    p.write_bytes(raw)
                    with self.assertRaises((ValueError, UnicodeError)): adapter.read(p, decimal_numbers=True)
            p.write_bytes(b'{"x":0.12345678901234567890123456789}')
            self.assertEqual(adapter.read(p, decimal_numbers=True)['x'], Decimal('0.12345678901234567890123456789'))

    def test_no_network_or_solver_and_no_input_mutation(self):
        before = copy.deepcopy(self.view)
        response = copy.deepcopy(self.response)
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('no network')):
            result = self.receipt()
        self.assertEqual(self.view, before)
        self.assertEqual(self.response, response)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['solver_calls'], 0)


if __name__ == '__main__': unittest.main()
