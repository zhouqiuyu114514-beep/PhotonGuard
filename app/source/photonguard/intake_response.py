"""Controlled rejection diagnostics; never retain untrusted response text.

Only parsed, recursively sanitized JSON is retained. It is diagnostic evidence,
not an exact copy for scoring: decimal literals are represented as text.
Malformed, overlong, nonfinite and deeply nested bodies are omitted entirely.
"""
import hashlib
import json
import re

from .backend import _redact

LIMIT_BYTES = 131072
MAX_DEPTH = 32
ASSIGNMENT = re.compile(
    r'(?i)(?:api[_ -]?key|access[_ -]?token|password|secret|authorization|密钥)'
    r'\s*[:=：]\s*[^\s，。；;]+')


class ResponseRejected(ValueError):
    def __init__(self, code, evidence):
        super().__init__('响应被受控拒绝（' + code + '）；请查看脱敏证据。')
        self.reason_code = code
        self.evidence = evidence


def _safe(value, depth=0):
    if depth > MAX_DEPTH:
        return '[OMITTED: depth limit]'
    if isinstance(value, dict):
        if any(_safe(k, depth + 1) != k for k in value):
            return {'_redacted_mapping': '[REDACTED]'}
        return {k: _safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v, depth + 1) for v in value]
    if isinstance(value, str):
        if value in {'[REDACTED]', '[OMITTED: redaction depth limit]',
                     '[OMITTED: unparseable embedded JSON]', '[OMITTED: embedded JSON]',
                     '[OMITTED: depth limit]'}:
            return value
        safe = _redact(value, None)
        # Decode Unicode escapes for assignment screening as well as sk-/Bearer.
        decoded = value
        for _ in range(MAX_DEPTH - depth):
            expanded = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), decoded)
            if expanded == decoded:
                break
            decoded = expanded
        if ASSIGNMENT.search(decoded):
            return '[REDACTED]'
        # Embedded JSON was handled recursively by the backend. Apply prose
        # assignment checks inside that representation too, or omit it whole.
        if value.lstrip().startswith(('{', '[', '"')):
            try:
                nested = json.loads(safe)
                if _safe(nested, depth + 1) != nested:
                    return '[REDACTED]'
            except (ValueError, RecursionError):
                return '[OMITTED: embedded JSON]'
        return safe
    return value


def parse_response(text):
    evidence = {'schema_version': 1, 'body': None, 'body_storage': 'OMITTED',
                'body_is_original_response': False,
                'numeric_representation': 'DECIMAL_LITERALS_AS_TEXT_NOT_FOR_SCORING'}

    def reject(code):
        evidence['reason_code'] = code
        raise ResponseRejected(code, evidence)

    if type(text) is not str:
        reject('RESPONSE_TYPE')
    encoded = text.encode('utf-8', errors='surrogatepass')
    evidence.update(original_sha256=hashlib.sha256(encoded).hexdigest(),
                    original_bytes=len(encoded), hash_encoding='UTF8_SURROGATEPASS')
    if not text.strip():
        reject('EMPTY_RESPONSE')
    if len(encoded) > LIMIT_BYTES:
        reject('RESPONSE_TOO_LARGE')
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        reject('INVALID_UNICODE')

    def unique(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                reject('DUPLICATE_JSON_KEY')
            obj[k] = v
        return obj

    def nonfinite(_):
        reject('NONFINITE_JSON_NUMBER')

    try:
        candidate = json.loads(text, object_pairs_hook=unique, parse_float=str,
                               parse_constant=nonfinite)
    except ResponseRejected:
        raise
    except json.JSONDecodeError as exc:
        # Positions and a format flag carry no exception text or response slice.
        evidence.update(json_error_line=exc.lineno, json_error_column=exc.colno,
                        code_fence_present=text.lstrip().startswith('```'))
        reject('INVALID_JSON')
    except RecursionError:
        reject('JSON_DEPTH_LIMIT')
    except ValueError:
        reject('JSON_NUMBER_LIMIT')
    stack = [(candidate, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_DEPTH:
            reject('JSON_DEPTH_LIMIT')
        if isinstance(value, dict):
            stack.extend((v, depth + 1) for v in value.values())
            stack.extend((k, depth + 1) for k in value)
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
        elif isinstance(value, str):
            try:
                value.encode('utf-8')
            except UnicodeEncodeError:
                reject('INVALID_UNICODE')
    try:
        safe = _safe(_redact(candidate, None))
    except (ValueError, TypeError, RecursionError, OverflowError):
        reject('REDACTION_LIMIT')
    evidence.update(body=safe, body_storage='SANITIZED_PARSED_JSON')
    if safe != candidate:
        reject('REDACTION_CHECK_REJECTED')
    evidence['reason_code'] = 'PARSED_SAFE_JSON'
    return candidate, evidence
