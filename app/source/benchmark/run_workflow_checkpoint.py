"""Synthetic integration checkpoint through the actual local HTTP API.

Not a browser/UI test, blind benchmark, real-user approval, or AI evaluation.
This developer harness explicitly approves only the included synthetic demo.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import http.client
import json
from pathlib import Path
import threading
import time
import uuid
from photonguard.workflow import make_server
from photonguard.runner import verify_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="workflow-verification")
    args = parser.parse_args()
    out = Path(args.out).resolve() / ("http-checkpoint-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    server = make_server(out / "data", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    events = []
    csrf = ""

    def request(path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        headers = {"Origin": origin, "X-CSRF-Token": csrf, "Content-Type": "application/json"} if body else {}
        connection.request("POST" if body else "GET", path, body, headers)
        response = connection.getresponse()
        raw = response.read()
        code = response.status
        connection.close()
        if code >= 400:
            raise AssertionError((path, code, raw.decode()))
        return raw if not response.getheader("Content-Type", "").startswith("application/json") else json.loads(raw)

    try:
        bootstrap = request("/api/bootstrap")
        csrf = bootstrap["csrf"]
        assert bootstrap["runtime"]["meep_available"]
        assert bootstrap["ai"]["enabled"] is False
        for path in ("/", "/assets/app.js", "/assets/style.css"):
            raw = request(path)
            assert len(raw) > 100
            events.append({"asset": path, "bytes": len(raw), "http": "200"})
        state = request("/api/cases", {"mode": "demo"})
        ident = state["id"]

        def action(kind, **fields):
            nonlocal state
            state = request(f"/api/cases/{ident}/action", {"type": kind, "expected_revision": state["revision"], **fields})
            events.append({"action": kind, "stage": state["stage"], "revision": state["revision"]})
            print(kind, state["stage"], flush=True)

        action("context", context=state["context"])
        action("task", task=state["task"])
        action("import", source=state["source_text"], name="synthetic-demo.py")
        assert state["approval"] is None
        action("confirm", approve=True)
        task_hash = state["approval"]["task_sha256"]
        for phase in ("original", "repaired"):
            action("run")
            while state["job"]["status"] == "running":
                time.sleep(.5)
                state = request(f"/api/cases/{ident}")
            assert state["job"]["status"] == "completed", state["job"]
            run = state["runs"][-1]
            assert run["status"] == ("FAIL" if phase == "original" else "PASS"), run
            assert run["fdtd_runs"] == 8 and run["solver_kind"] == "REAL_MEEP"
            assert run["task_hash"] == task_hash
            assert verify_evidence(out / "data" / ident / "artifacts" / run["run_id"])
            spectrum = request(run["spectrum_url"])["spectrum"]
            assert len(spectrum) == 41
            assert all(type(v) in (int, float) for row in spectrum for v in row.values())
            assert b"DOCTYPE" in request(run["report_url"]).upper()
            csv = request(f'/api/cases/{ident}/runs/{run["run_id"]}/files/spectrum.csv')
            assert len(csv.splitlines()) == 42
            events.append({"phase": phase, "run_id": run["run_id"], "status": run["status"], "fdtd_runs": 8, "points": 41, "evidence_verified": True})
            if phase == "original":
                action("propose")
                assert state["proposal"]["changes"] == [{"path": ["layers", 0, "material_value"], "old": 2.0, "new": 4.0}]
                action("apply", approve=True)
        result = {"kind": "synthetic-developer-HTTP-checkpoint", "not_browser_test": True,
                  "not_user_approval": True, "actual_llm_calls": 0, "fdtd_runs": 16,
                  "result": "PASS", "events": events, "state": state}
        (out / "checkpoint.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"status": "PASS", "output": str(out), "fdtd_runs": 16, "actual_llm_calls": 0}), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
