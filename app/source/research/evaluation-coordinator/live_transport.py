"""Bounded semantic-intake transport, separate from the consumed diagnostic.

No raw HTTP body, headers, unknown envelope fields or exception text is retained.
Credential-free assistant content is returned unchanged for original scoring.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from decimal import Decimal
import hashlib
import json
import re
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from photonguard.backend import (_scrub_text, _SECRET_FIELDS, _strict_json,
                                _urllib_transport, TransportRequest, TransportResponse)

ENDPOINT = 'https://api.deepseek.com/chat/completions'
MAX_REQUEST_BYTES = 120000
MAX_RESPONSE_BYTES = 1048576
INPUT_BOUND = 131072
OUTPUT_BOUND = 4096


def digest(data):
    return hashlib.sha256(data).hexdigest()


def credential_risk(text, key=None, depth=0):
    """Bounded known-key/credential/inner-JSON check; custom encodings excluded."""
    if depth > 32:
        return True
    if isinstance(text, dict):
        return any(str(k).casefold() in _SECRET_FIELDS or credential_risk(str(k), key, depth+1)
                   or credential_risk(v, key, depth+1) for k, v in text.items())
    if isinstance(text, list):
        return any(credential_risk(v, key, depth+1) for v in text)
    if not isinstance(text, str):
        return False
    decoded = text
    for _ in range(32-depth):
        if _scrub_text(decoded, key) != decoded:
            return True
        expanded = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), decoded)
        if expanded == decoded:
            break
        decoded = expanded
    if text.lstrip().startswith(('{', '[', '"')):
        try:
            parsed = json.loads(text)
        except (ValueError, RecursionError):
            return False
        return credential_risk(parsed, key, depth+1)
    return False


def complete(payload, key, ledger, *, transport=None, require_existing_ledger=False):
    """Every dispatch reserves once; failures never refund or auto retry."""
    live = transport is None
    send = transport or _urllib_transport
    audit = {'status': 'PREFLIGHT', 'live_dispatch': False, 'model_response_received': False,
             'actual_completed_calls': None, 'response': None,
             'response_storage': 'OMITTED_UNTRUSTED_HTTP_BODY', 'usage': None,
             'estimated_peak_cost_cny': None, 'cost_is_provider_bill': False,
             'transport_kind': 'live_https' if live else 'injected_mock'}
    if (payload.get('model') != ledger.authorization.model or
            payload.get('max_tokens') != OUTPUT_BOUND or payload.get('stream') is not False or
            payload.get('thinking') != {'type': 'disabled'}):
        raise ValueError('unfrozen request settings')
    if credential_risk(payload, key):
        raise ValueError('credential-shaped request forbidden')
    body = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError('request size bound exceeded')
    audit.update(request_sha256=digest(body), request_bytes=len(body))
    context_ledger = callable(getattr(ledger, 'reserve_worst', None))
    if context_ledger:
        if not require_existing_ledger:
            raise ValueError('Context-bound ledger requires an existing one-shot batch')
        audit['budget'] = ledger.reserve_worst(live, require_existing=True)
        reservation_id = audit['budget']['pending']['id']
    else:
        reservation = (Decimal(INPUT_BOUND)*Decimal(str(ledger.authorization.rates.input_usd_per_million)) +
                       Decimal(OUTPUT_BOUND)*Decimal(str(ledger.authorization.rates.output_usd_per_million))) / Decimal(1000000)
        audit['budget'] = (ledger.reserve(reservation, live, require_existing=True)
                           if require_existing_ledger else ledger.reserve(reservation, live))
    audit['live_dispatch'] = live
    tick = time.perf_counter()
    def outcome(status, message=None):
        if context_ledger and status != 'ASSISTANT_RETURNED':
            # Failed, ambiguous or malformed calls retain the whole reservation.
            # A crashed process leaves pending in the atomic ledger and cannot replay.
            try:
                ledger.halt()
            except (ValueError, OSError):
                audit['ledger_halt_failed'] = True
        audit.update(status=status, elapsed_seconds=time.perf_counter()-tick)
        return {'audit': audit, 'assistant': message}
    try:
        response = send(TransportRequest(ENDPOINT, body, 45, MAX_RESPONSE_BYTES,
            {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json', 'Accept': 'application/json'}))
    except Exception:
        return outcome('TRANSPORT_FAILURE')
    if not isinstance(response, TransportResponse) or not isinstance(response.body, bytes):
        return outcome('INVALID_TRANSPORT_RESPONSE')
    raw = response.body[:MAX_RESPONSE_BYTES]
    audit.update(response_sha256=digest(raw), response_bytes=len(raw),
                 response_sha256_scope='retained_prefix' if response.truncated or len(response.body)>MAX_RESPONSE_BYTES else 'received_body')
    if type(response.status_code) is int and 100 <= response.status_code <= 599:
        audit['http_status'] = response.status_code
    if response.final_url != ENDPOINT or type(response.status_code) is not int or 300 <= response.status_code < 400:
        return outcome('REDIRECT_OR_INVALID_STATUS')
    if response.truncated or len(response.body)>MAX_RESPONSE_BYTES:
        return outcome('RESPONSE_SIZE_FAILURE')
    if response.status_code != 200:
        return outcome('HTTP_FAILURE')
    try:
        envelope = _strict_json(raw.decode('utf-8'))
    except (ValueError, UnicodeError, RecursionError):
        return outcome('INVALID_ENVELOPE_JSON')
    if not isinstance(envelope, dict):
        return outcome('INVALID_ENVELOPE_TYPE')
    model = envelope.get('model')
    choices = envelope.get('choices')
    if (not isinstance(model, str) or not 1 <= len(model) <= 128 or credential_risk(model, key) or
            not isinstance(choices, list) or len(choices)!=1 or not isinstance(choices[0], dict)):
        return outcome('INVALID_MODEL_OR_CHOICES')
    if context_ledger and model != ledger.authorization.model:
        return outcome('MODEL_ID_MISMATCH')
    audit.update(provider_model=model, model_response_received=True,
                 actual_completed_calls=1 if live else 0)
    cid = envelope.get('id')
    if isinstance(cid, str) and len(cid)<=256 and not credential_risk(cid, key):
        audit['completion_id'] = cid
    choice = choices[0]
    finish = choice.get('finish_reason')
    if isinstance(finish, str) and len(finish)<=64 and not credential_risk(finish, key):
        audit['finish_reason'] = finish
    usage = envelope.get('usage')
    valid_usage = (isinstance(usage, dict) and all(type(usage.get(k)) is int and 0 <= usage[k] <= 10000000
                   for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')) and
                   usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens'])
    if valid_usage:
        audit['usage'] = {k:usage[k] for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')}
        for k in ('prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'):
            if type(usage.get(k)) is int and 0 <= usage[k] <= usage['prompt_tokens']:
                audit['usage'][k] = usage[k]
        estimated_cny = ledger.estimated_cny(audit['usage'])
        audit['estimated_peak_cost_cny'] = str(estimated_cny) if estimated_cny is not None else None
        if not context_ledger and (usage['prompt_tokens']>INPUT_BOUND or usage['completion_tokens']>OUTPUT_BOUND):
            ledger.halt()
            audit['usage_exceeded_reservation'] = True
    else:
        if not context_ledger:
            ledger.halt()
        audit['usage_missing_or_invalid'] = True
        if context_ledger:
            return outcome('INVALID_USAGE')
    message = choice.get('message')
    if not isinstance(message, dict) or message.get('role')!='assistant':
        return outcome('INVALID_ASSISTANT_MESSAGE')
    content = message.get('content')
    calls = message.get('tool_calls')
    safe_message = {'role': 'assistant', 'content': content}
    if content is not None and not isinstance(content, str):
        return outcome('INVALID_ASSISTANT_CONTENT')
    if credential_risk(content, key):
        return outcome('SAFETY_STOP')
    if calls is not None:
        if not isinstance(calls, list) or len(calls)>8:
            return outcome('INVALID_TOOL_CALLS')
        safe_calls = []
        for call in calls:
            if not isinstance(call, dict) or call.get('type')!='function':
                return outcome('INVALID_TOOL_CALLS')
            fn=call.get('function');identifier=call.get('id')
            if (not isinstance(fn,dict) or not isinstance(identifier,str) or not 1 <= len(identifier)<=128 or
                    not isinstance(fn.get('name'),str) or not 1 <= len(fn['name'])<=80 or
                    not isinstance(fn.get('arguments'),str)):
                return outcome('INVALID_TOOL_CALLS')
            item={'id':identifier,'type':'function','function':{'name':fn['name'],'arguments':fn['arguments']}}
            if credential_risk(item,key):
                return outcome('SAFETY_STOP')
            safe_calls.append(item)
        safe_message['tool_calls']=safe_calls
    if message.get('reasoning_content') or message.get('function_call') or message.get('refusal'):
        audit['unexpected_message_fields'] = True
        return outcome('UNSUPPORTED_MESSAGE_FIELDS', safe_message)
    status = 'ASSISTANT_RETURNED' if finish in ('stop', 'tool_calls') else 'INCOMPLETE_RETURN'
    if context_ledger and status == 'ASSISTANT_RETURNED':
        try:
            audit['budget_after_settlement'] = ledger.settle_usage(reservation_id, usage)
            audit['usage_settled'] = True
        except (ValueError, OSError):
            audit['usage_settled'] = False
            return outcome('USAGE_OR_SETTLEMENT_STOP')
    return outcome(status, safe_message)


def raw_member(text, name):
    """Extract exact member lexeme without reconstructing decimal/Unicode JSON."""
    decoder=json.JSONDecoder()
    pos=0
    def space(i):
        while i<len(text) and text[i] in ' \t\r\n':i+=1
        return i
    pos=space(pos)
    if text[pos:pos+1]!='{':raise ValueError('object required')
    pos=space(pos+1);found=None;keys=set()
    while text[pos:pos+1]!='}':
        key,end=decoder.raw_decode(text,pos)
        if not isinstance(key,str) or key in keys:raise ValueError('unique keys required')
        keys.add(key);pos=space(end)
        if text[pos:pos+1]!=':':raise ValueError('colon required')
        start=space(pos+1);unused,end=decoder.raw_decode(text,start)
        if key==name:found=text[start:end]
        pos=space(end)
        if text[pos:pos+1]==',':pos=space(pos+1)
        elif text[pos:pos+1]!='}':raise ValueError('delimiter required')
    if space(pos+1)!=len(text) or found is None:raise ValueError('member required')
    return found
