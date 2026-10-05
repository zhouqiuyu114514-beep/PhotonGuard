"""Local CLI, explicit task/patch confirmation, no arbitrary code execution."""
import argparse
import json
from pathlib import Path
import sys
import zipfile
from .core import load,write_json,lock_task,verify_lock
from .runner import run_case,verify_evidence
from .agent import propose_patch,apply_patch

def main(argv=None):
    p=argparse.ArgumentParser(prog="photonguard",description="Bounded evidence-first Meep film checker")
    subs=p.add_subparsers(dest="command",required=True)
    c=subs.add_parser("import-script",help="Read-only AST preview; never executes supplied Python");c.add_argument("script");c.add_argument("--out",required=True)
    c=subs.add_parser("confirm");c.add_argument("task");c.add_argument("--lock",required=True);c.add_argument("--approve",action="store_true",required=True)
    c=subs.add_parser("run");c.add_argument("task");c.add_argument("candidate");c.add_argument("--lock",required=True);c.add_argument("--out",default="artifacts");c.add_argument("--max-fdtd-runs",type=int,default=8)
    c=subs.add_parser("propose");c.add_argument("evidence");c.add_argument("--out",required=True)
    c=subs.add_parser("apply");c.add_argument("task");c.add_argument("candidate");c.add_argument("patch");c.add_argument("--lock",required=True);c.add_argument("--out",required=True);c.add_argument("--approve",action="store_true",required=True)
    c=subs.add_parser("verify-evidence");c.add_argument("evidence")
    c=subs.add_parser("export");c.add_argument("evidence");c.add_argument("--out",required=True)
    c=subs.add_parser("diagnose-api");c.add_argument("evidence");c.add_argument("--config",required=True);c.add_argument("--ledger",required=True);c.add_argument("--out",required=True);c.add_argument("--audit-dir",required=True);c.add_argument("--approve-data-and-cost",action="store_true",required=True)
    c=subs.add_parser("export-model");c.add_argument("evidence");c.add_argument("--out",required=True)
    c=subs.add_parser("import-model");c.add_argument("evidence");c.add_argument("request");c.add_argument("response");c.add_argument("--provenance",required=True);c.add_argument("--out",required=True);c.add_argument("--audit-dir",required=True)
    c=subs.add_parser("ui");c.add_argument("--root",default=".");c.add_argument("--port",type=int,default=8765)
    args=p.parse_args(argv)
    try:
        if args.command=="import-script":
            from .script_import import write_preview
            preview,path=write_preview(args.script,args.out)
            print(json.dumps({"status":preview["status"],"preview":str(path),"source_sha256":preview["source"]["sha256"],"claim":preview["claim"],"unresolved":preview["unresolved"],"next_step":"Review extracted candidate and source mappings. Independently supply and explicitly confirm a task with units, physics and spectrum before running. Import does not create or approve a task."},ensure_ascii=False,indent=2))
            return 0 if preview["status"]=="EXTRACTED" else 4
        elif args.command=="confirm":print(json.dumps(lock_task(args.task,args.lock),indent=2))
        elif args.command=="run":
            report,path=run_case(args.task,args.candidate,args.lock,args.out,args.max_fdtd_runs)
            summary={"status":report["status"],"evidence":str(path),"resource_usage":report["resource_usage"]}
            if "execution_scope" in report:summary["execution_scope"]=report["execution_scope"]
            print(json.dumps(summary,indent=2))
            return 0 if report["status"]=="PASS" else {"FAIL":2,"INCONCLUSIVE":3,"UNSUPPORTED":4}[report["status"]]
        elif args.command=="propose":
            path=Path(args.evidence)
            if not verify_evidence(path):raise ValueError("Evidence integrity check failed")
            patch=propose_patch(load(path/"task.original.json"),load(path/"candidate.original.json"),load(path/"report.json"))
            if patch is None:print("No supported bounded patch. No change made.");return 3
            write_json(args.out,patch);print(json.dumps(patch,ensure_ascii=False,indent=2))
        elif args.command=="apply":
            task=load(args.task)
            if not verify_lock(task,load(args.lock)):raise ValueError("Task lock invalid")
            patch=load(args.patch);candidate=apply_patch(task,load(args.candidate),patch)
            if patch.get("diagnostic_provenance"):candidate["origin"]["diagnostic_provenance"]=patch["diagnostic_provenance"]
            write_json(args.out,candidate)
            print("Approved candidate written. This is not a PASS; rerun all required checks.")
        elif args.command=="verify-evidence":
            ok=verify_evidence(args.evidence);print("VERIFIED" if ok else "TAMPERED");return 0 if ok else 2
        elif args.command=="export":
            root=Path(args.evidence)
            if not verify_evidence(root):raise ValueError("Evidence integrity check failed")
            with zipfile.ZipFile(args.out,"x",zipfile.ZIP_DEFLATED) as z:
                for f in sorted(root.rglob("*")):
                    if f.is_file():z.write(f,root.name+"/"+str(f.relative_to(root)))
            print(args.out)
        elif args.command=="diagnose-api":
            from .api_cli import diagnose_api
            return diagnose_api(args)
        elif args.command=="export-model":
            from .exchange import export_request
            request=export_request(args.evidence);write_json(args.out,request)
            print("Exported diagnostic inputs without case labels or reference spectra. No model was called.")
        elif args.command=="import-model":
            from .exchange import action_to_patch,save_exchange
            request=load(args.request);action=load(args.response);provenance=load(args.provenance)
            patch=action_to_patch(args.evidence,request,action,provenance)
            save_exchange(args.audit_dir,request,action,provenance,patch)
            if patch is None:print("Model abstained or proposed no change. Verifier result remains unchanged.")
            else:write_json(args.out,patch);print("Model proposal validated and recorded. Approval plus complete revalidation still required.")
        elif args.command=="ui":
            from .ui import serve
            serve(Path(args.root),port=args.port)
        return 0
    except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError) as e:
        print(f"PhotonGuard stopped safely: {e}",file=sys.stderr);return 3

if __name__=="__main__":raise SystemExit(main())
