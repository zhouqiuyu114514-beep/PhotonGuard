import io
import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from photonguard.backend import TransportResponse
from photonguard.experiments import ai_binding as ab
from photonguard.experiments.service import store_for
from photonguard.product_phase import json_payload
from photonguard.workflow import WorkflowError, WorkflowStore
from test_workflow_security import server, request

KEY = 'sk-SYNTHETICPERSONALTESTKEY000000'


def config(**extra):
    return {'api_key': KEY, 'request_limit': 20, 'approve': True, **extra}


@pytest.fixture
def owner(tmp_path):
    value = WorkflowStore(tmp_path / 'workspace', allow_workers=False)
    yield value
    value.close()


@pytest.fixture
def manager(owner, monkeypatch):
    monkeypatch.setattr(ab, 'account_check', lambda key: None)
    return ab.manager_for(owner)


def response(**extra):
    return TransportResponse(200, json.dumps({'id': 'synthetic', 'model': ab.MODEL,
        'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}, **extra}).encode())


def test_connection_restart_disconnect_never_restores_owner_key(manager, owner):
    old = SimpleNamespace(status=lambda: {'live_enabled': True})
    owner.product_client = old
    assert store_for(owner).client is old
    manager.connect(config())
    connected = store_for(owner).client
    assert connected is manager.client
    assert KEY not in json.dumps(manager.status())
    assert all(KEY.encode() not in p.read_bytes() for p in owner.root.rglob('*') if p.is_file())
    manager.disconnect()
    assert connected._key is None
    assert store_for(owner).client is None
    owner.close()
    restarted = WorkflowStore(owner.root, allow_workers=False)
    try:
        restarted.product_client = old
        assert store_for(restarted).client is None
        assert ab.manager_for(restarted).status()['managed']
    finally:
        restarted.close()


@pytest.mark.parametrize('extra', [{'approve': False}, {'request_limit': True}, {'request_limit': 0},
    {'request_limit': 1.5}, {'request_limit': -1}, {'request_limit': ab.MAX_SAFE_REQUESTS + 1}, {'api_key': 'password'}, {'api_key': KEY+'\r\nInjected'}, {'endpoint': 'https://evil.invalid'}])
def test_invalid_binding_never_probes(manager, monkeypatch, extra):
    monkeypatch.setattr(ab, 'account_check', lambda key: pytest.fail('must reject before network'))
    with pytest.raises(WorkflowError):
        manager.connect(config(**extra))
    assert not manager.status()['connected']


def test_failed_replacement_keeps_existing_connection(manager, monkeypatch):
    manager.connect(config())
    client = manager.client
    def fail(key):
        raise WorkflowError('invalid key')
    monkeypatch.setattr(ab, 'account_check', fail)
    with pytest.raises(WorkflowError):
        manager.connect(config(api_key=KEY+'NEW'))
    assert manager.client is client
    assert manager.status()['live_enabled']


def test_success_cap_persists_and_explicit_raise(manager, monkeypatch, owner):
    sent = []
    def transport(req):
        sent.append(req)
        return response()
    monkeypatch.setattr(ab.wire, '_urllib_transport', transport)
    manager.connect(config(request_limit=1))
    result = manager.client.complete('first', json_payload('JSON', {'value': 1}))
    assert result['audit']['usage_settled']
    assert result['audit']['estimated_peak_cost_cny'] is None
    assert manager.quota.snapshot()['settled_tokens'] == 110
    assert not manager.status()['live_enabled']
    with pytest.raises(WorkflowError):
        manager.client.complete('second', json_payload('JSON', {}))
    manager.disconnect()
    with pytest.raises(WorkflowError):
        manager.connect(config(request_limit=1))
    manager.connect(config(request_limit=2))
    assert manager.status()['requests_used'] == 1
    manager.client.complete('second', json_payload('JSON', {}))
    assert len(sent) == 2
    assert all(KEY.encode() not in p.read_bytes() for p in owner.root.rglob('*') if p.is_file())


@pytest.mark.parametrize('kind', ['timeout', 'usage', 'model', 'secret', 'overbound', 'http'])
def test_failures_hold_reservation_and_require_explicit_recovery(manager, monkeypatch, kind):
    calls = []
    def transport(req):
        calls.append(req)
        if kind == 'timeout':
            raise TimeoutError(KEY)
        if kind == 'usage':
            return response(usage=None)
        if kind == 'model':
            return response(model='other')
        if kind == 'overbound':
            return response(usage={'prompt_tokens': 200000, 'completion_tokens': 10, 'total_tokens': 200010})
        if kind == 'http':
            return TransportResponse(401, KEY.encode())
        return response(choices=[{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': KEY}}])
    monkeypatch.setattr(ab.wire, '_urllib_transport', transport)
    manager.connect(config())
    payload = json_payload('JSON', {'test': kind})
    with pytest.raises(WorkflowError) as caught:
        manager.client.complete('first', payload)
    assert KEY not in str(caught.value)
    assert manager.status()['needs_recovery']
    with pytest.raises(WorkflowError):
        manager.connect(config())
    manager.connect(config(resume=True))
    assert manager.quota.snapshot()['held_tokens'] == ab.TOKEN_BOUND
    assert manager.status()['requests_used'] == 1
    with pytest.raises(WorkflowError):
        manager.client.complete('retry', payload)
    assert len(calls) == 1
    assert manager.status()['requests_used'] == 1


def test_connect_disconnect_cannot_race_paid_call(manager, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def transport(req):
        entered.set()
        assert release.wait(3)
        return response()
    monkeypatch.setattr(ab.wire, '_urllib_transport', transport)
    manager.connect(config())
    thread = threading.Thread(target=manager.client.complete, args=('first', json_payload('JSON', {})))
    thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(WorkflowError):
            manager.disconnect()
        with pytest.raises(WorkflowError):
            manager.connect(config())
        assert manager.status()['in_flight']
    finally:
        release.set()
        thread.join(3)


def test_crash_pending_survives_restart(manager, owner):
    manager.connect(config())
    manager.quota.request_hash = 'a' * 64
    manager.quota.reserve_worst(True)
    fresh = ab.BindingManager(owner)
    assert fresh.status()['needs_recovery']
    assert not fresh.status()['connected']
    fresh.connect(config(resume=True))
    assert fresh.status()['requests_used'] == 1
    assert fresh.quota.snapshot()['unknown_hashes'] == ['a' * 64]


def test_http_csrf_and_no_secret_echo(server, monkeypatch):
    probes = []
    monkeypatch.setattr(ab, 'account_check', lambda key: probes.append(True))
    for omit in (['Origin'], ['X-CSRF-Token']):
        assert request(server, 'POST', '/api/experiments/ai/connect', config(), omit=omit)[0] == 403
    assert not probes
    status, headers, body = request(server, 'POST', '/api/experiments/ai/connect', config())
    assert status == 200 and KEY.encode() not in body
    assert headers['Cache-Control'] == 'no-store'
    assert len(probes) == 1
    status, _, body = request(server, path='/api/experiments/bootstrap')
    assert json.loads(body)['ai']['live_enabled']
    assert KEY.encode() not in body
    assert request(server, 'POST', '/api/experiments/ai/disconnect', {})[0] == 200


@pytest.mark.parametrize('mode', ['good', 'redirect', '401', 'timeout', 'oversize', 'unavailable', 'model_missing', 'invalid'])
def test_account_probe_uses_only_official_get_and_sanitizes(monkeypatch, mode):
    seen = []
    class Reply(io.BytesIO):
        status = 200
        def geturl(self):
            return 'https://evil.invalid' if mode == 'redirect' else seen[-1].full_url
        def read1(self, size):
            return self.read(size)
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            assert req.get_method() == 'GET' and req.data is None
            assert req.full_url in (ab.API+'/models', ab.API+'/user/balance')
            assert timeout == 12
            if mode == '401':
                raise HTTPError(req.full_url, 401, KEY, {}, io.BytesIO(KEY.encode()))
            if mode == 'timeout':
                raise TimeoutError(KEY)
            value = {'data': [{'id': ab.MODEL}]} if req.full_url.endswith('/models') else {'is_available': True}
            if mode == 'unavailable':
                value = {'data': [{'id': ab.MODEL}], 'is_available': False}
            if mode == 'model_missing':
                value = {'data': []}
            return Reply(b'x'*65537 if mode == 'oversize' else KEY.encode() if mode == 'invalid' else json.dumps(value).encode())
    monkeypatch.setattr(ab, 'build_opener', lambda *handlers: Opener())
    if mode == 'good':
        ab.account_check(KEY)
        assert len(seen) == 2
    else:
        with pytest.raises(WorkflowError) as caught:
            ab.account_check(KEY)
        assert KEY not in str(caught.value)


@pytest.mark.parametrize("limit", [101, 1000, 1000000, ab.MAX_SAFE_REQUESTS])
def test_user_quota_above_old_cap_persists(manager, owner, limit):
    manager.connect(config(request_limit=limit))
    assert manager.status()['request_limit'] == limit
    assert ab.RequestQuota(owner).snapshot()['limit'] == limit
    manager.quota.state['attempts'] = 100
    manager.quota.write()
    manager.quota.request_hash = 'a' * 64
    manager.quota.reserve_worst(None)
    assert manager.quota.snapshot()['attempts'] == 101
    assert manager.quota.snapshot()['limit'] == limit
