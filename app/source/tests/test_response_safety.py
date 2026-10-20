"""Synthetic end-to-end persistence regressions; every socket is forbidden."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from photonguard.backend import (ApprovedRates, BackendAuthorization, BackendError,
    DeepSeekBackend, DeepSeekConfig, TransportResponse, _redact)
from photonguard.core import load, lock_task
from photonguard.runner import run_case
from photonguard.exchange import export_request
from photonguard.api_cli import diagnose_api

ROOT = Path(__file__).parents[1]
KEY = 'SYNTHETIC_PERSISTENCE_SENTINEL_20261006'
ACTION = {'decision': 'inconclusive', 'changes': [], 'rationale': 'synthetic fixture', 'evidence_ids': []}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*a, **k): pytest.fail('Network forbidden in persistence regressions')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)


def config():
    return DeepSeekConfig('deepseek-flash', BackendAuthorization(True, 'SYNTHETIC-ONLY',
        'deepseek-flash', '.042', 1, ApprovedRates('.30', '1.20',
        datetime.now(timezone.utc).isoformat(), 'https://api-docs.deepseek.com/quick_start/pricing/')), KEY)


def envelope(action):
    content = json.dumps(action).replace(KEY, ''.join('\\u%04x' % ord(c) for c in KEY))
    return {'id': 'synthetic', 'model': 'deepseek-flash',
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}


def recoverable(value, depth=0):
    assert depth <= 40
    if isinstance(value, dict):
        return any(KEY in k or recoverable(v, depth+1) for k, v in value.items())
    if isinstance(value, list):
        return any(recoverable(v, depth+1) for v in value)
    if isinstance(value, str):
        if KEY in value: return True
        try: decoded = json.loads(value)
        except ValueError: return False
        return recoverable(decoded, depth+1)
    return False


@pytest.mark.parametrize('value', [
    {KEY: 'first', '[REDACTED]': 'second'},
    {'outer': [{KEY: 'first'}]},
    {'outer': {KEY: 'first', 'Bearer synthetic-other-token': 'second'}},
    json.dumps({KEY: 'first'}).replace(KEY, ''.join('\\u%04x' % ord(c) for c in KEY)),
    json.dumps(json.dumps({'rationale': KEY})),
])
def test_nested_keys_strings_and_collisions(value):
    clean = _redact(value, KEY)
    assert not recoverable(clean)
    assert 'first' not in json.dumps(clean) and 'second' not in json.dumps(clean)
    assert _redact(clean, KEY) == clean


@pytest.mark.parametrize('body,status,truncated', [
    (KEY.encode(), 200, False),
    (('invalid ' + KEY).encode(), 401, False),
    (json.dumps({KEY: 'error', 'nested': {'message': KEY}}).encode(), 500, False),
    ((KEY * 10).encode(), 200, True),
    (b'{"model":"bad","choices":', 200, False),
])
def test_unparseable_http_and_truncated_bodies_are_never_retained(body, status, truncated):
    cfg = config()
    def transport(_): return TransportResponse(status, body, truncated=truncated)
    with pytest.raises(BackendError) as error:
        DeepSeekBackend(cfg, transport=transport).diagnose(
            {'prompt': 'synthetic', 'task': {}, 'candidate': {}, 'observations': {}, 'allowed_actions': {}})
    audit = error.value.audit
    assert audit['response'] is None
    assert audit['response_sha256'] == hashlib.sha256(body).hexdigest()
    assert not recoverable(audit)
    assert audit['budget']['attempts'] == 1
    assert audit['budget']['reserved_usd'] == '0.0417792'


@pytest.fixture
def evidence(tmp_path):
    folder = ROOT / 'examples/epsilon_mismatch'
    lock = tmp_path / 'lock.json'
    lock_task(folder / 'task.json', lock)
    return run_case(folder / 'task.json', folder / 'candidate.json', lock, tmp_path / 'runs', 0)[1]


@pytest.mark.parametrize('entry', ['api_cli', 'once'])
@pytest.mark.parametrize('mode', ['rationale', 'action_key', 'metadata', 'http_error',
                                   'bad_json', 'oversized', 'decision_object', 'decision_list',
                                   'decision_null', 'decision_bool', 'decision_number'])
def test_every_saved_exit_is_safe_and_invalid_decisions_are_controlled(
        entry, mode, evidence, tmp_path, monkeypatch, capsys):
    cfg = config()
    action = {**ACTION}
    if mode == 'rationale': action['rationale'] = json.dumps({'echo': KEY})
    if mode == 'action_key': action[KEY] = 'untrusted'
    decisions = {'decision_object': {}, 'decision_list': [], 'decision_null': None,
                 'decision_bool': True, 'decision_number': 123}
    if mode in decisions: action['decision'] = decisions[mode]
    body = envelope(action)
    if mode == 'metadata':
        body[KEY] = [{'extra': KEY}]
        body['usage']['untrusted'] = KEY
        body['choices'][0]['untrusted'] = KEY
    raw = json.dumps(body).encode()
    if mode == 'http_error': raw = KEY.encode()
    if mode == 'bad_json': raw = ('{ broken ' + KEY).encode()
    if mode == 'oversized': raw = (KEY * 33000).encode()
    calls = []
    def transport(request):
        calls.append(request)
        return TransportResponse(500 if mode == 'http_error' else 200, raw)
    monkeypatch.setattr('photonguard.backend._urllib_transport', transport)
    auth = cfg.authorization
    authorization = {'approved': True, 'reference': auth.reference, 'model': auth.model,
        'total_budget_usd': auth.total_budget_usd, 'max_calls': 1,
        'rates': vars(auth.rates)}
    session = tmp_path / 'session'
    session.mkdir()
    ledger = tmp_path / 'budget.ledger.json'
    if entry == 'api_cli':
        config_path = tmp_path / 'config.json'
        config_path.write_text(json.dumps({'authorization': authorization, 'model': cfg.model}))
        monkeypatch.setenv('DEEPSEEK_API_KEY', KEY)
        args = SimpleNamespace(approve_data_and_cost=True, config=config_path, evidence=evidence,
                               ledger=ledger, audit_dir=session / 'audit', out=session / 'proposal.json')
        outcome = diagnose_api(args)
        summary_file = session / 'audit/validation.json'
        audit_file = next((session / 'audit').glob('*audit.json'), None)
    else:
        spec = importlib.util.spec_from_file_location('persistence_once', ROOT / 'tools/run_deepseek_once.py')
        once = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(once)
        request = export_request(evidence)
        plan = {'authorization': authorization, 'cny_approval': {
            'total_budget_cny': '.28', 'input_cny_per_million': '2', 'output_cny_per_million': '8',
            'checked_at': auth.rates.checked_at, 'source': 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'},
            'limits': {}, 'evidence': str(evidence),
            'diagnostic_request_sha256': once.digest(request)}
        (session / 'plan.json').write_text(json.dumps(plan))
        (session / 'diagnostic-request.json').write_text(json.dumps(request))
        monkeypatch.setattr(once, 'SESSION', session)
        monkeypatch.setattr(once, 'LEDGER', ledger)
        monkeypatch.setattr(once, 'interactive_terminal', lambda: True)
        monkeypatch.setattr(once.getpass, 'getpass', lambda p: KEY)
        monkeypatch.setattr(once, 'authenticate', lambda *a: {'authenticated': True})
        outcome = once.run()
        summary_file = session / 'summary.json'
        audit_file = session / 'provider.audit.json'
        assert summary_file.exists()
    if mode in decisions or mode in {'action_key', 'http_error', 'bad_json', 'oversized'}:
        assert outcome == 3
    if mode in decisions:
        assert load(summary_file)['status'] == ('REJECTED' if entry == 'api_cli' else 'ACTION_REJECTED')
    assert len(calls) == 1
    assert load(ledger)['attempts'] == 1
    assert load(ledger)['reserved_usd'] == '0.0417792'
    if entry == 'once': assert load(ledger)['reserved_cny'] == '0.278528000001'
    for path in session.rglob('*.json'):
        assert not recoverable(load(path)), path.name
    output = capsys.readouterr()
    assert KEY not in output.out + output.err
    audit = load(audit_file) if audit_file else load(session / 'audit/provenance.json')['provider_audit']
    assert audit['response'] is None
    if mode in {'rationale', 'metadata'}:
        saved = json.loads(audit['response_json']['choices'][0]['message']['content'])
        action_file = session / ('audit/response.action.json' if entry == 'api_cli' else 'response.action.json')
        assert saved == load(action_file)
