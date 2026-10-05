"""Visible deterministic importer development cases; never executes input scripts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parents[1]))
from photonguard.agent import apply_patch, propose_patch
from photonguard.core import POLICY_HASH, digest, load, lock_task, write_json
from photonguard.runner import code_fingerprint, run_case, verify_evidence
from photonguard.script_import import write_preview


def main():
    root = Path(__file__).parents[1]
    batch = root / "benchmark" / ("script-import-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    batch.mkdir(exist_ok=False)
    source = (root / "examples/script_import/film_n2.py").read_text()
    unequal = source.replace("ref = mp.Simulation", "refsource = mp.Source(pulse, component=mp.Ex, center=mp.Vector3(0, 0, -d/2-2), amplitude=0.5)\nref = mp.Simulation").replace("sources=[source], eps_averaging=True)", "sources=[refsource], eps_averaging=True)", 1)
    cases = [
        ("recognized-film", source, "film_n2", "PASS", False),
        ("epsilon-preserved", source.replace("mp.Medium(index=n)", "mp.Medium(epsilon=n)"), "film_n2", "FAIL", True),
        ("subtraction-omitted", source.replace("target.load_minus_flux_data(rflux, incident_data)", "# intentionally omitted"), "film_n2", "FAIL", True),
        ("unequal-reference-amplitude", unequal, "film_n2", "FAIL", True),
        ("unknown-branch", source + "\nif False:\n    target.run(until_after_sources=100)\n", "film_n2", "UNSUPPORTED", False),
        ("unresolved-material", source.replace("mp.Medium(index=n)", "mp.Medium(index=unknown_material)"), "film_n2", "UNSUPPORTED", False),
        ("uncanonical-source", source.replace("-d / 2 - 2)", "-d / 2 - 2.1)"), "film_n2", "UNSUPPORTED", False),
        ("incompatible-task-spectrum", source, "film_n2", "UNSUPPORTED", False),
    ]
    write_json(batch / "manifest.json", {"scope":"visible synthetic script-import development cases, not held-out or AI evaluation", "source_sha256":code_fingerprint(), "policy_sha256":POLICY_HASH,"cases":[{"id":x[0],"expected":x[3],"source_sha256":hashlib.sha256(x[1].encode()).hexdigest()} for x in cases]})
    results = []
    for name, text, task_name, expected, repair in cases:
        folder = batch / name; folder.mkdir()
        original = folder / "input.py"; original.write_bytes(text.encode())
        preview, imported = write_preview(original, folder / "import")
        item = {"id":name,"expected":expected,"import_status":preview["status"],"source_sha256":preview["source"]["sha256"],"actual_status":"UNSUPPORTED","repairs":[],"fdtd_runs":0}
        if preview["status"] == "EXTRACTED":
            task = load(root / "examples" / task_name / "task.json")
            if name == "incompatible-task-spectrum": task["nfreq"] = 43
            task_path = folder / "task.json"; lock = folder / "task.lock.json"
            write_json(task_path, task); lock_task(task_path, lock)
            report, evidence = run_case(task_path, imported / "candidate.json", lock, root / "artifacts")
            item.update(actual_status=report["status"], evidence=str(evidence.relative_to(root)), integrity_verified=verify_evidence(evidence), fdtd_runs=report["resource_usage"]["fdtd_runs"])
            candidate = preview["candidate"]
            if repair:
                patch = propose_patch(task, candidate, report)
                if patch is not None:
                    # Explicit developer-fixture approval, not an inferred end-user approval.
                    write_json(folder / "patch.json", patch)
                    fixed = apply_patch(task, candidate, patch)
                    write_json(folder / "repaired.json", fixed)
                    rerun, repaired = run_case(task_path, folder / "repaired.json", lock, root / "artifacts")
                    item["repairs"].append({"status":rerun["status"],"evidence":str(repaired.relative_to(root)),"integrity_verified":verify_evidence(repaired),"original_script_sha256":rerun["execution_scope"]["original_script_sha256"],"fdtd_runs":rerun["resource_usage"]["fdtd_runs"],"task_hash_unchanged":rerun["task_hash"]==digest(task)})
        results.append(item)
        write_json(batch / "results.json", results)
        print(name, item["actual_status"], [x["status"] for x in item["repairs"]], flush=True)
    summary = {"scope":"visible deterministic parser and trusted-recipe development checks", "cases":len(results), "expected_status_matched":sum(x["expected"]==x["actual_status"] for x in results),"faults_repaired":sum(bool(x["repairs"]) and x["repairs"][-1]["status"]=="PASS" for x in results),"total_fdtd_runs":sum(x["fdtd_runs"]+sum(y["fdtd_runs"] for y in x["repairs"]) for x in results), "policy_sha256":POLICY_HASH,"actual_llm_calls":0,"input_scripts_executed":0,"not_established":["Arbitrary-script equivalence","AI gain","Natural-language intent extraction","Held-out template robustness","User effort reduction"]}
    write_json(batch / "summary.json", summary)
    print(json.dumps(summary, indent=2)); print(batch)
    return 0 if summary["expected_status_matched"]==len(cases) and summary["faults_repaired"]==3 else 2


if __name__ == "__main__": raise SystemExit(main())
