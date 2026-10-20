"""Record actual automated executions, not human effort or model performance.
SPDX-License-Identifier: GPL-2.0-or-later
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 -B run_local_proof.py NEW_OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=False)
    before = {str(p.relative_to(HERE)): sha(p) for p in sorted(HERE.rglob("*"))
              if p.is_file() and out not in p.parents and "__pycache__" not in p.parts}
    events = []
    for name in ("complete", "needs-clarification"):
        bundle = HERE / "fixtures" / (name + ".bundle.json")
        proposal = HERE / "fixtures" / (name + ".mock.json")
        command = [sys.executable, "-B", str(HERE / "intent_pilot.py"), str(bundle), str(proposal)]
        started = datetime.now(timezone.utc).isoformat()
        tick = time.perf_counter()
        run = subprocess.run(command, capture_output=True, text=True, check=False, timeout=15)
        elapsed = time.perf_counter() - tick
        if run.returncode:
            raise RuntimeError(run.stderr)
        result = json.loads(run.stdout)
        write(out / (name + ".review.json"), result)
        events.append({"event": "automated_cli_review", "fixture": name,
                       "started_utc": started, "argv": command, "returncode": run.returncode,
                       "automated_elapsed_seconds": elapsed,
                       "bundle_file_sha256": sha(bundle), "mock_file_sha256": sha(proposal),
                       "output_file_sha256": sha(out / (name + ".review.json")),
                       "status": result["status"], "proposed_fields": sum(
                           f["state"] == "proposed" for f in result["fields"]),
                       "potential_review_field_count": len(result["fields"]),
                       "question_count": len(result["questions"]),
                       "human_subjects": 0, "human_edit_count": None, "human_review_seconds": None,
                       "model_calls": 0, "solver_calls": 0, "api_cost_cny": 0})
    command = [sys.executable, "-B", "-m", "unittest", "-v", "test_intent_pilot"]
    tick = time.perf_counter()
    run = subprocess.run(command, cwd=HERE, capture_output=True, text=True, check=False, timeout=30)
    elapsed = time.perf_counter() - tick
    with (out / "tests.log").open("x", encoding="utf-8") as stream:
        stream.write(run.stdout + run.stderr)
    match = re.search(r"Ran (\d+) tests", run.stderr)
    tests = int(match.group(1)) if match else None
    events.append({"event": "automated_boundary_tests", "argv": command,
                   "returncode": run.returncode, "test_count": tests,
                   "automated_elapsed_seconds": elapsed, "log_sha256": sha(out / "tests.log")})
    after = {str(p.relative_to(HERE)): sha(p) for p in sorted(HERE.rglob("*"))
             if p.is_file() and out not in p.parents and "__pycache__" not in p.parts}
    write(out / "operations.json", {"kind": "automated_development_execution_only",
                                    "human_trial_performed": False,
                                    "python": platform.python_version(), "platform": platform.platform(),
                                    "inputs_and_pilot_files_unchanged": before == after,
                                    "input_file_sha256": before, "events": events})
    if run.returncode or before != after:
        raise SystemExit("Offline proof failed; inspect recorded logs")
    print(json.dumps({"output": str(out), "tests_passed": tests, "fixtures": 2,
                      "human_trial_performed": False, "inputs_unchanged": before == after}))


if __name__ == "__main__":
    main()
