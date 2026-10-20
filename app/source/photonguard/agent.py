"""Honest backend boundary. Rule diagnostics do not pretend to be model calls."""
from __future__ import annotations
from typing import Protocol
import copy
from .core import POLICY,POLICY_HASH,digest,candidate_problem,expected_layers

class ModelBackend(Protocol):
    """Future adapter must preserve actual request/response, model id, tokens and cost."""
    def diagnose(self,task:dict,candidate:dict,evidence:dict)->dict: ...

class UnconfiguredModelBackend:
    def diagnose(self,task,candidate,evidence):
        raise RuntimeError("No runtime model backend configured. No LLM call occurred. Use rules-only mode, or configure an explicitly authorized provider adapter.")

def propose_patch(task,candidate,report):
    if report.get("task_hash")!=digest(task) or report.get("candidate_hash")!=digest(candidate):raise ValueError("Evidence does not match exact task and candidate")
    if report.get("status") in {"PASS","INCONCLUSIVE","UNSUPPORTED"}:return None
    if candidate.get("origin",{}).get("patch_round",0)>=POLICY["max_patch_rounds"]:return None
    changes=[];rationale=""
    if len(task.get("layers",[]))!=len(candidate.get("layers",[])):return None
    for i,(a,b) in enumerate(zip(task["layers"],expected_layers(candidate))):
        if a["n"]!=b["n"]:
            kind=candidate["layers"][i]["material_kind"]
            changes=[{"path":["layers",i,"material_value"],"old":candidate["layers"][i]["material_value"],"new":a["n"] if kind=="index" else a["n"]**2}]
            rationale="Restore the material to the independently confirmed task; epsilon=n² for this nonmagnetic lossless model"
            break
        if a["thickness_um"]!=b["thickness_um"]:
            changes=[{"path":["layers",i,"thickness_um"],"old":b["thickness_um"],"new":a["thickness_um"]}];rationale="Restore thickness to the independently confirmed task";break
    wf=candidate["workflow"];num=candidate["numerics"]
    if not changes:
        for key,value,why in (("reference_amplitude",num["source_amplitude"],"Recompute the reference with the target source amplitude"),("subtract_incident",True,"Subtract reference Fourier fields before reflection-flux accumulation")):
            if wf[key]!=value:changes=[{"path":["workflow",key],"old":wf[key],"new":value}];rationale=why;break
    if not changes:
        ids={c["id"] for c in report.get("checks",[]) if c["status"]=="FAIL"}
        if "time_sensitivity" in ids and num["after_sources"]<400:
            changes=[{"path":["numerics","after_sources"],"old":num["after_sources"],"new":min(400,num["after_sources"]*10)}]
            rationale="Measured time sensitivity failed; increase duration within the fixed resource budget and rerun"
        elif ("grid_sensitivity" in ids or "base_independent_tmm" in ids) and num["resolution"]<320:
            changes=[{"path":["numerics","resolution"],"old":num["resolution"],"new":min(320,num["resolution"]*4)}]
            rationale="Measured grid/reference discrepancy remains; refine grid within the fixed budget and rerun"
    if not changes:return None
    return {"schema_version":1,"backend":"rules_only","actual_llm_calls":0,"task_hash":digest(task),"candidate_hash":digest(candidate),"policy_hash":POLICY_HASH,"based_on_run":report["run_id"],"changes":changes,"rationale":rationale,"requires_explicit_approval":True,"verification":"Four reference/target pairs (eight FDTD simulations total) and mandatory checks must be rerun"}

def apply_patch(task,candidate,patch):
    if patch.get("task_hash")!=digest(task) or patch.get("candidate_hash")!=digest(candidate) or patch.get("policy_hash")!=POLICY_HASH:raise ValueError("Patch is stale or targets a different task/candidate/policy")
    changes=patch.get("changes",[])
    if len(changes)!=1:raise ValueError("Exactly one primary bounded change allowed")
    round=candidate.get("origin",{}).get("patch_round",0)+1
    if round>POLICY["max_patch_rounds"]:raise ValueError("Maximum patch rounds reached")
    change=changes[0];path=change.get("path",[])
    allowed_value=None
    if len(path)==3 and path[0]=="layers" and type(path[1]) is int and 0<=path[1]<len(task["layers"]) and path[2] in {"material_value","thickness_um"}:
        i=path[1];layer=task["layers"][i]
        if path[2]=="material_value":allowed_value=layer["n"] if candidate["layers"][i]["material_kind"]=="index" else layer["n"]**2
        else:allowed_value=layer["thickness_um"]
    elif path==["workflow","reference_amplitude"]:allowed_value=candidate["numerics"]["source_amplitude"]
    elif path==["workflow","reference_time_factor"]:allowed_value=1.0
    elif path==["workflow","subtract_incident"]:allowed_value=True
    elif path==["numerics","after_sources"]:
        allowed_value=min(400,candidate["numerics"]["after_sources"]*10)
    elif path==["numerics","resolution"]:
        allowed_value=min(320,candidate["numerics"]["resolution"]*4)
    else:raise ValueError("Patch path outside allowed recovery scope")
    if change.get("new")!=allowed_value:raise ValueError("Patch would change confirmed intent or required workflow")
    new=copy.deepcopy(candidate);target=new
    for key in path[:-1]:target=target[key]
    if target[path[-1]]!=change.get("old"):raise ValueError("Patch old value mismatched")
    target[path[-1]]=change["new"]
    problem=candidate_problem(new)
    if problem:raise ValueError(problem["reason"])
    new["origin"]={"kind":"approved-bounded-patch","patch_round":round,"original_candidate_hash":candidate.get("origin",{}).get("original_candidate_hash",digest(candidate)),"previous_candidate_hash":digest(candidate),"based_on_run":patch.get("based_on_run"),"patch_sha256":digest(patch)}
    if patch.get("diagnostic_provenance"):
        new["origin"]["diagnostic_provenance"] = copy.deepcopy(patch["diagnostic_provenance"])
    if "script_import" in candidate.get("origin",{}):
        new["origin"]["script_import"]=copy.deepcopy(candidate["origin"]["script_import"])
        new["origin"]["script_patch_history"]=copy.deepcopy(candidate["origin"].get("script_patch_history",[]))+[copy.deepcopy(patch)]
    return new
