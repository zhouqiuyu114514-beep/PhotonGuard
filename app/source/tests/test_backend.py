"""Offline transport/guardrail compatibility tests ONLY: zero live API calls.

All response bodies are explicitly synthetic fixtures. These tests provide no
DeepSeek model-performance, diagnostic-accuracy, or live-API compatibility claim.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
import json
import socket
import urllib.error

import pytest

from photonguard.backend import (
    ApprovedRates, BackendAuthorization, BackendError, BudgetLedger,
    DeepSeekBackend, DeepSeekConfig, ENDPOINT, PersistentBudgetLedger,
    TransportRequest, TransportResponse, _NoRedirects, _urllib_transport,
)

SYNTHETIC_KEY = "sk-offline-unit-test-not-a-real-key"
ACTION = {"decision": "inconclusive", "changes": [], "rationale": "Synthetic offline fixture", "evidence_ids": []}


@pytest.fixture(autouse=True)
def prohibit_live_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("These are mock compatibility tests; live networking is forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def config():
    return DeepSeekConfig(
        model="deepseek-flash", api_key=SYNTHETIC_KEY,
        authorization=BackendAuthorization(
            approved=True, reference="OFFLINE-TEST-FIXTURE-NOT-USER-APPROVAL", model="deepseek-flash",
            total_budget_usd="0.10", max_calls=2,
            rates=ApprovedRates("0.30", "1.20", "2026-10-05", "https://api-docs.deepseek.com/quick_start/pricing/")))


@pytest.fixture
def request_data():
    return {"prompt": "Diagnose this synthetic test fixture.", "task": {"locked": True},
            "candidate": {}, "observations": {"checks": []}, "allowed_actions": {"maximum_changes": 1},
            "excluded_test_label": "DO NOT FORWARD THIS FIELD"}


def envelope(**updates):
    result = {"id": "synthetic-offline-response", "model": "synthetic-provider-model-version",
              "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(ACTION)}}],
              "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}}
    result.update(updates)
    return result


class MockTransport:
    """A test-only callable that never uses a network transport."""
    def __init__(self, value=None, error=None, status=200, final_url=ENDPOINT, truncated=False):
        self.value = envelope() if value is None else value
        self.error = error
        self.status = status
        self.final_url = final_url
        self.truncated = truncated
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        body = self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode()
        return TransportResponse(self.status, body, self.final_url, self.truncated)


def test_json_transport_mock_preserves_actual_fixture_and_metadata(config, request_data):
    mock = MockTransport()
    backend = DeepSeekBackend(config, transport=mock)
    result = backend.diagnose(request_data)
    assert result["action"] == ACTION
    audit = result["audit"]
    assert audit["transport_kind"] == "injected_mock"
    assert audit["actual_llm_calls"] == 0
    assert audit["provider_model"] == "synthetic-provider-model-version"
    assert audit["usage"] == envelope()["usage"]
    assert audit["response"] is None
    assert audit["response_storage"] == "omitted_untrusted_raw_body"
    assert audit["response_json"] == envelope()
    assert audit["status"] == "response_received"
    assert audit["action_validation"] == "pending_independent_validator"
    assert audit["cost_is_provider_bill"] is False
    assert audit["estimated_cost_usd"] == "0.000078"
    assert audit["budget"]["attempts"] == 1
    assert audit["budget"]["live_provider_attempts"] == 0
    assert Decimal(audit["budget"]["reserved_usd"]) == Decimal("0.0417792")
    assert audit["approval"]["approved_rates"]["checked_at"] == "2026-10-05"
    payload = json.loads(mock.calls[0].body)
    assert payload["model"] == config.model
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_tokens"] == 2048
    assert payload["stream"] is False
    assert "json" in payload["messages"][0]["content"]
    assert '"decision":"inconclusive"' in payload["messages"][0]["content"]
    assert "DO NOT FORWARD THIS FIELD" not in mock.calls[0].body.decode()
    assert json.loads(payload["messages"][1]["content"])["task"] == request_data["task"]
    assert mock.calls[0].headers["Authorization"] == "Bearer " + SYNTHETIC_KEY
    assert SYNTHETIC_KEY not in repr(mock.calls[0])
    assert SYNTHETIC_KEY not in repr(config)
    assert SYNTHETIC_KEY not in json.dumps(audit)


@pytest.mark.parametrize("change", [
    {"model": ""}, {"model": "different-unapproved-model"}, {"authorization": None},
    {"api_key": None}, {"api_key": ""}, {"api_key": "bad\nkey"},
    {"endpoint": "http://api.deepseek.com/chat/completions"},
    {"endpoint": "https://api.deepseek.com.attacker.invalid/chat/completions"},
    {"endpoint": "https://user:pass@api.deepseek.com/chat/completions"},
    {"endpoint": "https://api.deepseek.com/chat/completions?api_key=leak"},
    {"endpoint": "https://api.deepseek.com:443/chat/completions"},
    {"endpoint": "https://example.com/chat/completions"},
    {"timeout_seconds": 61}, {"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
    {"max_request_bytes": 65537}, {"max_response_bytes": 1048577}, {"max_tokens": 4097},
    {"max_tokens": True}, {"input_token_reservation": 100},
])
def test_preflight_blocks_before_transport(config, request_data, change):
    mock = MockTransport()
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(replace(config, **change), transport=mock).diagnose(request_data)
    assert caught.value.audit["status"] == "blocked"
    assert caught.value.audit["actual_llm_calls"] == 0
    assert len(mock.calls) == 0


@pytest.mark.parametrize("change", [
    {"approved": False}, {"reference": ""}, {"max_calls": 3}, {"max_calls": 0},
    {"total_budget_usd": "0"}, {"total_budget_usd": "NaN"}, {"total_budget_usd": "0.001"},
    {"total_budget_usd": "Infinity"},
    {"rates": ApprovedRates("0.3", "1.2", "", "https://api-docs.deepseek.com/quick_start/pricing/")},
    {"rates": ApprovedRates("0.3", "1.2", "2026-10-05", "https://attacker.invalid/pricing")},
    {"rates": ApprovedRates("0", "1.2", "2026-10-05", "https://api-docs.deepseek.com/quick_start/pricing/")},
])
def test_approval_and_conservative_budget_fail_closed(config, request_data, change):
    mock = MockTransport()
    c = replace(config, authorization=replace(config.authorization, **change))
    with pytest.raises(BackendError):
        DeepSeekBackend(c, transport=mock).diagnose(request_data)
    assert len(mock.calls) == 0


def test_no_environment_credentials_are_discovered(config, request_data, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", SYNTHETIC_KEY)
    with pytest.raises(BackendError, match="credential"):
        DeepSeekBackend(replace(config, api_key=None)).diagnose(request_data)


def test_no_authorization_no_network_even_with_credential(config, request_data):
    with pytest.raises(BackendError, match="authorization"):
        DeepSeekBackend(replace(config, authorization=None)).diagnose(request_data)


def test_two_failed_attempts_count_and_never_retry(config, request_data):
    mock = MockTransport(error=RuntimeError("Secret echo " + SYNTHETIC_KEY))
    backend = DeepSeekBackend(config, transport=mock)
    for attempt in (1, 2):
        with pytest.raises(BackendError) as caught:
            backend.diagnose(request_data)
        assert caught.value.audit["status"] == "transport_error"
        assert caught.value.audit["budget"]["attempts"] == attempt
        assert SYNTHETIC_KEY not in str(caught.value)
        assert SYNTHETIC_KEY not in json.dumps(caught.value.audit)
        assert len(mock.calls) == attempt
    with pytest.raises(BackendError) as caught:
        backend.diagnose(request_data)
    assert caught.value.audit["status"] == "blocked"
    assert len(mock.calls) == 2


def test_no_refund_even_after_low_token_response(config, request_data):
    c = replace(config, authorization=replace(config.authorization, total_budget_usd="0.05"))
    mock = MockTransport()
    backend = DeepSeekBackend(c, transport=mock)
    backend.diagnose(request_data)
    with pytest.raises(BackendError):
        backend.diagnose(request_data)
    assert len(mock.calls) == 1


@pytest.mark.parametrize("body,expected", [
    (b"", "invalid_response"), (b"not json", "invalid_response"),
    (b"{\xff}", "invalid_response"), (b"[]", "invalid_response"),
    (b'{"model":"a","model":"b"}', "invalid_response"),
    (b'{"model":NaN}', "invalid_response"),
    (b'{"model":"\\ud800"}', "invalid_response"),
    (b'{"\\ud800":"bad key"}', "invalid_response"),
    (envelope(choices=[]), "invalid_response"), (envelope(model=None), "invalid_response"),
    (envelope(usage=None), "invalid_response"),
    (envelope(usage={"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1}), "invalid_response"),
    (envelope(usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 100}), "invalid_response"),
])
def test_bad_envelopes_are_audited_not_retried(config, request_data, body, expected):
    mock = MockTransport(body)
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=mock).diagnose(request_data)
    assert caught.value.audit["status"] == expected
    assert caught.value.audit["response"] is None
    assert caught.value.audit["budget"]["attempts"] == 1
    assert len(mock.calls) == 1


@pytest.mark.parametrize("content,finish,expected", [
    ("", "stop", "empty_content"), ("   ", "stop", "empty_content"),
    (None, "stop", "empty_content"), ("{}", "length", "incomplete_response"),
    ("{}", "content_filter", "incomplete_response"),
    ("```json\n{}\n```", "stop", "invalid_response"),
    ("[]", "stop", "invalid_response"), ("{\"x\":NaN}", "stop", "invalid_response"),
    ("{\"x\":1,\"x\":2}", "stop", "invalid_response"),
    ('{"rationale":"\\ud800"}', "stop", "invalid_response"),
])
def test_bad_completions_are_audited(config, request_data, content, finish, expected):
    body = envelope()
    body["choices"][0].update(finish_reason=finish, message={"content": content})
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=MockTransport(body)).diagnose(request_data)
    assert caught.value.audit["status"] == expected
    assert caught.value.audit["provider_model"] == body["model"]
    assert caught.value.audit["finish_reason"] == finish
    assert caught.value.audit["usage"] == body["usage"]


def test_model_action_is_not_implicitly_approved(config, request_data):
    body = envelope()
    body["choices"][0]["message"]["content"] = '{"arbitrary_untrusted_action":true}'
    result = DeepSeekBackend(config, transport=MockTransport(body)).diagnose(request_data)
    assert result["action"] == {"arbitrary_untrusted_action": True}
    assert result["audit"]["action_validation"] == "pending_independent_validator"


def test_credential_echo_is_redacted_from_all_returned_paths(config, request_data):
    request_data["task"].update(api_key="unrelated-secret", context=SYNTHETIC_KEY)
    body = envelope()
    body["choices"][0]["message"]["content"] = json.dumps({**ACTION, "rationale": SYNTHETIC_KEY})
    mock = MockTransport(body)
    result = DeepSeekBackend(config, transport=mock).diagnose(request_data)
    assert SYNTHETIC_KEY not in json.dumps(result)
    assert b"unrelated-secret" not in mock.calls[0].body
    assert SYNTHETIC_KEY.encode() not in mock.calls[0].body
    assert result["action"]["rationale"] == "[REDACTED]"


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 429, 500, 503])
def test_http_errors_and_redirects_never_retry(config, request_data, status):
    mock = MockTransport({"error": "synthetic failure"}, status=status)
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=mock).diagnose(request_data)
    assert caught.value.audit["status"] == ("redirect_rejected" if status < 400 else "http_error")
    assert caught.value.audit["http_status"] == status
    assert len(mock.calls) == 1


def test_unexpected_final_url_is_rejected(config, request_data):
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=MockTransport(final_url="https://attacker.invalid")).diagnose(request_data)
    assert caught.value.audit["status"] == "redirect_rejected"


def test_default_redirect_handler_refuses_even_same_host():
    assert _NoRedirects().redirect_request(None, None, 302, "", {}, ENDPOINT) is None


def test_oversized_input_never_calls(config, request_data):
    request_data["task"]["huge"] = "x" * 65536
    mock = MockTransport()
    with pytest.raises(BackendError, match="byte limit"):
        DeepSeekBackend(config, transport=mock).diagnose(request_data)
    assert mock.calls == []


def test_nonfinite_input_never_calls(config, request_data):
    request_data["task"]["number"] = float("nan")
    mock = MockTransport()
    with pytest.raises(BackendError):
        DeepSeekBackend(config, transport=mock).diagnose(request_data)
    assert mock.calls == []


def test_oversized_response_only_retains_prefix_hash_and_count(config, request_data):
    c = replace(config, max_response_bytes=100)
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(c, transport=MockTransport(b"x" * 1000)).diagnose(request_data)
    assert caught.value.audit["response_bytes"] == 100
    assert caught.value.audit["response_truncated"] is True
    assert caught.value.audit["response"] is None
    assert caught.value.audit["response_sha256_scope"] == "retained_prefix"


def test_provider_token_bound_violation_halts_ledger(config, request_data):
    body = envelope(usage={"prompt_tokens": 100, "completion_tokens": 3000, "total_tokens": 3100})
    mock = MockTransport(body)
    backend = DeepSeekBackend(config, transport=mock)
    with pytest.raises(BackendError) as caught:
        backend.diagnose(request_data)
    assert caught.value.audit["status"] == "reservation_exceeded"
    assert caught.value.audit["budget"]["halted"] is True
    with pytest.raises(BackendError):
        backend.diagnose(request_data)
    assert len(mock.calls) == 1


def test_shared_ledger_preserves_limits(config, request_data):
    ledger = BudgetLedger(config.authorization)
    mock = MockTransport()
    for _ in range(2):
        DeepSeekBackend(config, transport=mock, ledger=ledger).diagnose(request_data)
    with pytest.raises(BackendError):
        DeepSeekBackend(config, transport=mock, ledger=ledger).diagnose(request_data)
    assert len(mock.calls) == 2


def test_persistent_ledger_survives_new_backend_instances(config, request_data, tmp_path):
    path = tmp_path / "approval-ledger.json"
    mock = MockTransport(error=TimeoutError("synthetic timeout"))
    for _ in range(2):
        with pytest.raises(BackendError):
            DeepSeekBackend(config, transport=mock, ledger=PersistentBudgetLedger(config.authorization, path)).diagnose(request_data)
    with pytest.raises(BackendError):
        DeepSeekBackend(config, transport=mock, ledger=PersistentBudgetLedger(config.authorization, path)).diagnose(request_data)
    assert len(mock.calls) == 2
    data = json.loads(path.read_text())
    assert data["attempts"] == 2
    assert Decimal(data["reserved_usd"]) == Decimal("0.0835584")
    assert SYNTHETIC_KEY not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600


def test_persistent_ledger_concurrent_atomic_reservations(config, tmp_path):
    path = tmp_path / "approval-ledger.json"
    def reserve(_):
        try:
            PersistentBudgetLedger(config.authorization, path).reserve(Decimal("0.04"), False)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(20))) == 2
    assert json.loads(path.read_text())["attempts"] == 2


def test_persistent_ledger_rejects_changed_approval(config, request_data, tmp_path):
    path = tmp_path / "approval-ledger.json"
    PersistentBudgetLedger(config.authorization, path).reserve(Decimal("0.04"), False)
    changed = replace(config, authorization=replace(config.authorization, reference="DIFFERENT-TEST-APPROVAL"))
    mock = MockTransport()
    with pytest.raises(BackendError):
        DeepSeekBackend(changed, transport=mock, ledger=PersistentBudgetLedger(changed.authorization, path)).diagnose(request_data)
    assert not mock.calls
    assert json.loads(path.read_text())["attempts"] == 1


@pytest.mark.parametrize("contents", ["", "broken", "{}", '{"schema_version":1,"attempts":0,"reserved_usd":"0"}'])
def test_corrupt_ledger_never_resets_or_calls(config, request_data, tmp_path, contents):
    path = tmp_path / "approval-ledger.json"
    path.write_text(contents)
    mock = MockTransport()
    with pytest.raises(BackendError):
        DeepSeekBackend(config, transport=mock, ledger=PersistentBudgetLedger(config.authorization, path)).diagnose(request_data)
    assert not mock.calls
    assert path.read_text() == contents


def test_symlink_ledger_is_rejected(config, request_data, tmp_path):
    actual = tmp_path / "actual.json"
    actual.write_text("untouched")
    path = tmp_path / "link.json"
    path.symlink_to(actual)
    mock = MockTransport()
    with pytest.raises(BackendError):
        DeepSeekBackend(config, transport=mock, ledger=PersistentBudgetLedger(config.authorization, path)).diagnose(request_data)
    assert not mock.calls
    assert actual.read_text() == "untouched"


def test_default_transport_builds_verified_tls_without_proxies(config, monkeypatch):
    import photonguard.backend as module
    captured = {}
    class FakeResponse:
        code = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def geturl(self): return ENDPOINT
        def read1(self, count):
            result = getattr(self, "data", b"synthetic bytes")
            self.data = b""
            return result[:count]
    class FakeOpener:
        def open(self, request, timeout):
            captured.update(request=request, timeout=timeout)
            return FakeResponse()
    def fake_build(*handlers):
        captured["handlers"] = handlers
        return FakeOpener()
    monkeypatch.setattr(module, "build_opener", fake_build)
    result = _urllib_transport(TransportRequest(ENDPOINT, b"{}", 10, 100, {"Authorization": "Bearer " + SYNTHETIC_KEY}))
    assert result.body == b"synthetic bytes"
    assert captured["timeout"] == 10
    assert captured["handlers"][0].proxies == {}
    tls = captured["handlers"][1]._context
    assert tls.check_hostname is True
    assert tls.verify_mode.name == "CERT_REQUIRED"
    assert isinstance(captured["handlers"][2], _NoRedirects)


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), True])
@pytest.mark.parametrize("persistent", [False, True])
def test_public_ledger_rejects_invalid_reservations(config, tmp_path, amount, persistent):
    ledger = PersistentBudgetLedger(config.authorization, tmp_path / "budget.json") if persistent else BudgetLedger(config.authorization)
    with pytest.raises(ValueError):
        ledger.reserve(amount, False)
    assert ledger.snapshot()["attempts"] == 0


def test_unknown_live_call_count_after_simulated_transport_failure(config, request_data, monkeypatch):
    # Intercept the default transport before constructing the backend. There is
    # NO network request; this only tests accounting of an uncertain live path.
    import photonguard.backend as module
    def synthetic_failure(_):
        raise TimeoutError("synthetic failure, no live call made by this test")
    monkeypatch.setattr(module, "_urllib_transport", synthetic_failure)
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config).diagnose(request_data)
    assert caught.value.audit["actual_llm_calls"] is None
    assert caught.value.audit["model_response_received"] is False
    assert caught.value.audit["budget"]["live_provider_attempts"] == 1


def test_corrupt_ledger_failure_keeps_audit(config, request_data, tmp_path):
    path = tmp_path / "budget.json"
    path.write_text("invalid")
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=MockTransport(), ledger=PersistentBudgetLedger(config.authorization, path)).diagnose(request_data)
    assert caught.value.audit["budget"]["status"] == "ledger_unavailable"
    assert caught.value.audit["budget_error"]
    assert caught.value.audit["actual_llm_calls"] == 0


def test_overflow_float_is_not_accepted_as_finite_json(config, request_data):
    body = envelope()
    body["choices"][0]["message"]["content"] = '{"number":1e9999}'
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=MockTransport(body)).diagnose(request_data)
    assert caught.value.audit["status"] == "invalid_response"


def test_excessive_response_nesting_is_audited(config, request_data):
    body = envelope()
    body["extra"] = json.loads("[" * 50 + "0" + "]" * 50)
    with pytest.raises(BackendError) as caught:
        DeepSeekBackend(config, transport=MockTransport(body)).diagnose(request_data)
    assert caught.value.audit["status"] == "invalid_response"


def test_unknown_secret_fields_are_redacted_in_raw_envelope(config, request_data):
    body = envelope()
    body["headers"] = {"Authorization": "private-unknown-test-value"}
    body["api_key"] = "private-unknown-test-key"
    result = DeepSeekBackend(config, transport=MockTransport(body)).diagnose(request_data)
    assert "private-unknown-test" not in json.dumps(result)
    assert result["audit"]["response"] is None
    assert 'headers' not in result["audit"]["response_json"]
    assert 'api_key' not in result["audit"]["response_json"]


def test_secret_fields_in_stringified_action_are_redacted(config, request_data):
    body = envelope()
    body["choices"][0]["message"]["content"] = json.dumps({"api_key": "private-unknown-test-key"})
    result = DeepSeekBackend(config, transport=MockTransport(body)).diagnose(request_data)
    assert "private-unknown-test-key" not in json.dumps(result)
    assert result["action"] == {"api_key": "[REDACTED]"}


def test_default_transport_preserves_bounded_http_error_body(monkeypatch):
    import io
    import photonguard.backend as module
    class FakeOpener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(ENDPOINT, 429, "synthetic fixture", {}, io.BytesIO(b'{"error":"synthetic throttling"}'))
    monkeypatch.setattr(module, "build_opener", lambda *handlers: FakeOpener())
    result = _urllib_transport(TransportRequest(ENDPOINT, b"{}", 10, 100, {}))
    assert result.status_code == 429
    assert result.body == b'{"error":"synthetic throttling"}'
