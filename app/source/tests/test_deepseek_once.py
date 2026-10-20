"""Credential prompt/authentication gates. No live network or paid calls."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import socket

import pytest

from photonguard.core import digest

spec = importlib.util.spec_from_file_location("once_script", Path(__file__).parents[1] / "tools/run_deepseek_once.py")
once = importlib.util.module_from_spec(spec)
spec.loader.exec_module(once)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*a, **k): pytest.fail("No live network in credential tests")
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def session(tmp_path, monkeypatch):
    folder = tmp_path / "session"
    folder.mkdir()
    monkeypatch.setattr(once, "ROOT", tmp_path)
    monkeypatch.setattr(once, "SESSION", folder)
    monkeypatch.setattr(once, "LEDGER", tmp_path / "budget.ledger.json")
    request = {"prepared": "offline-test"}
    stamp = datetime.now(timezone.utc).isoformat()
    plan = {"authorization": {"approved": True, "reference": "OFFLINE-ONLY",
            "model": "deepseek-flash", "total_budget_usd": "0.042", "max_calls": 1,
            "rates": {"input_usd_per_million": "0.30", "output_usd_per_million": "1.20",
                      "checked_at": stamp, "source": "https://api-docs.deepseek.com/quick_start/pricing/"}},
            "cny_approval": {"total_budget_cny": "0.28", "input_cny_per_million": "2",
                             "output_cny_per_million": "8", "checked_at": stamp,
                             "source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"},
            "limits": {}, "evidence": "fixture", "diagnostic_request_sha256": digest(request)}
    (folder / "plan.json").write_text(json.dumps(plan))
    (folder / "diagnostic-request.json").write_text(json.dumps(request))
    monkeypatch.setattr(once, "verify_evidence", lambda p: True)
    monkeypatch.setattr(once, "interactive_terminal", lambda: True)
    return folder


def test_failed_free_auth_never_dispatches_or_reserves_and_key_not_saved(session, monkeypatch, capsys):
    key = "sk-OFFLINE-NOT-A-REAL-KEY"
    monkeypatch.setattr(once.getpass, "getpass", lambda p: key)
    monkeypatch.setattr(once, "authenticate", lambda k, m: {"authenticated": False, "http_status": 401})
    monkeypatch.setattr(once, "DeepSeekBackend", lambda *a, **k: pytest.fail("Paid dispatch forbidden"))
    assert once.run() == 3
    assert not once.LEDGER.exists()
    assert json.loads((session / "summary.json").read_text())["generation_requests"] == 0
    assert key not in "".join(p.read_text() for p in session.iterdir())
    assert key not in capsys.readouterr().out


def test_noninteractive_prompt_never_reads_credential(session, monkeypatch):
    monkeypatch.setattr(once, "interactive_terminal", lambda: False)
    monkeypatch.setattr(once.getpass, "getpass", lambda p: pytest.fail("Credential must not be read"))
    with pytest.raises(ValueError, match="interactive"): once.run()


def test_finished_session_blocks_before_secret_read(session, monkeypatch):
    (session / "summary.json").write_text("{}")
    monkeypatch.setattr(once.getpass, "getpass", lambda p: pytest.fail("No second prompt"))
    with pytest.raises(ValueError, match="finished"): once.run()


def test_tampered_request_blocks_before_secret_read(session, monkeypatch):
    (session / "diagnostic-request.json").write_text('{"changed":true}')
    monkeypatch.setattr(once.getpass, "getpass", lambda p: pytest.fail("No prompt"))
    with pytest.raises(ValueError, match="changed"): once.run()


def test_auth_requires_model_availability_and_does_not_store_headers(monkeypatch):
    key = "sk-OFFLINE-NOT-A-REAL-KEY"
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return "https://api.deepseek.com/models"
        def read(self, size): return json.dumps({"data": [{"id": "other-model"}, {"id": key}]}).encode()
    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            assert request.full_url == "https://api.deepseek.com/models"
            return Response()
    monkeypatch.setattr(once, "build_opener", lambda *a: Opener())
    result = once.authenticate(key, "deepseek-flash")
    assert result["authenticated"] is False
    assert key not in json.dumps(result)
    assert result["generation_requests"] == 0
