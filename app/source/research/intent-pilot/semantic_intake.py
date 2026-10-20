"""Public-only offline semantic adapter. No scoring assets, API or task writes.

This is a distinct protocol, not a rename of the legacy fourteen paths.
Citation existence is checked; entailment and revision authority are not inferred.
"""
import argparse
import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

PUBLIC = Path(__file__).with_name('public-contract')
KEYS = ('spatial_dimension', 'incidence_angle', 'relative_permeability', 'lossless',
        'isotropic', 'nondispersive', 'layer_count', 'incident_index', 'film_index',
        'exit_index', 'film_thickness', 'wavelength_min', 'wavelength_max', 'wavelength_samples')
TYPES = ('enum', 'quantity', 'number', 'boolean', 'boolean', 'boolean', 'integer',
         'number', 'number', 'number', 'quantity', 'quantity', 'quantity', 'integer')
PATHS = ('physics.dimensions', 'physics.angle_deg', 'physics.mu', 'physics.lossless',
         'physics.isotropic', 'physics.dispersive', None, 'physics.n_incident',
         'layers.0.n', 'physics.n_exit', 'layers.0.thickness_um', 'wavelength_um.0',
         'wavelength_um.1', 'nfreq')
LENGTH = {'nm': 0, 'um': 3, 'µm': 3, 'μm': 3, 'm': 9}
STATES = ('proposed', 'unknown', 'conflict', 'unsupported')
REVIEWS = ('REVIEW_REQUIRED', 'CLARIFICATION_REQUIRED', 'OUT_OF_SCOPE')
REASONS = ('absorption', 'dispersion', 'magnetism', 'anisotropy', 'oblique_incidence',
           'multiple_layers', 'dimension', 'other')


def require(ok, message):
    if not ok: raise ValueError(message)


def exact(value, keys, context):
    require(type(value) is dict and set(value) == set(keys), context + ': closed keys required')


def bounded_list(value, maximum, context):
    require(type(value) is list and len(value) <= maximum, context + ': bounded list required')


def number(value):
    require(type(value) in (str, int, float, Decimal), 'finite decimal required; bool is not numeric')
    text = str(value)
    require(len(text) <= 256, 'decimal text bound')
    try: result = Decimal(text)
    except InvalidOperation: raise ValueError('invalid decimal') from None
    require(result.is_finite(), 'finite decimal required')
    _, digits, exponent = result.as_tuple()
    require(len(digits) <= 128 and abs(exponent) <= 1000, 'decimal coefficient/exponent bound')
    return result


def shift(value, power=0):
    # Tuple exponent adjustment is exact even beyond the Decimal context precision.
    sign, digits, exponent = number(value).as_tuple()
    result = Decimal((sign, digits, exponent + power))
    fixed = format(result, 'f')
    return fixed if len(fixed) <= 256 else str(result)


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data): return hashlib.sha256(canonical(data)).hexdigest()


def read(path, *, decimal_numbers=False):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, 'duplicate JSON key')
            out[k] = v
        return out
    def bad(_): raise ValueError('nonfinite JSON number')
    def integer(text):
        require(len(text.lstrip('-')) <= 128, 'integer coefficient bound')
        return int(text)
    raw = Path(path).read_bytes()
    require(len(raw) <= 4 * 1024 * 1024, 'JSON byte bound')
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=bad,
                       parse_int=integer, parse_float=number if decimal_numbers else float)
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        require(depth <= 64, 'JSON depth bound')
        if isinstance(node, dict):
            for key in node: key.encode('utf-8')
            stack.extend((v, depth+1) for v in node.values())
        elif isinstance(node, list): stack.extend((v, depth+1) for v in node)
        elif isinstance(node, str): node.encode('utf-8')
        elif isinstance(node, float): number(node)
    return value


def validate_view(view, expected_input_sha256, *, allow_user_material=False):
    exact(view, ('semantic_contract', 'packet', 'clarification_documents', 'input_sha256'), 'view')
    require(type(expected_input_sha256) is str and re.fullmatch('[a-f0-9]{64}', expected_input_sha256), 'trusted view hash required')
    require(view['semantic_contract'] == read(PUBLIC / 'semantic_contract.json'), 'different public semantic contract')
    actual = digest({k: v for k, v in view.items() if k != 'input_sha256'})
    require(actual == expected_input_sha256 == view['input_sha256'], 'unapproved, stale or modified visible view')
    packet = view['packet']
    exact(packet, ('schema_version', 'case_id', 'synthetic', 'request_zh', 'documents'), 'packet')
    require(type(packet['case_id']) is str and type(packet['request_zh']) is str and
            (packet['synthetic'] is True or (allow_user_material and packet['synthetic'] is False)), 'synthetic packet metadata')
    bounded_list(packet['documents'], 128, 'documents')
    bounded_list(view['clarification_documents'], 128, 'released documents')
    docs = {}
    for doc in packet['documents'] + view['clarification_documents']:
        exact(doc, ('id', 'title', 'lines'), 'document')
        require(type(doc['id']) is str and doc['id'] and doc['id'] not in docs and type(doc['title']) is str, 'document ID/title')
        bounded_list(doc['lines'], 2048, 'document lines')
        require(all(type(s) is str and len(s) <= 65536 for s in doc['lines']), 'source line type/bound')
        docs[doc['id']] = doc['lines']
    return docs


def normalize(view, candidate, expected_input_sha256, *, allow_user_material=False):
    docs = validate_view(view, expected_input_sha256, allow_user_material=allow_user_material)
    exact(candidate, ('case_id', 'input_sha256', 'review_status', 'fields', 'questions', 'conflicts', 'refusal'), 'candidate')
    require(candidate['case_id'] == view['packet']['case_id'] and candidate['input_sha256'] == expected_input_sha256, 'candidate/view binding')
    require(type(candidate['review_status']) is str and candidate['review_status'] in REVIEWS, 'review status')
    exact(candidate['fields'], KEYS, 'semantic fields')
    normalized = copy.deepcopy(candidate)
    for key, kind in zip(KEYS, TYPES):
        field = candidate['fields'][key]
        exact(field, ('status', 'value', 'unit', 'evidence'), 'field')
        state, value, unit = field['status'], field['value'], field['unit']
        require(type(state) is str and state in STATES, 'field status')
        bounded_list(field['evidence'], 2048, 'references')
        seen = set()
        for ref in field['evidence']:
            exact(ref, ('document', 'line', 'quote'), 'reference')
            doc, line, quote = ref['document'], ref['line'], ref['quote']
            require(type(doc) is str and doc in docs and type(line) is int and 1 <= line <= len(docs[doc]), 'visible source line')
            require(type(quote) is str and quote == docs[doc][line-1], 'literal quote mismatch')
            require((doc, line) not in seen, 'duplicate reference')
            seen.add((doc, line))
        if state != 'proposed':
            require(value is None and unit is None, 'unresolved value/unit must be null')
            if state == 'conflict': require(len(seen) >= 2, 'conflict needs both sources')
            continue
        require(bool(seen), 'proposed field needs a visible source')
        if kind == 'boolean': require(type(value) is bool and unit is None, 'boolean/null-unit required')
        elif kind == 'enum': require(type(value) is str and unit is None, 'enum/null-unit required')
        elif kind == 'integer': require(type(value) is int and unit is None and len(str(abs(value))) <= 128, 'integer/null-unit required')
        elif kind == 'number':
            require(unit in (None, 'dimensionless', '1'), 'dimensionless unit required')
            normalized['fields'][key].update(value=str(number(value)), unit='dimensionless')
        else:
            units = {'deg': 0, '°': 0} if key == 'incidence_angle' else LENGTH
            require(type(unit) is str and unit in units, 'explicit supported quantity unit required')
            converted = shift(value, units[unit])
            try: number(converted)
            except ValueError:
                # A legal input near the exponent bound can exceed the output
                # bound after changing units. Preserve its original unit/value.
                normalized['fields'][key].update(value=str(number(value)), unit=unit)
            else:
                normalized['fields'][key].update(value=converted, unit='deg' if key == 'incidence_angle' else 'nm')
    bounded_list(candidate['conflicts'], len(KEYS), 'conflicts')
    require(all(type(k) is str and k in KEYS for k in candidate['conflicts']), 'conflict keys')
    conflict_set = {k for k in KEYS if candidate['fields'][k]['status'] == 'conflict'}
    require(len(set(candidate['conflicts'])) == len(candidate['conflicts']) and set(candidate['conflicts']) == conflict_set, 'conflict declarations disagree')
    bounded_list(candidate['questions'], 128, 'questions')
    targets = set()
    for question in candidate['questions']:
        exact(question, ('targets', 'text'), 'question')
        bounded_list(question['targets'], len(KEYS), 'targets')
        require(bool(question['targets']) and all(type(t) is str and t in KEYS for t in question['targets']), 'question targets')
        require(len(set(question['targets'])) == len(question['targets']), 'duplicate question target')
        require(type(question['text']) is str and bool(question['text'].strip()) and len(question['text']) <= 65536, 'question text')
        targets.update(question['targets'])
    unresolved = {k for k in KEYS if candidate['fields'][k]['status'] in ('unknown', 'conflict')}
    if candidate['review_status'] != 'OUT_OF_SCOPE': require(unresolved <= targets, 'missing clarification targets')
    if candidate['review_status'] == 'REVIEW_REQUIRED': require(not unresolved, 'review cannot hide unresolved fields')
    exact(candidate['refusal'], ('reason_codes', 'text'), 'refusal')
    codes, text = candidate['refusal']['reason_codes'], candidate['refusal']['text']
    bounded_list(codes, len(REASONS), 'refusal codes')
    require(all(type(code) is str and code in REASONS for code in codes) and len(set(codes)) == len(codes), 'refusal codes')
    if candidate['review_status'] == 'OUT_OF_SCOPE': require(bool(codes) and type(text) is str and bool(text.strip()), 'refusal explanation required')
    else: require(not codes and text is None, 'unexpected refusal')
    return normalized


def projection(normalized):
    fields = []
    for key, path in zip(KEYS, PATHS):
        if path is None: continue
        field = normalized['fields'][key]
        value = field['value']
        if field['status'] == 'proposed':
            if key == 'nondispersive': value = not value
            elif key == 'spatial_dimension':
                value = int(value[:-1]) if re.fullmatch('[123]D', value) else None
            elif key in ('film_thickness', 'wavelength_min', 'wavelength_max'): value = shift(value, LENGTH[field['unit']]-3)
        fields.append({'semantic_key': key, 'implementation_key': path,
                       'mapping_note': 'COUNT_ONLY_GRID_INCOMPATIBLE' if key == 'wavelength_samples' else 'EXACT_PROJECTION_NOT_NATIVE_JSON', 'status': field['status'],
                       'value': value, 'evidence': copy.deepcopy(field['evidence'])})
    fields.append({'semantic_key': None, 'implementation_key': 'units_um',
                   'status': 'unknown', 'value': None, 'evidence': []})
    return {'kind': 'READ_ONLY_PARTIAL_PROJECTION_NOT_LEGACY_PROPOSAL', 'fields': fields,
            'layer_count': copy.deepcopy(normalized['fields']['layer_count']),
            'blocked': ['SEMANTIC_CONTRACT_DOES_NOT_SUPPLY_MEEP_UNITS_SCALE',
                        'UNIFORM_WAVELENGTH_IS_NOT_NATIVE_UNIFORM_FREQUENCY',
                        'LEGACY_BOUNDS_AND_FLOAT_PRECISION_NEED_SEPARATE_REVIEW'],
            'task_created': False, 'task_lock_created': False, 'task_approved': False}


def receipt(view, candidate, trusted_hash, *, allow_user_material=False):
    normalized = normalize(view, candidate, trusted_hash, allow_user_material=allow_user_material)
    return {'status': 'SEMANTIC_STRUCTURE_VALID_NATIVE_TASK_BRIDGE_BLOCKED',
            'normalized_response': normalized, 'implementation_projection': projection(normalized),
            'input_sha256': trusted_hash, 'semantic_entailment_verified': False,
            'revision_authority_verified': False, 'missing_conflicts_verified': False,
            'coordinator_scoring_performed': False, 'model_calls': 0, 'solver_calls': 0,
            'task_approved': False, 'task_lock_created': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('export', 'import'))
    parser.add_argument('--view', required=True)
    parser.add_argument('--expected-input-sha256', required=True, help='Trusted coordinator-released view hash, not candidate supplied')
    parser.add_argument('--candidate')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        view = read(args.view)
        validate_view(view, args.expected_input_sha256)
        if args.mode == 'export': result = copy.deepcopy(view)
        else:
            require(bool(args.candidate), 'candidate required')
            result = receipt(view, read(args.candidate, decimal_numbers=True), args.expected_input_sha256)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=False)
        (out / ('visible-view.json' if args.mode == 'export' else 'receipt.json')).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        print('EXPORTED_NOT_SENT' if args.mode == 'export' else 'STRUCTURAL_ONLY_NATIVE_TASK_BLOCKED')
    except (ValueError, TypeError, OSError, RecursionError, UnicodeError):
        parser.exit(3, 'REJECTED: invalid/unapproved view or candidate; no API, score, approval or task action\n')


if __name__ == '__main__': main()
