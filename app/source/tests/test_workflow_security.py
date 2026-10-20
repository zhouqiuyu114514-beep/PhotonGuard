"""Offline adversarial tests for the local workflow's security boundary.

No solver/model calls are made: subprocess launch and worker run_case are mocked.
Synthetic patch evidence below is a test fixture, never a scientific run receipt.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import http.client
import hashlib
import json
import os
from pathlib import Path
import threading
from unittest.mock import Mock

import pytest

from photonguard import workflow as wf
from photonguard import workflow_worker as worker
from photonguard.agent import propose_patch
from photonguard.core import digest, load


@pytest.fixture
def store(tmp_path):
    result = wf.WorkflowStore(tmp_path / "work", allow_workers=False)
    yield result
    result.close()


@pytest.fixture
def server(tmp_path):
    result = wf.make_server(tmp_path / "http", port=0, allow_workers=False)
    thread = threading.Thread(target=result.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    yield result
    result.shutdown()
    result.server_close()
    thread.join(timeout=3)


def request(server, method="GET", path="/api/bootstrap", data=None, *, headers=None, omit=(), raw=None):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else b"")
    standard = [("Host", f"127.0.0.1:{server.server_port}")]
    if method == "POST":
        standard += [("Origin", f"http://127.0.0.1:{server.server_port}"),
                     ("X-CSRF-Token", server.store.csrf), ("Content-Type", "application/json"),
                     ("Content-Length", str(len(body)))]
    pairs = [(k, v) for k, v in standard if k.lower() not in {x.lower() for x in omit}]
    pairs += list(headers or [])
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for key, value in pairs:
            conn.putheader(key, value)
        conn.endheaders(body)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def action(store, state, kind, **extra):
    return store.action(state["id"], {"expected_revision": state["revision"], "type": kind, **extra})


def test_portable_task_summary_allows_styles_but_no_scripts_or_network(server):
    from photonguard.experiments.service import store_for
    from photonguard.experiments.task_entry import start
    from photonguard.experiments.inverse_models import GAUSSIAN
    s=start(store_for(server.store),{'teaching':True,'model':GAUSSIAN,'text':'教学任务'})['case']
    status,headers,body=request(server,path='/api/experiments/cases/'+s['id']+'/summary')
    assert status==200 and b'<style>' in body
    assert headers['Content-Security-Policy']=="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    _,headers,_=request(server,path='/experiments')
    assert "script-src 'self'" in headers['Content-Security-Policy'] and 'unsafe-inline' not in headers['Content-Security-Policy']


def prepared(store, *, confirm=False):
    state = store.create("demo")
    state = action(store, state, "context", context=state["context"])
    state = action(store, state, "task", task=state["task"])
    state = action(store, state, "import", name="fixture.py", source=state["source_text"])
    if confirm:
        state = action(store, state, "confirm", approve=True)
    return state


def proposed(store):
    state = prepared(store, confirm=True)
    internal = store._load(state["id"])
    report = {"status": "FAIL", "task_hash": digest(state["task"]),
              "candidate_hash": digest(state["candidate"]), "run_id": "synthetic-test-only"}
    internal["proposal"] = propose_patch(state["task"], state["candidate"], report)
    store._save(internal)
    return store.get(state["id"])


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "127.0.0.1:1", "0.0.0.0:1", "[::1]:1", "localhost.evil:1", "127.0.0.1@evil:1"])
def test_untrusted_host_rejected(server, host):
    assert request(server, headers=[("Host", host)], omit=["Host"])[0] == 403


def test_host_required_and_duplicate_rejected(server):
    assert request(server, omit=["Host"])[0] == 403
    assert request(server, headers=[("Host", f"127.0.0.1:{server.server_port}")])[0] in (400, 403)


@pytest.mark.parametrize("origin", ["null", "https://evil.example", "http://localhost:1", "https://127.0.0.1:1"])
def test_foreign_origin_rejected_for_reads_and_writes(server, origin):
    assert request(server, headers=[("Origin", origin)])[0] == 403
    assert request(server, "POST", "/api/cases", {"mode": "own"}, omit=["Origin"], headers=[("Origin", origin)])[0] == 403
    assert server.store.list_cases() == []


@pytest.mark.parametrize("omit,extra", [(["Origin"], []), (["X-CSRF-Token"], []), (["X-CSRF-Token"], [("X-CSRF-Token", "wrong")]), ([], [("Sec-Fetch-Site", "cross-site")])])
def test_mutation_requires_same_origin_and_csrf(server, omit, extra):
    assert request(server, "POST", "/api/cases", {"mode": "own"}, omit=omit, headers=extra)[0] == 403
    assert server.store.list_cases() == []


@pytest.mark.parametrize("name,value", [("Origin", "same"), ("Content-Length", "15"), ("X-CSRF-Token", "same"), ("Content-Type", "application/json"), ("Sec-Fetch-Site", "same-origin")])
def test_security_relevant_duplicate_headers_rejected(server, name, value):
    if name == "Origin":
        value = f"http://127.0.0.1:{server.server_port}"
    elif name == "X-CSRF-Token":
        value = server.store.csrf
    extras = [(name, value)]
    if name == "Sec-Fetch-Site":
        extras += [(name, "cross-site")]
    status, _, _ = request(server, "POST", "/api/cases", {"mode": "own"}, headers=extras)
    assert 400 <= status < 500
    assert server.store.list_cases() == []


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data", "application/json; charset=utf-8"])
def test_only_exact_json_content_type(server, content_type):
    assert request(server, "POST", "/api/cases", {"mode": "own"}, omit=["Content-Type"], headers=[("Content-Type", content_type)])[0] == 415


@pytest.mark.parametrize("length", ["0", "-1", str(wf.MAX_BODY + 1), "nonnumeric"])
def test_bad_body_lengths_rejected_without_reading_body(server, length):
    status, _, _ = request(server, "POST", "/api/cases", omit=["Content-Length"], headers=[("Content-Length", length)])
    assert 400 <= status < 500
    assert server.store.list_cases() == []


def test_transfer_encoding_and_missing_length_rejected(server):
    assert request(server, "POST", "/api/cases", {"mode": "own"}, headers=[("Transfer-Encoding", "chunked")])[0] == 400
    assert request(server, "POST", "/api/cases", {"mode": "own"}, omit=["Content-Length"])[0] == 400


@pytest.mark.parametrize("raw", [b'{"mode":"own","mode":"demo"}', b'{"mode":NaN}', b'{"mode":Infinity}', b'{"mode":-Infinity}', b'[]', b'null', b'"own"', b'{', b'\xff', b'{"mode":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'])
def test_invalid_json_rejected_without_mutation(server, raw):
    status, _, _ = request(server, "POST", "/api/cases", raw=raw)
    assert 400 <= status < 500
    assert server.store.list_cases() == []


@pytest.mark.parametrize("path", ["/../secret", "/%2e%2e/secret", "/%252e%252e/secret", "/api/cases/x%5cy", "/api/cases/%00", "/api/bootstrap?root=/etc", "http://evil.example/api/bootstrap", "/docs/../../README.md", "/api/cases/%ZZ"])
def test_arbitrary_paths_and_encoded_traversal_rejected(server, path):
    assert 400 <= request(server, path=path)[0] < 500


@pytest.mark.parametrize("extra", [{"root": "/tmp/escape"}, {"path": "../../x"}, {"command": "id"}, {"candidate": {}}, {"key": "not-a-real-key"}])
def test_create_rejects_client_paths_commands_and_extra_fields(server, extra):
    assert request(server, "POST", "/api/cases", {"mode": "own", **extra})[0] == 400
    assert server.store.list_cases() == []


def test_bootstrap_and_responses_have_no_cors_and_strict_headers(server):
    status, headers, body = request(server)
    assert status == 200
    assert json.loads(body)["ai"]["enabled"] is False
    assert json.loads(body)["ai"]["actual_llm_calls"] == 0
    assert "Access-Control-Allow-Origin" not in headers
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


def test_mode_report_stylesheet_is_served_with_the_unchanged_same_origin_csp(server):
    status, headers, body = request(server, path="/assets/mode-report.css")
    assert status == 200
    assert headers["Content-Type"] == "text/css; charset=utf-8"
    assert body == (wf.ASSETS / "mode-report.css").read_bytes()
    page_status, page_headers, _ = request(server, path="/")
    assert page_status == 200
    assert headers["Content-Security-Policy"] == page_headers["Content-Security-Policy"]
    assert "style-src 'self'" in headers["Content-Security-Policy"]
    assert "unsafe-inline" not in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "localhost", "192.168.1.1"])
def test_non_loopback_bind_refused(tmp_path, host):
    with pytest.raises(wf.WorkflowError):
        wf.make_server(tmp_path / "bad", host=host, port=0)


def test_workspace_exclusive_lock(store):
    with pytest.raises(wf.WorkflowError, match="已有"):
        wf.WorkflowStore(store.root, allow_workers=False)


@pytest.mark.parametrize("approval", [False, None, 0, 1, "true", "yes", [], {}])
def test_confirm_requires_literal_true(store, approval):
    state = prepared(store)
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=approval)
    assert store.get(state["id"])["approval"] is None
    assert not (store.root / state["id"] / "task.lock.json").exists()


@pytest.mark.parametrize("approval", [False, None, 0, 1, "true", "yes", [], {}])
def test_apply_requires_literal_true(store, approval):
    state = proposed(store)
    before = digest(state["candidate"])
    with pytest.raises(wf.WorkflowError):
        action(store, state, "apply", approve=approval)
    assert digest(store.get(state["id"])["candidate"]) == before


def test_stale_revision_and_duplicate_approval_do_not_mutate(store):
    state = prepared(store)
    current = action(store, state, "confirm", approve=True)
    files_before = {p.name: p.read_bytes() for p in (store.root / state["id"]).iterdir() if p.is_file()}
    with pytest.raises(wf.WorkflowError) as error:
        action(store, state, "confirm", approve=True)
    assert error.value.status == 409
    with pytest.raises(wf.WorkflowError):
        action(store, current, "confirm", approve=True)
    assert files_before == {p.name: p.read_bytes() for p in (store.root / state["id"]).iterdir() if p.is_file()}


def test_double_apply_changes_recipe_once_and_preserves_script(store):
    state = proposed(store)
    source_before = state["source_text"]
    current = action(store, state, "apply", approve=True)
    assert current["candidate"]["origin"]["patch_round"] == 1
    assert current["source_text"] == source_before
    assert current["candidate"]["layers"][0]["material_value"] == 4
    with pytest.raises(wf.WorkflowError):
        action(store, state, "apply", approve=True)
    with pytest.raises(wf.WorkflowError):
        action(store, current, "apply", approve=True)
    assert store.get(state["id"])["candidate"] == current["candidate"]


def test_unknowns_never_autofill_from_script_or_pause_resume(store):
    state = store.create("own")
    original = copy.deepcopy(state["task"])
    _, source, _ = wf.demo_material()
    state = action(store, state, "import", name="known.py", source=source)
    assert state["import_preview"]["status"] == "EXTRACTED"
    assert state["task"] == original
    assert state["task"]["units_um"] is None
    assert state["task"]["layers"][0]["n"] is None
    assert state["approval"] is None
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    state = action(store, state, "pause", reason="No independent source")
    assert state["stage"] == "PAUSED"
    with pytest.raises(wf.WorkflowError):
        action(store, state, "run")
    state = action(store, state, "resume")
    assert state["task"] == original
    assert state["approval"] is None


@pytest.mark.parametrize("name", ["../evil.py", "/tmp/evil.py", "a\\b.py", "x..y.py", "evil.sh", "x.py\x00"])
def test_import_file_names_are_names_not_paths(store, name):
    state = store.create("own")
    with pytest.raises(wf.WorkflowError):
        action(store, state, "import", name=name, source="import meep as mp\n")
    assert store.get(state["id"])["revision"] == state["revision"]


def test_uploaded_python_is_never_executed(store, tmp_path, monkeypatch):
    marker = tmp_path / "must-not-exist"
    popen = Mock(side_effect=AssertionError("No subprocess permitted for import"))
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    state = action(store, store.create("own"), "import", name="attack.py", source=source)
    assert state["import_preview"]["status"] == "UNSUPPORTED"
    assert state["candidate"] is None
    assert state["approval"] is None
    assert not marker.exists()
    popen.assert_not_called()


def test_unknown_control_fields_cannot_inject_candidate_or_command(store):
    state = store.create("own")
    for field, value in [("candidate_file", "../../evil.py"), ("candidate", {}), ("command", ["sh"]), ("root", "/tmp"), ("approval", True)]:
        with pytest.raises(wf.WorkflowError):
            action(store, state, "resume", **{field: value})
    assert store.get(state["id"])["revision"] == state["revision"]


def test_worker_disabled_never_fabricates_solver_results(store, monkeypatch):
    state = prepared(store, confirm=True)
    popen = Mock(side_effect=AssertionError("Disabled worker was launched"))
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    with pytest.raises(wf.WorkflowError) as error:
        action(store, state, "run")
    assert error.value.status == 503
    current = store.get(state["id"])
    assert current["runs"] == []
    assert current["job"] is None
    popen.assert_not_called()


def test_concurrent_runs_launch_at_most_one_fixed_worker(store, monkeypatch):
    first, second = prepared(store, confirm=True), prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    proc = Mock(pid=os.getpid())
    proc.poll.return_value = None
    popen = Mock(return_value=proc)
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-only-do-not-copy")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-only-do-not-copy")
    barrier = threading.Barrier(2)
    def run(state):
        barrier.wait(timeout=3)
        try:
            return action(store, state, "run")
        except wf.WorkflowError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(run, [first, second]))
    assert sum(isinstance(x, dict) for x in outputs) == 1
    assert sum(isinstance(x, wf.WorkflowError) and x.status == 409 for x in outputs) == 1
    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0][1:3] == ["-m", "photonguard.workflow_worker"]
    assert args[0][4].startswith("candidate-") and args[0][4].endswith(".json")
    assert kwargs.get("shell", False) is False
    assert kwargs["cwd"] == wf.PROJECT
    assert kwargs["close_fds"] is True
    assert kwargs["start_new_session"] is True
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]
    assert "OPENAI_API_KEY" not in kwargs["env"]
    assert "PYTHONPATH" not in kwargs["env"]
    assert all(not arg.endswith(".py") for arg in args[0])


def test_symlink_workspace_case_and_state_refused(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(wf.WorkflowError):
        wf.WorkflowStore(alias, allow_workers=False)
    ident = "a" * 32
    (store.root / ident).symlink_to(outside, target_is_directory=True)
    with pytest.raises(wf.WorkflowError):
        store.get(ident)
    state = store.create("own")
    state_file = store.root / state["id"] / "state.json"
    state_file.unlink()
    (outside / "state.json").write_text("{}")
    state_file.symlink_to(outside / "state.json")
    with pytest.raises(wf.WorkflowError):
        store.get(state["id"])


def test_symlink_server_lock_is_not_followed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "external-lock"
    outside.write_text("outside")
    (root / ".server.lock").symlink_to(outside)
    with pytest.raises(wf.WorkflowError):
        possible = wf.WorkflowStore(root, allow_workers=False)
        possible.close()
    assert outside.read_text() == "outside"


def test_malformed_task_does_not_poison_saved_case(store):
    state = prepared(store)
    malformed = copy.deepcopy(state["task"])
    malformed["layers"][0]["n"] = "not a numeric value"
    try:
        action(store, state, "task", task=malformed)
    except (wf.WorkflowError, TypeError, ValueError):
        pass
    # A rejected or unsupported draft must remain readable/editable, never brick
    # get(), bootstrap case listing, or every subsequent action.
    current = store.get(state["id"])
    assert current["approval"] is None
    assert store.list_cases()


@pytest.mark.parametrize("candidate", ["../../evil.json", "/tmp/evil.json", "evil.py", "candidate-" + "a" * 32 + ".json;id"])
def test_worker_rejects_untrusted_candidate_arguments(tmp_path, monkeypatch, candidate):
    run = Mock(side_effect=AssertionError("Unsafe input reached solver"))
    monkeypatch.setattr(worker, "run_case", run)
    job = "b" * 32
    monkeypatch.setattr(worker.sys, "argv", ["workflow_worker", str(tmp_path), candidate, job, "job-" + job + ".json"])
    with pytest.raises(ValueError):
        worker.main()
    run.assert_not_called()


@pytest.mark.parametrize("unsafe", ["candidate", "task", "lock", "artifacts"])
def test_worker_refuses_symlink_inputs_and_output(tmp_path, monkeypatch, unsafe):
    root = tmp_path / "case"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    names = {"candidate": "candidate-" + "a" * 32 + ".json", "task": "task.json", "lock": "task.lock.json", "artifacts": "artifacts"}
    for key, name in names.items():
        if key == "artifacts":
            (root / name).mkdir()
        else:
            (root / name).write_text("{}")
    target = root / names[unsafe]
    target.rmdir() if target.is_dir() else target.unlink()
    external = outside / names[unsafe]
    external.mkdir() if unsafe == "artifacts" else external.write_text("{}")
    target.symlink_to(external, target_is_directory=unsafe == "artifacts")
    run = Mock(side_effect=AssertionError("Symlink input reached solver"))
    monkeypatch.setattr(worker, "run_case", run)
    job = "b" * 32
    monkeypatch.setattr(worker.sys, "argv", ["workflow_worker", str(root), names["candidate"], job, "job-" + job + ".json"])
    try:
        worker.main()
    except (ValueError, OSError):
        pass
    run.assert_not_called()


def test_worker_does_not_overwrite_existing_receipt(tmp_path, monkeypatch):
    job = "b" * 32
    receipt = tmp_path / ("job-" + job + ".json")
    receipt.write_text('{"existing":"preserve"}')
    monkeypatch.setattr(worker, "run_case", Mock(return_value=({"status": "INCONCLUSIVE"}, tmp_path / "test-run")))
    monkeypatch.setattr(worker.sys, "argv", ["workflow_worker", str(tmp_path), "candidate-" + "a" * 32 + ".json", job, receipt.name])
    try:
        worker.main()
    except (ValueError, OSError):
        pass
    assert receipt.read_text() == '{"existing":"preserve"}'


def test_failed_durable_job_save_cannot_admit_second_worker(store, monkeypatch):
    """A storage error around launch must not allow a second concurrent solver."""
    first, second = prepared(store, confirm=True), prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    proc = Mock(pid=os.getpid())
    proc.poll.return_value = None
    popen = Mock(return_value=proc)
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    real_save = store._save
    failed = False
    def fail_first_running_save(state):
        nonlocal failed
        if not failed and state.get("job", {}).get("status") == "running":
            failed = True
            raise OSError("Synthetic disk write failure")
        return real_save(state)
    monkeypatch.setattr(store, "_save", fail_first_running_save)
    try:
        action(store, first, "run")
    except (OSError, wf.WorkflowError):
        pass
    try:
        action(store, second, "run")
    except wf.WorkflowError:
        pass
    assert popen.call_count <= 1, "A worker launched before durable admission can become invisible to concurrency guards"


def test_simultaneous_double_apply_has_one_winner(store):
    state = proposed(store)
    barrier = threading.Barrier(2)
    def apply(_):
        barrier.wait(timeout=3)
        try:
            return action(store, state, "apply", approve=True)
        except wf.WorkflowError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, range(2)))
    assert sum(isinstance(x, dict) for x in results) == 1
    assert sum(isinstance(x, wf.WorkflowError) and x.status == 409 for x in results) == 1
    assert store.get(state["id"])["candidate"]["origin"]["patch_round"] == 1


def test_failed_worker_exit_is_failure_not_pass(store, monkeypatch):
    state = prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    proc = Mock(pid=os.getpid())
    proc.poll.return_value = None
    monkeypatch.setattr(wf.subprocess, "Popen", Mock(return_value=proc))
    state = action(store, state, "run")
    proc.poll.return_value = 1
    current = store.get(state["id"])
    assert current["job"]["status"] == "failed"
    assert current["runs"] == []
    assert current["stage"] == "READY_TO_RUN"


def test_restart_keeps_live_worker_blocked_until_receipt(store, monkeypatch):
    state = prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    proc = Mock(pid=os.getpid())
    proc.poll.return_value = None
    popen = Mock(return_value=proc)
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    state = action(store, state, "run")
    # Simulate service restart while the worker PID remains alive.
    store.processes.clear()
    current = store.get(state["id"])
    assert current["job"]["status"] == "running"
    with pytest.raises(wf.WorkflowError) as exc:
        action(store, current, "run")
    assert exc.value.status == 409
    popen.assert_called_once()


def test_missing_worker_after_restart_becomes_failed_without_autorun(store, monkeypatch):
    state = prepared(store, confirm=True)
    internal = store._load(state["id"])
    internal["job"] = {"id": "b" * 32, "status": "running", "receipt": "job-" + "b" * 32 + ".json", "pid": 2**30}
    store._save(internal)
    kill = Mock(side_effect=ProcessLookupError)
    popen = Mock(side_effect=AssertionError("Recovery must not automatically rerun"))
    monkeypatch.setattr(wf.os, "kill", kill)
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    current = store.get(state["id"])
    assert current["job"]["status"] == "failed"
    assert current["runs"] == []
    popen.assert_not_called()


def test_wrong_identity_receipt_does_not_become_completion(store):
    state = prepared(store, confirm=True)
    internal = store._load(state["id"])
    job = "b" * 32
    internal["job"] = {"id": job, "status": "running", "receipt": "job-" + job + ".json", "pid": os.getpid()}
    store._save(internal)
    wf.write_once(store.root / state["id"] / internal["job"]["receipt"], {"job_id": "c" * 32, "status": "completed", "run_id": "invented"})
    with pytest.raises(wf.WorkflowError):
        store.get(state["id"])
    assert store._load(state["id"])["runs"] == []


def test_symlink_artifacts_not_used_as_evidence(store, tmp_path):
    state = store.create("own")
    outside = tmp_path / "outside-artifacts"
    outside.mkdir()
    (store.root / state["id"] / "artifacts").symlink_to(outside, target_is_directory=True)
    with pytest.raises((wf.WorkflowError, ValueError)):
        store.evidence(state["id"], "anything")


def test_completed_receipt_without_verified_evidence_cannot_make_pass(store):
    state = prepared(store, confirm=True)
    internal = store._load(state["id"])
    job = "b" * 32
    run = "synthetic-incomplete-evidence"
    internal["job"] = {"id": job, "status": "running", "receipt": "job-" + job + ".json", "pid": os.getpid()}
    store._save(internal)
    (store.root / state["id"] / "artifacts" / run).mkdir(parents=True)
    wf.write_once(store.root / state["id"] / internal["job"]["receipt"], {"job_id": job, "status": "completed", "run_id": run, "verification_status": "PASS"})
    current = store.get(state["id"])
    assert current["job"]["status"] == "failed"
    assert current["runs"] == []


@pytest.mark.parametrize("size", [wf.MAX_BYTES + 1, wf.MAX_BYTES * 2])
def test_source_size_rejected_before_import(store, size, monkeypatch):
    state = store.create("own")
    parser = Mock(side_effect=AssertionError("Oversized source reached parser"))
    monkeypatch.setattr(wf, "preview_bytes", parser)
    with pytest.raises(wf.WorkflowError) as error:
        action(store, state, "import", source="x" * size, name="oversized.py")
    assert error.value.status == 413
    parser.assert_not_called()
    assert store.get(state["id"])["source_text"] == ""


@pytest.mark.parametrize("extra", [{"model": "anything"}, {"backend": "deepseek"}, {"api_key": "synthetic-not-a-real-key"}, {"max_fdtd_runs": 100}, {"shell": True}])
def test_run_cannot_expand_budget_or_enable_model(store, extra):
    state = prepared(store, confirm=True)
    with pytest.raises(wf.WorkflowError) as error:
        action(store, state, "run", **extra)
    assert error.value.status == 400
    assert store.get(state["id"])["job"] is None


@pytest.mark.parametrize("revision", [True, False, "1", 1.0, None, -1])
def test_revision_requires_exact_current_integer(store, revision):
    state = store.create("own")
    with pytest.raises(wf.WorkflowError) as error:
        store.action(state["id"], {"type": "resume", "expected_revision": revision})
    assert error.value.status == 409
    assert store.get(state["id"])["revision"] == state["revision"]


def test_incompatible_script_spectrum_blocks_confirmation_without_autofill(store):
    state = prepared(store)
    changed = copy.deepcopy(state["task"])
    changed["nfreq"] = 43
    state = action(store, state, "task", task=changed)
    assert state["task"]["nfreq"] == 43
    assert state["readiness"]["provenance_problem"]
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    assert not (store.root / state["id"] / "task.lock.json").exists()


def test_material_discrepancy_is_preserved_separately_from_intent(store):
    state = prepared(store, confirm=True)
    assert state["task"]["layers"][0]["n"] == 2
    assert state["candidate"]["layers"][0]["material_kind"] == "epsilon"
    assert state["candidate"]["layers"][0]["material_value"] == 2
    assert any(row["field"] == "第1层 折射率 n" and row["match"] is False for row in state["comparison"])
    assert state["approval"] is not None
    assert state["runs"] == []


@pytest.mark.parametrize("kind", ["context", "task", "import"])
def test_locked_task_rejects_edit_without_overwriting_evidence(store, kind):
    state = prepared(store, confirm=True)
    locked = (store.root / state["id"] / "task.lock.json").read_bytes()
    extra = {"context": {"context": state["context"]}, "task": {"task": state["task"]}, "import": {"source": state["source_text"], "name": "again.py"}}[kind]
    with pytest.raises(wf.WorkflowError) as error:
        action(store, state, kind, **extra)
    assert error.value.status == 409
    assert (store.root / state["id"] / "task.lock.json").read_bytes() == locked
    assert store.get(state["id"])["revision"] == state["revision"]


def test_tampered_lock_blocks_apply(store):
    state = proposed(store)
    lock_path = store.root / state["id"] / "task.lock.json"
    record = load(lock_path)
    record["task_sha256"] = "0" * 64
    lock_path.write_text(json.dumps(record))
    with pytest.raises(wf.WorkflowError):
        action(store, state, "apply", approve=True)
    assert store.get(state["id"])["candidate"] == state["candidate"]


def test_oversized_task_rejected_without_snapshot(store):
    state = store.create("own")
    draft = copy.deepcopy(state["task"])
    draft["intent_note"] = "x" * 65537
    files_before = set((store.root / state["id"]).iterdir())
    with pytest.raises(wf.WorkflowError):
        action(store, state, "task", task=draft)
    assert set((store.root / state["id"]).iterdir()) == files_before
    assert store.get(state["id"])["task"] == state["task"]


def test_nested_duplicate_json_keys_rejected_before_action(server):
    state = server.store.create("own")
    raw = ('{"type":"context","expected_revision":' + str(state["revision"]) + ',"context":{"goal":"one","goal":"two"}}').encode()
    status, _, _ = request(server, "POST", f'/api/cases/{state["id"]}/action', raw=raw)
    assert status == 400
    assert server.store.get(state["id"])["revision"] == state["revision"]


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS"])
def test_unsupported_mutation_methods_have_no_effect(server, method):
    assert request(server, method=method, path="/api/cases")[0] == 405
    assert server.store.list_cases() == []


def test_cross_case_evidence_path_without_membership_not_exposed(server):
    first, second = server.store.create("own"), server.store.create("own")
    for case in (first, second):
        for suffix in ("spectrum", "files", "files/report.json"):
            assert request(server, path=f'/api/cases/{case["id"]}/runs/unrecorded/{suffix}')[0] == 404
        assert request(server, path=f'/reports/{case["id"]}/unrecorded')[0] == 404


@pytest.mark.parametrize("marker", ["不知道", "我不知道。", "暂时不知道", "不清楚！", "不确定", "待确认", "unknown", " UNKNOWN. ", "资料没有", "资料里没有", "没有"])
def test_natural_unknown_context_markers_block_confirmation(store, marker):
    state = prepared(store)
    context = dict(state["context"], role=marker)
    state = action(store, state, "context", context=context)
    assert "context.role" in state["missing"]
    assert state["stage"] == "CONTEXT_NEEDED"
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    assert not (store.root / state["id"] / "task.lock.json").exists()


def test_explicit_unknown_metadata_survives_and_blocks_without_deleting_text(store):
    state = prepared(store)
    original_context = state["context"].copy()
    original_task = copy.deepcopy(state["task"])
    state = action(store, state, "context", context=original_context, unknown_fields=["goal", "role", "role"])
    assert state["context_unknown_fields"] == ["goal", "role"]
    assert state["context"] == original_context
    assert state["task"] == original_task
    assert {"context.goal", "context.role"}.issubset(set(state["missing"]))
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    state = action(store, state, "pause", reason="Need source")
    state = action(store, state, "resume")
    assert state["context_unknown_fields"] == ["goal", "role"]
    assert state["approval"] is None
    state = action(store, state, "context", context=original_context, unknown_fields=[])
    assert "context.role" not in state["missing"]


@pytest.mark.parametrize("unknown_fields", ["role", None, {}, ["../../path"], ["candidate"], [1], [None], [{}]])
def test_unknown_metadata_only_accepts_known_context_names(store, unknown_fields):
    state = store.create("own")
    with pytest.raises(wf.WorkflowError):
        action(store, state, "context", context=state["context"], unknown_fields=unknown_fields)
    assert store.get(state["id"])["revision"] == state["revision"]


@pytest.mark.parametrize("field,value", [("dimensions", 2), ("angle_deg", 30), ("lossless", False), ("dispersive", True), ("n_exit", 1.5), ("units_um", .001)])
def test_explicit_out_of_scope_is_reported_before_other_unknowns(store, field, value):
    state = store.create("own")
    draft = copy.deepcopy(state["task"])
    if field == "units_um":
        draft[field] = value
    else:
        draft["physics"][field] = value
    state = action(store, state, "task", task=draft)
    assert state["missing"]
    assert state["stage"] == "UNSUPPORTED"
    assert state["readiness"]["explicit_scope_problem"]
    assert state["task"] == draft
    assert state["approval"] is None
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)


def test_storage_low_free_space_blocks_create_without_case_directory(store, monkeypatch):
    monkeypatch.setattr(wf.shutil, "disk_usage", lambda _: Mock(free=15 * 1024 ** 2))
    before = set(store.root.iterdir())
    with pytest.raises(wf.WorkflowError) as exc:
        store.create("own")
    assert exc.value.status == 507
    assert set(store.root.iterdir()) == before


def test_storage_logical_one_gib_cap_blocks_without_deleting_evidence(store):
    # Sparse synthetic file: records a logical size without writing 1 GiB.
    sentinel = store.root / "budget-test.bin"
    with sentinel.open("wb") as stream:
        stream.truncate(1024 ** 3)
    with pytest.raises(wf.WorkflowError) as exc:
        store.create("own")
    assert exc.value.status == 507
    assert sentinel.stat().st_size == 1024 ** 3


def test_storage_low_free_space_blocks_edit_without_changing_state(store, monkeypatch):
    state = store.create("own")
    original = (store.root / state["id"] / "state.json").read_bytes()
    monkeypatch.setattr(wf.shutil, "disk_usage", lambda _: Mock(free=0))
    with pytest.raises(wf.WorkflowError) as exc:
        action(store, state, "context", context=state["context"])
    assert exc.value.status == 507
    assert (store.root / state["id"] / "state.json").read_bytes() == original


def test_solver_storage_reservation_blocks_launch_when_under_192_mib_free(store, monkeypatch):
    state = prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    popen = Mock(side_effect=AssertionError("Not enough reserved storage for solver"))
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    monkeypatch.setattr(wf.shutil, "disk_usage", lambda _: Mock(free=191 * 1024 ** 2))
    with pytest.raises(wf.WorkflowError) as exc:
        action(store, state, "run")
    assert exc.value.status == 507
    assert store.get(state["id"])["job"] is None
    popen.assert_not_called()


def test_every_accepted_connection_has_five_second_timeout(server, monkeypatch):
    observed = []
    original_setup = wf.WorkflowHandler.setup
    def tracked_setup(handler):
        original_setup(handler)
        observed.append(handler.connection.gettimeout())
    monkeypatch.setattr(wf.WorkflowHandler, "setup", tracked_setup)
    assert request(server)[0] == 200
    assert observed == [5.0]


def test_postlaunch_save_failure_preserves_reservation_and_started_pid_recovery(store, monkeypatch):
    first, second = prepared(store, confirm=True), prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    proc = Mock(pid=os.getpid())
    proc.poll.return_value = None
    def launch(argv, **kwargs):
        root, _, job = argv[3:6]
        wf.write_once(Path(root) / ("started-" + job + ".json"), {"job_id": job, "pid": proc.pid})
        return proc
    popen = Mock(side_effect=launch)
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    real_save = store._save
    def fail_postlaunch_save(state):
        if state.get("job") and state["job"].get("pid"):
            raise OSError("Synthetic postlaunch disk error")
        return real_save(state)
    monkeypatch.setattr(store, "_save", fail_postlaunch_save)
    with pytest.raises(OSError):
        action(store, first, "run")
    durable = store._load(first["id"])
    assert durable["job"]["status"] == "running"
    assert durable["job"]["pid"] is None
    store.processes.clear()
    current = store.get(first["id"])
    assert current["job"]["pid"] == proc.pid
    assert current["job"]["status"] == "running"
    with pytest.raises(wf.WorkflowError):
        action(store, second, "run")
    popen.assert_called_once()


def test_reservation_without_started_marker_stays_blocked(store, monkeypatch):
    state = prepared(store, confirm=True)
    internal = store._load(state["id"])
    job = "b" * 32
    internal["job"] = {"id": job, "status": "running", "receipt": "job-" + job + ".json", "pid": None}
    store._save(internal)
    popen = Mock(side_effect=AssertionError("Unknown launch status must not retry"))
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    current = store.get(state["id"])
    assert current["job"]["status"] == "running"
    assert current["job"]["recovery_note"]
    with pytest.raises(wf.WorkflowError):
        action(store, current, "run")
    popen.assert_not_called()


def test_worker_writes_started_marker_before_solver_and_exclusive_receipt(tmp_path, monkeypatch):
    job = "b" * 32
    receipt = "job-" + job + ".json"
    def synthetic_run(*args):
        marker = load(tmp_path / ("started-" + job + ".json"))
        assert marker == {"job_id": job, "pid": os.getpid()}
        return {"status": "INCONCLUSIVE"}, tmp_path / "synthetic-test-only"
    run = Mock(side_effect=synthetic_run)
    monkeypatch.setattr(worker, "run_case", run)
    monkeypatch.setattr(worker.sys, "argv", ["workflow_worker", str(tmp_path), "candidate-" + "a" * 32 + ".json", job, receipt])
    worker.main()
    run.assert_called_once()
    result = load(tmp_path / receipt)
    assert result["job_id"] == job
    assert result["status"] == "completed"
    assert result["verification_status"] == "INCONCLUSIVE"
    saved = (tmp_path / receipt).read_bytes()
    with pytest.raises(FileExistsError):
        worker.main()
    assert (tmp_path / receipt).read_bytes() == saved
    run.assert_called_once()


def test_worker_failure_receipt_does_not_disclose_exception_content(tmp_path, monkeypatch):
    job = "b" * 32
    receipt = "job-" + job + ".json"
    run = Mock(side_effect=RuntimeError("synthetic-private-content-never-return"))
    monkeypatch.setattr(worker, "run_case", run)
    monkeypatch.setattr(worker.sys, "argv", ["workflow_worker", str(tmp_path), "candidate-" + "a" * 32 + ".json", job, receipt])
    worker.main()
    result = load(tmp_path / receipt)
    assert result["status"] == "failed"
    assert "RuntimeError" in result["error"]
    assert "synthetic-private-content-never-return" not in result["error"]


@pytest.mark.parametrize("reference", [None, "", "   ", "不知道", "待确认。", "UNKNOWN", "资料没有"])
def test_incomplete_source_reference_saves_and_pauses_without_losing_note(store, reference):
    state = prepared(store)
    draft = copy.deepcopy(state["task"])
    draft["sources"] = [{"kind": "partially entered independent source", "reference": reference,
                         "note": "Remember the draft note and its measured-material context"}]
    state = action(store, state, "task", task=draft)
    assert state["task"]["sources"] == draft["sources"]
    assert "sources.0.reference" in state["missing"]
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    assert not (store.root / state["id"] / "task.lock.json").exists()
    state = action(store, state, "pause", reason="Source reference is not available yet")
    assert state["stage"] == "PAUSED"
    assert store.get(state["id"])["task"]["sources"] == draft["sources"]
    state = action(store, state, "resume")
    assert state["task"]["sources"] == draft["sources"]
    assert "sources.0.reference" in state["missing"]
    assert state["stage"] == "TASK_REVIEW", "A missing source reference must return to task review rather than offer confirmation"
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    completed = copy.deepcopy(state["task"])
    completed["sources"][0]["reference"] = "Independent supplied task card, section 2"
    state = action(store, state, "task", task=completed)
    assert "sources.0.reference" not in state["missing"]
    assert state["task"]["sources"][0]["note"] == draft["sources"][0]["note"]
    assert state["stage"] == "CONFIRM_TASK"
    state = action(store, state, "confirm", approve=True)
    assert state["approval"] is not None
    assert state["stage"] == "READY_TO_RUN"


def test_source_entry_without_reference_key_preserves_note_and_blocks_approval(store):
    state = prepared(store)
    draft = copy.deepcopy(state["task"])
    draft["sources"] = [{"note": "Partial source note with reference not typed yet"}]
    state = action(store, state, "task", task=draft)
    assert state["task"]["sources"] == draft["sources"]
    assert "sources.0.reference" in state["missing"]
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    assert state["approval"] is None


@pytest.mark.parametrize("reference", [0, True, [], {}])
def test_source_reference_malformed_type_rejected_but_original_draft_retained(store, reference):
    state = prepared(store)
    draft = copy.deepcopy(state["task"])
    draft["sources"] = [{"reference": reference, "note": "preserve original draft on invalid input"}]
    with pytest.raises(wf.WorkflowError):
        action(store, state, "task", task=draft)
    assert store.get(state["id"])["task"] == state["task"]


def test_any_incomplete_source_blocks_even_when_another_reference_is_valid(store):
    state = prepared(store)
    draft = copy.deepcopy(state["task"])
    draft["sources"].append({"reference": None, "note": "Unfinished second source"})
    state = action(store, state, "task", task=draft)
    assert "sources.1.reference" in state["missing"]
    assert "sources.0.reference" not in state["missing"]
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    assert state["approval"] is None


def test_no_safe_proposal_preserves_fail_and_routes_to_report(store, monkeypatch):
    state = prepared(store, confirm=True)
    internal = store._load(state["id"])
    recorded = {"run_id": "synthetic-test-only-no-safe-patch", "status": "FAIL", "candidate_hash": digest(state["candidate"])}
    internal["runs"] = [recorded]
    store._save(internal)
    state = store.get(state["id"])
    assert state["stage"] == "DIAGNOSIS"
    evidence = Mock()
    evidence.report.return_value = {"status": "FAIL", "run_id": recorded["run_id"]}
    monkeypatch.setattr(store, "evidence", Mock(return_value=evidence))
    monkeypatch.setattr(wf, "verify_evidence", Mock(return_value=True))
    proposer = Mock(return_value=None)
    monkeypatch.setattr(wf, "propose_patch", proposer)
    state = action(store, state, "propose")
    assert state["proposal"] is None
    assert state["diagnosis_blocker"]
    assert state["runs"] == [recorded]
    assert state["stage"] == "REVIEW_NEEDED"
    assert state["next_action"]["kind"] == "report"
    current = store.get(state["id"])
    assert current["diagnosis_blocker"] == state["diagnosis_blocker"]
    assert current["stage"] == "REVIEW_NEEDED"
    with pytest.raises(wf.WorkflowError):
        action(store, current, "apply", approve=True)
    proposer.assert_called_once()


def test_failed_launches_count_towards_six_attempt_cap(store, monkeypatch):
    state = prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    popen = Mock(side_effect=OSError("Synthetic launch failure"))
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    for attempt in range(1, 7):
        state = action(store, state, "run")
        assert state["job"]["status"] == "failed"
        assert state["job_attempts"] == attempt
        assert state["runs"] == []
    with pytest.raises(wf.WorkflowError) as exc:
        action(store, state, "run")
    assert exc.value.status == 409
    assert popen.call_count == 6
    assert store.get(state["id"])["job_attempts"] == 6
    assert store.get(state["id"])["stage"] == "REVIEW_NEEDED"
    assert store.get(state["id"])["next_action"]["kind"] == "report"


def test_exited_workers_count_towards_six_attempt_cap(store, monkeypatch):
    state = prepared(store, confirm=True)
    store.allow_workers = store.meep_available = True
    proc = Mock(pid=os.getpid())
    proc.poll.return_value = 1
    popen = Mock(return_value=proc)
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    for attempt in range(1, 7):
        state = action(store, state, "run")
        state = store.get(state["id"])
        assert state["job"]["status"] == "failed"
        assert state["job_attempts"] == attempt
        assert state["runs"] == []
    with pytest.raises(wf.WorkflowError) as exc:
        action(store, state, "run")
    assert exc.value.status == 409
    assert popen.call_count == 6


def test_unsupported_ast_routes_to_unsupported_without_partial_recipe(store, monkeypatch):
    state = prepared(store)
    task = copy.deepcopy(state["task"])
    popen = Mock(side_effect=AssertionError("Unsupported source cannot execute"))
    monkeypatch.setattr(wf.subprocess, "Popen", popen)
    state = action(store, state, "import", name="unsupported.py", source="import meep as mp\nwhile True:\n    pass\n")
    assert state["import_preview"]["status"] == "UNSUPPORTED"
    assert state["stage"] == "UNSUPPORTED"
    assert state["next_action"]["kind"] == "unsupported"
    assert state["candidate"] is None
    assert state["task"] == task
    assert state["approval"] is None
    with pytest.raises(wf.WorkflowError):
        action(store, state, "confirm", approve=True)
    state = action(store, state, "pause", reason="Keep unsupported source for review")
    state = action(store, state, "resume")
    assert state["stage"] == "UNSUPPORTED"
    popen.assert_not_called()


def recorded_synthetic_spectrum(server, raw):
    """Create local parser-only evidence fixture, without a scientific PASS claim."""
    state = server.store.create("own")
    run_id = "synthetic-spectrum-parser-test"
    internal = server.store._load(state["id"])
    internal["runs"] = [{"run_id": run_id}]
    server.store._save(internal)
    run_dir = server.store.root / state["id"] / "artifacts" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "spectrum.csv").write_bytes(raw)
    wf.write_once(run_dir / "manifest.json", {"schema_version": 1, "algorithm": "sha256", "run_id": run_id,
                                               "files": {"spectrum.csv": hashlib.sha256(raw).hexdigest()}})
    return f'/api/cases/{state["id"]}/runs/{run_id}', run_dir


def test_spectrum_api_returns_finite_numbers_and_preserves_raw_csv(server):
    raw = b"frequency,wavelength_um,R,T,R_reference,T_reference\r\n0.5,2,0.2,0.8,0.21,0.79\r\n1,1,1e-3,0.999,0.002,0.998\r\n"
    base, run_dir = recorded_synthetic_spectrum(server, raw)
    status, _, body = request(server, path=base + "/spectrum")
    assert status == 200
    payload = json.loads(body)
    assert payload["source"] == "spectrum.csv"
    assert payload["transformation"] == "finite CSV numeric parsing only"
    assert payload["spectrum"] == [
        {"frequency": .5, "wavelength_um": 2., "R": .2, "T": .8, "R_reference": .21, "T_reference": .79},
        {"frequency": 1., "wavelength_um": 1., "R": .001, "T": .999, "R_reference": .002, "T_reference": .998},
    ]
    assert all(type(value) in (int, float) for row in payload["spectrum"] for value in row.values())
    assert (run_dir / "spectrum.csv").read_bytes() == raw
    status, headers, downloaded = request(server, path=base + "/files/spectrum.csv")
    assert status == 200
    assert downloaded == raw
    assert "attachment" in headers["Content-Disposition"]


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", "1e999", "", "not-a-number", "<script>alert(1)</script>"])
def test_spectrum_api_rejects_nonfinite_or_malformed_numeric_values(server, invalid):
    raw = ("frequency,wavelength_um,R,T,R_reference,T_reference\n.5,2," + invalid + ",.8,.2,.8\n").encode()
    base, run_dir = recorded_synthetic_spectrum(server, raw)
    status, _, body = request(server, path=base + "/spectrum")
    assert status == 422
    assert "spectrum" not in json.loads(body)
    assert (run_dir / "spectrum.csv").read_bytes() == raw


def test_spectrum_api_missing_required_column_is_controlled_rejection(server):
    raw = b"frequency,wavelength_um,R,T,R_reference\n.5,2,.2,.8,.2\n"
    base, _ = recorded_synthetic_spectrum(server, raw)
    assert request(server, path=base + "/spectrum")[0] == 422


def test_empty_spectrum_api_is_empty_data_not_fabricated_curve(server):
    raw = b"frequency,wavelength_um,R,T,R_reference,T_reference\n"
    base, _ = recorded_synthetic_spectrum(server, raw)
    status, _, body = request(server, path=base + "/spectrum")
    assert status == 200
    assert json.loads(body)["spectrum"] == []


def test_spectrum_or_evidence_changed_after_completion_is_not_served_as_verified(server):
    raw = b"frequency,wavelength_um,R,T,R_reference,T_reference\n.5,2,.2,.8,.2,.8\n"
    base, run_dir = recorded_synthetic_spectrum(server, raw)
    assert request(server, path=base + "/spectrum")[0] == 200
    (run_dir / "spectrum.csv").write_bytes(raw.replace(b".2,.8", b".1,.9"))
    for suffix in ("/spectrum", "/files", "/files/spectrum.csv"):
        assert request(server, path=base + suffix)[0] == 409
