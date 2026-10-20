"""Replay the fixed synthetic CLI demo and retain local execution evidence.

Uses the selected interpreter's real Meep runtime, never a supplied Python
script or an API. Approval applies only to the bundled development fixture.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def replay(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    events = []
    fixture_paths = [ROOT / "examples/script_import/film_n2.py",
                     ROOT / "examples/film_n2/task.json"]
    fixture_hashes = {str(p.relative_to(ROOT)): sha(p) for p in fixture_paths}
    state = {"scope": "fixed synthetic development CLI replay",
             "platform": platform.platform(), "python": platform.python_version(),
             "interpreter": sys.executable, "actual_llm_calls": 0,
             "api_cost_cny": 0, "input_scripts_executed": 0,
             "human_trial_performed": False, "human_review_seconds": None,
             "human_edit_count": None, "events": events}

    def cli(label, arguments, expected=0):
        command = [sys.executable, "-B", "-m", "photonguard", *map(str, arguments)]
        started = datetime.now(timezone.utc).isoformat()
        tick = time.perf_counter()
        try:
            run = subprocess.run(command, cwd=ROOT, capture_output=True,
                                 timeout=600, check=False)
        except subprocess.TimeoutExpired as exc:
            (out / (label + ".stdout.log")).write_bytes(exc.stdout or b"")
            (out / (label + ".stderr.log")).write_bytes(exc.stderr or b"")
            events.append({"label": label, "argv": command, "started_utc": started,
                           "elapsed_seconds": time.perf_counter() - tick,
                           "returncode": None, "timed_out": True})
            write(out / "operations.json", state)
            raise RuntimeError(label + " timed out; inspect retained logs") from exc
        stdout = out / (label + ".stdout.log")
        stderr = out / (label + ".stderr.log")
        stdout.write_bytes(run.stdout)
        stderr.write_bytes(run.stderr)
        events.append({"label": label, "argv": command, "started_utc": started,
                       "elapsed_seconds": time.perf_counter() - tick,
                       "returncode": run.returncode, "expected_returncode": expected,
                       "stdout_sha256": sha(stdout), "stderr_sha256": sha(stderr)})
        write(out / "operations.json", state)
        print(label, "exit", run.returncode, flush=True)
        if run.returncode != expected:
            raise RuntimeError(f"{label}: expected exit {expected}, got {run.returncode}")
        return run.stdout.decode("utf-8")

    try:
        raw = fixture_paths[0].read_bytes()
        if raw.count(b"mp.Medium(index=n)") != 1:
            raise ValueError("Bundled source fixture changed; refuse to construct fault")
        source = out / "input.py"
        source.write_bytes(raw.replace(b"mp.Medium(index=n)", b"mp.Medium(epsilon=n)"))
        imported, intent = out / "import", out / "intent"
        cli("import", ["import-script", source, "--out", imported])
        candidate = imported / "candidate.json"
        cli("prepare", ["prepare-task", candidate, "--out", intent])
        task, lock = intent / "task.json", intent / "task.lock.json"
        task.write_bytes(fixture_paths[1].read_bytes())
        cli("confirm", ["confirm", task, "--candidate", candidate, "--lock", lock, "--approve"])
        originals = [source, imported / "script.original.py", candidate, task, lock]
        hashes = {str(p.relative_to(out)): sha(p) for p in originals}
        write(out / "original-hashes.json", hashes)
        before = json.loads(cli("run-before", ["run", task, candidate, "--lock", lock,
                                               "--out", out / "before"], expected=2))
        if before["status"] != "FAIL":
            raise ValueError("Expected synthetic material mismatch to FAIL")
        first = Path(before["evidence"])
        cli("verify-before", ["verify-evidence", first])
        patch_path = out / "patch.json"
        cli("propose", ["propose", first, "--out", patch_path])
        patch = read(patch_path)
        expected_change = [{"path": ["layers", 0, "material_value"], "old": 2, "new": 4}]
        if (patch.get("backend") != "rules_only" or patch.get("actual_llm_calls") != 0
                or patch.get("changes") != expected_change):
            raise ValueError("Unexpected proposal; synthetic approval does not cover it")
        repaired = out / "repaired.json"
        cli("apply", ["apply", task, candidate, patch_path, "--lock", lock,
                      "--out", repaired, "--approve"])
        after = json.loads(cli("run-after", ["run", task, repaired, "--lock", lock,
                                              "--out", out / "after"]))
        last = Path(after["evidence"])
        cli("verify-original-final", ["verify-evidence", first])
        cli("verify-repaired", ["verify-evidence", last])
        r0, r1 = (read(p / "report.json") for p in (first, last))
        unchanged = all(sha(p) == hashes[str(p.relative_to(out))] for p in originals)
        fixture_unchanged = all(sha(p) == fixture_hashes[str(p.relative_to(ROOT))]
                                for p in fixture_paths)
        counts = [r["resource_usage"]["fdtd_runs"] for r in (r0, r1)]
        if (r1["status"] != "PASS" or counts != [8, 8] or not unchanged
                or not fixture_unchanged or r0["task_hash"] != r1["task_hash"]
                or r0["policy_hash"] != r1["policy_hash"]):
            raise ValueError("Local checkpoint invariants failed; inspect retained evidence")
        state.update(status="VERIFIED", before_status=r0["status"], after_status=r1["status"],
                     before_evidence=str(first), after_evidence=str(last),
                     total_fdtd_runs=sum(counts), original_inputs_unchanged=unchanged,
                     bundled_fixtures_unchanged=fixture_unchanged,
                     task_hash=r0["task_hash"], policy_hash=r0["policy_hash"],
                     claim="PASS applies only to the repaired canonical recipe, fixed task and policy")
    except Exception as exc:
        state.update(status="FAILED", error=str(exc))
        write(out / "operations.json", state)
        raise
    write(out / "operations.json", state)
    print(json.dumps({k: v for k, v in state.items() if k != "events"}, indent=2))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="New output directory, never overwritten")
    parser.add_argument("--approve-synthetic-demo", action="store_true", required=True,
                        help="Approve only the bundled task and exact epsilon 2 to 4 fixture repair")
    args = parser.parse_args()
    try:
        replay(args.out)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
