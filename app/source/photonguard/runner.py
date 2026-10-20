"""Capped subprocess runs and append-only, hash-verifiable evidence bundles."""
from __future__ import annotations
import csv
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid
from .core import ASSUMPTIONS,POLICY,POLICY_HASH,load,write_json,digest,task_problem,candidate_problem,verify_lock
from .checks import check,static_checks,evaluate_raw,sensitivity,aggregate

VARIANTS=[{"name":"base"},{"name":"grid","resolution_factor":1.5},{"name":"time","time_factor":2},{"name":"pml","pml_factor":1.5}]

def limited_process():
    import resource  # Linux solver limits; offline Windows review never calls this.
    resource.setrlimit(resource.RLIMIT_AS,(POLICY["max_memory_mib"]*1024**2,)*2)
    resource.setrlimit(resource.RLIMIT_CPU,(POLICY["max_pair_seconds"],)*2)
    resource.setrlimit(resource.RLIMIT_FSIZE,(20*1024**2,)*2)
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))

def clean_environment():
    # Never transmit runtime LLM/API credentials to the solver process.
    keep=("PATH","LD_LIBRARY_PATH","DYLD_LIBRARY_PATH","SYSTEMROOT")
    env={k:os.environ[k] for k in keep if k in os.environ}
    env.update(OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",MKL_NUM_THREADS="1",PYTHONNOUSERSITE="1",MPLCONFIGDIR="/tmp/photonguard-mpl")
    return env

def finite_sampling(value):
    import math
    return type(value) in (int,float) and math.isfinite(value) and value > 0

def code_fingerprint():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))}

def environment():
    versions={}
    for name in ("numpy","tmm","pytest","meep","pymeep"):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: pass
    return {"python":sys.version,"executable":sys.executable,"platform":platform.platform(),"packages":versions,"code_sha256":code_fingerprint()}

def run_case(task_path,candidate_path,lock_path,out_root,max_fdtd_runs=8):
    if type(max_fdtd_runs) is not int or not 0<=max_fdtd_runs<=POLICY["max_fdtd_runs"]: raise ValueError("max_fdtd_runs must be integer 0..8")
    task=load(task_path);candidate=load(candidate_path);lock=load(lock_path)
    if not all(isinstance(x,dict) for x in (task,candidate,lock)): raise ValueError("Task, candidate and lock must be JSON objects")
    started=time.monotonic();run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]
    out=Path(out_root)/run_id;out.mkdir(parents=True,exist_ok=False);(out/"raw").mkdir()
    # Preserve original byte representation too, not only canonical interpreted data.
    for path,name in ((task_path,"task.original.json"),(candidate_path,"candidate.original.json"),(lock_path,"task.lock.json")):
        (out/name).write_bytes(Path(path).read_bytes())
    source_preservation_error=None
    imported_origin=candidate.get("origin",{})
    is_script_import=isinstance(imported_origin,dict) and ("script_import" in imported_origin or "script_patch_history" in imported_origin or imported_origin.get("kind")=="meep-ast-canonical-import")
    if is_script_import:
        from .script_import import decode_source
        try:(out/"script.original.py").write_bytes(decode_source(imported_origin.get("script_import")))
        except (ValueError,KeyError,TypeError) as exc:source_preservation_error=str(exc)
    checks=[];spectra=[];raws={};rows_by_name={};count=0
    report={"schema_version":1,"run_id":run_id,"case_id":task.get("case_id","unknown"),"created_at":datetime.now(timezone.utc).isoformat(),"task_hash":digest(task),"candidate_hash":digest(candidate),"policy_hash":POLICY_HASH,"policy":POLICY,"assumptions":ASSUMPTIONS,"checks":checks,"backend":{"mode":"rules_only","actual_llm_calls":0,"model":None,"note":"No runtime model configured; development assistance is not runtime AI evidence"},"environment":environment(),"limitations":["Development cases and thresholds only; not a held-out benchmark","PASS covers only the recorded discrete frequencies under stated assumptions","Tested-setting sensitivity is not proof of convergence","Evidence is write-protected and hash-verifiable, not cryptographic external attestation"],"origin":candidate.get("origin",{})}
    if "sampling" in task and not task_problem(task):
        from .sampling import description
        report["sampling"] = description(task)
    if is_script_import:
        from .script_import import CLAIM
        report["execution_scope"]={"kind":"canonical-recipe-from-read-only-script-import","claim":CLAIM,"script_executed":False,"provenance_verified":False,"original_recipe_modified":candidate.get("origin",{}).get("patch_round",0)>0}
    diagnostic=candidate.get("origin",{}).get("diagnostic_provenance") if isinstance(candidate.get("origin",{}),dict) else None
    if isinstance(diagnostic,dict) and diagnostic.get("mode") in {"assistant_mediated_gpt","deepseek_api"}:
        report["backend"]={"mode":diagnostic["mode"],"actual_llm_calls":diagnostic.get("api_calls") if diagnostic["mode"]=="deepseek_api" else None,"runtime_api_calls":diagnostic.get("api_calls",0),"assistant_mediated_exchanges":1 if diagnostic["mode"]=="assistant_mediated_gpt" else 0,"model":diagnostic.get("model_identity"),"provenance":diagnostic,"note":"Imported diagnostic provenance; the FDTD verifier itself never calls a model. Unknown token/cost values are not estimated."}
    if not verify_lock(task,lock): checks.append(check("task_lock","FAIL","Confirmed task or frozen policy hash changed; refusing execution"))
    else:
        checks.append(check("task_lock","PASS","Confirmed task and policy hashes match"))
        problem=task_problem(task) or candidate_problem(candidate)
        if not problem and is_script_import:
            from .script_import import validate_provenance,CLAIM
            try:
                if source_preservation_error:raise ValueError(source_preservation_error)
                source,preview=validate_provenance(candidate,task)
                # Report preserves extraction of original source, separate from any patched recipe.
                write_json(out/"script.import-report.json",preview)
                report["execution_scope"]={"kind":"canonical-recipe-from-read-only-script-import","claim":CLAIM,"original_script_sha256":preview["source"]["sha256"],"script_executed":False,"provenance_verified":True,"original_recipe_modified":candidate.get("origin",{}).get("patch_round",0)>0}
                checks.append(check("script_import_provenance","PASS","Original bytes re-parsed; source hash, mapped recipe, patch history and locked-task spectrum verified. This is not a script-execution result."))
            except (ValueError,KeyError,TypeError) as exc:
                problem={"status":"UNSUPPORTED","reason":"Script import provenance/scope rejected: "+str(exc)}
        if problem: checks.append(check("adapter_scope",problem["status"],problem["reason"]))
        else:
            checks.append(check("adapter_scope","PASS","Within supported parameterized film scope"));checks.extend(static_checks(task,candidate))
            for variant in VARIANTS:
                name=variant["name"]
                if count+2>max_fdtd_runs:
                    checks.append(check(name+"_execution","INCONCLUSIVE","FDTD run budget exhausted; required checks were not skipped into PASS"));continue
                request_path=out/"raw"/(name+".request.json");raw_path=out/"raw"/(name+".json")
                write_json(request_path,{"task":task,"candidate":candidate,"variant":variant})
                stdout_path=out/"raw"/(name+".stdout.log");stderr_path=out/"raw"/(name+".stderr.log")
                with stdout_path.open("w") as stdout,stderr_path.open("w") as stderr:
                    count+=2 # Conservative attempted-run reservation, even on worker failure.
                    try:
                        result=subprocess.run([sys.executable,str(Path(__file__).with_name("fdtd_worker.py")),str(request_path.resolve()),str(raw_path.resolve())],cwd=out,env=clean_environment(),stdout=stdout,stderr=stderr,timeout=POLICY["max_pair_seconds"]+5,preexec_fn=limited_process,check=False)
                        if result.returncode or not raw_path.exists():
                            checks.append(check(name+"_execution","INCONCLUSIVE","Meep worker failed; see retained stderr",returncode=result.returncode));continue
                    except subprocess.TimeoutExpired:
                        checks.append(check(name+"_execution","INCONCLUSIVE","Meep worker walltime limit exceeded"));continue
                raw=load(raw_path);raws[name]=raw
                new_checks,rows=evaluate_raw(raw,task);rows_by_name[name]=rows
                for c in new_checks:
                    c["id"]=name+"_"+c["id"]
                    checks.append(c)
                if name=="base":spectra=rows or []
            for name in ("grid","time","pml"):
                checks.append(sensitivity(rows_by_name.get("base"),rows_by_name.get(name),name+"_sensitivity"))
                if "base" in raws and name in raws:
                    a=raws["base"]["incident_flux"];b=raws[name]["incident_flux"]
                    den=max(abs(x) for x in a)
                    err=max(abs(x-y) for x,y in zip(a,b))/den if den else float("inf")
                    if err!=float("inf"):
                        checks.append(check(name+"_incident_sensitivity","PASS" if err<=POLICY["sensitivity_absolute_tolerance"] else "FAIL","Max absolute raw incident-flux change normalized by baseline peak",max_relative_to_peak_change=err,tolerance=POLICY["sensitivity_absolute_tolerance"]))
                    else:checks.append(check(name+"_incident_sensitivity","INCONCLUSIVE","Zero incident signal"))
    report["status"]=aggregate(checks)
    report["resource_usage"]={"fdtd_runs":sum(r["fdtd_runs"] for r in raws.values()),"fdtd_count_definition":"Completed paired simulations only; a failed worker may have started more work. See fdtd_attempts_reserved.","fdtd_attempts_reserved":count,"wall_seconds":time.monotonic()-started,"solver_wall_seconds":sum(r["wall_seconds"] for r in raws.values()),"peak_worker_rss_kib":max([r["max_rss_kib"] for r in raws.values()] or [0]),"max_fdtd_runs":max_fdtd_runs,"workers":"sequential serial; OMP/BLAS threads=1"}
    if report.get('sampling'):
        sampling = report['sampling']
        sampling['planned_solver_frequencies_per_um'] = sampling['actual_solver_frequencies_per_um']
        sampling['requested_wavelengths_um'] = sampling['actual_solver_wavelengths_um']
        observed = raws.get('base',{}).get('frequency',[])
        if not isinstance(observed,list) or any(not finite_sampling(v) for v in observed): observed=[]
        sampling['actual_solver_frequencies_per_um'] = observed
        sampling['actual_solver_wavelengths_um'] = [1/f for f in observed]
        sampling['actual_solver_point_count'] = len(observed)
    if raws:report["environment"]["meep_actual_version"]=next(iter(raws.values()))["meep_version"]
    report["files"]={"spectrum":"spectrum.csv","raw":"raw","task":"task.original.json","candidate":"candidate.original.json"}
    if (out/"script.original.py").exists():report["files"]["imported_source"]="script.original.py"
    if (out/"script.import-report.json").exists():report["files"]["import_preview"]="script.import-report.json"
    write_json(out/"report.json",report)
    with (out/"spectrum.csv").open("w",newline="") as f:
        cols=["frequency","wavelength_um","R","T","R_reference","T_reference"]
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows(spectra)
    try:
        from .report import render_report
        (out/"report.html").write_text(render_report(report,spectra),encoding="utf-8")
    except ImportError:
        import html
        (out/"report.html").write_text("<meta charset='utf-8'><pre>"+html.escape(json.dumps(report,ensure_ascii=False,indent=2))+"</pre>")
    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}
    write_json(out/"manifest.json",{"schema_version":1,"algorithm":"sha256","run_id":run_id,"files":files})
    for p in out.rglob("*"):
        if p.is_file():p.chmod(0o444)
    for p in sorted(out.rglob("*"),reverse=True):
        if p.is_dir():p.chmod(0o555)
    out.chmod(0o555)
    return report,out

def verify_evidence(path):
    path=Path(path)
    if not (path/"manifest.json").is_file() or any(p.is_symlink() for p in path.rglob("*")):return False
    manifest=load(path/"manifest.json")
    actual={str(p.relative_to(path)) for p in path.rglob("*") if p.is_file() and p.relative_to(path).as_posix()!="manifest.json"}
    expected=set(manifest["files"])
    if actual!=expected:return False
    for rel,value in manifest["files"].items():
        p=(path/rel).resolve()
        if path.resolve() not in p.parents or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=value:return False
    return True
