"""Data validation and task locking. No input code is executed."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

POLICY = {
    "version": "development-v0.1.0",
    "rt_absolute_tolerance": 0.01,
    "sensitivity_absolute_tolerance": 0.005,
    "incident_relative_floor": 1e-6,
    "incident_absolute_floor": 1e-12,
    "max_layers": 8,
    "max_total_thickness_um": 5.0,
    "max_frequency_points": 201,
    "max_resolution": 480,
    "max_after_sources": 800,
    "max_fdtd_runs": 8,
    "max_pair_seconds": 60,
    "max_memory_mib": 1536,
    "max_patch_rounds": 2,
}
POLICY_HASH = hashlib.sha256(json.dumps(POLICY,sort_keys=True,separators=(",",":")).encode()).hexdigest()
ASSUMPTIONS = ["1D z-axis, normal incidence, Ex polarization", "Linear, lossless, nondispersive, isotropic, nonmagnetic layers", "Air incident and exit media; all propagating channels represented", "Strict parameterized adapter only; arbitrary Python is never executed", "Development tolerances, not a scientific correctness certificate"]

def canonical(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)

def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Non-finite JSON: {x}")))

def write_json(path,x):
    Path(path).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

def finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)

def issue(status,reason):
    return {"status":status,"reason":reason}

def task_problem(task):
    """Unknown intent is distinct from out-of-scope physics."""
    if not isinstance(task,dict): return issue("INCONCLUSIVE","Task must be an object")
    known={"schema_version","case_id","physics","units_um","layers","wavelength_um","nfreq","sources","intent_note"}
    if set(task)-known: return issue("UNSUPPORTED","Unrecognized task fields: "+str(sorted(set(task)-known)))
    if type(task.get("schema_version")) is not int or task.get("schema_version") != 1: return issue("UNSUPPORTED","Unknown task schema")
    p=task.get("physics",{})
    if not isinstance(p,dict): return issue("INCONCLUSIVE","Missing physics assumptions")
    supported={"dimensions":1,"angle_deg":0,"lossless":True,"dispersive":False,"isotropic":True,"mu":1,"n_incident":1,"n_exit":1}
    for k,v in supported.items():
        if k not in p or p[k] is None: return issue("INCONCLUSIVE",f"Unconfirmed physics field: {k}")
        if type(p[k]) is not type(v) and not (type(p[k]) in (int,float) and type(v) in (int,float)) or p[k] != v: return issue("UNSUPPORTED",f"Unsupported physics {k}={p[k]}")
    if set(p)-set(supported): return issue("UNSUPPORTED","Unrecognized physics fields")
    if not finite(task.get("units_um")) or task.get("units_um") != 1.0: return issue("UNSUPPORTED","First adapter uses one micrometre per unit")
    layers=task.get("layers")
    if not isinstance(layers,list) or not layers: return issue("INCONCLUSIVE","Layer specification missing")
    if len(layers)>POLICY["max_layers"]: return issue("UNSUPPORTED","Layer count exceeds adapter limit")
    for layer in layers:
        if not isinstance(layer,dict) or set(layer)-{"n","thickness_um"}: return issue("UNSUPPORTED","Unsupported layer fields")
        if layer.get("n") is None or layer.get("thickness_um") is None: return issue("INCONCLUSIVE","Unknown layer index or thickness; intent is required")
        if not finite(layer["n"]) or not 1<=layer["n"]<=5 or not finite(layer["thickness_um"]) or not 0.02<=layer["thickness_um"]<=5:
            return issue("UNSUPPORTED","Layer outside bounded real-index/thickness range")
    if sum(l["thickness_um"] for l in layers)>5: return issue("UNSUPPORTED","Total thickness exceeds resource range")
    w=task.get("wavelength_um")
    if not isinstance(w,list) or len(w)!=2 or not all(finite(v) for v in w) or not 0.5<=w[0]<w[1]<=5:
        return issue("INCONCLUSIVE","Valid ordered wavelength endpoints in [0.5,5] um required")
    if not isinstance(task.get("nfreq"),int) or isinstance(task["nfreq"],bool) or not 3<=task["nfreq"]<=201:
        return issue("INCONCLUSIVE","nfreq must be an integer in [3,201]")
    if not task.get("sources"): return issue("INCONCLUSIVE","Intent provenance must be supplied")
    return None

def lock_task(task_path,lock_path):
    task=load(task_path)
    record={"schema_version":1,"task_sha256":digest(task),"policy_sha256":POLICY_HASH,"confirmation":"Explicit CLI --approve confirmation", "case_id":task.get("case_id")}
    write_json(lock_path,record)
    return record

def verify_lock(task,lock):
    return lock.get("task_sha256")==digest(task) and lock.get("policy_sha256")==POLICY_HASH

def candidate_problem(c):
    if not isinstance(c,dict): return issue("UNSUPPORTED","Candidate must be a JSON adapter object")
    allowed={"schema_version","adapter","case_id","layers","numerics","workflow","origin"}
    if set(c)-allowed: return issue("UNSUPPORTED","Unsupported candidate fields")
    if type(c.get("schema_version")) is not int or c.get("schema_version")!=1 or c.get("adapter")!="film1d-v1": return issue("UNSUPPORTED","Only film1d-v1 parameterized adapter supported")
    if not isinstance(c.get("layers"),list) or not c["layers"] or len(c["layers"])>8: return issue("UNSUPPORTED","Invalid layers")
    for l in c["layers"]:
        if not isinstance(l,dict) or set(l)-{"material_kind","material_value","thickness_um"}: return issue("UNSUPPORTED","Unknown candidate layer fields")
        if l.get("material_kind") not in {"index","epsilon"}: return issue("UNSUPPORTED","Unsupported material kind")
        n=l.get("material_value");d=l.get("thickness_um")
        if not finite(n) or not 1<=n<=(5 if l["material_kind"]=="index" else 25) or not finite(d) or not .02<=d<=5: return issue("UNSUPPORTED","Invalid candidate material or thickness")
    if sum(l["thickness_um"] for l in c["layers"])>5: return issue("UNSUPPORTED","Candidate exceeds bounded cell range")
    num=c.get("numerics",{})
    if not isinstance(num,dict): return issue("UNSUPPORTED","Numerics must be an object")
    if set(num)!={"resolution","after_sources","pml_um","air_um","source_amplitude"}: return issue("UNSUPPORTED","Numerical configuration requires exact supported fields")
    limits={"resolution":(20,320),"after_sources":(10,400),"pml_um":(.5,2),"air_um":(3,5),"source_amplitude":(.1,2)}
    for k,(lo,hi) in limits.items():
        if not finite(num[k]) or not lo<=num[k]<=hi: return issue("UNSUPPORTED",f"Out-of-range numerical setting {k}")
    if type(num["resolution"]) is not int: return issue("UNSUPPORTED","Resolution must be integer")
    wf=c.get("workflow",{})
    if not isinstance(wf,dict): return issue("UNSUPPORTED","Workflow must be an object")
    if set(wf)!={"subtract_incident","reference_amplitude","reference_time_factor"}: return issue("UNSUPPORTED","Unsupported workflow fields")
    if type(wf["subtract_incident"]) is not bool: return issue("UNSUPPORTED","subtract_incident must be Boolean")
    if not finite(wf["reference_amplitude"]) or not .1<=wf["reference_amplitude"]<=2: return issue("UNSUPPORTED","Reference amplitude out of range")
    if not finite(wf["reference_time_factor"]) or not 0<=wf["reference_time_factor"]<=1: return issue("UNSUPPORTED","Reference time factor out of range")
    origin=c.get("origin",{})
    if not isinstance(origin,dict) or type(origin.get("patch_round",0)) is not int or not 0<=origin.get("patch_round",0)<=2: return issue("UNSUPPORTED","Invalid patch provenance")
    return None

def expected_layers(candidate):
    return [{"n":l["material_value"] if l["material_kind"]=="index" else math.sqrt(l["material_value"]),"thickness_um":l["thickness_um"]} for l in candidate["layers"]]

def consistency(task,candidate):
    a=task["layers"];b=expected_layers(candidate)
    return len(a)==len(b) and all(abs(x["n"]-y["n"])<1e-12 and abs(x["thickness_um"]-y["thickness_um"])<1e-12 for x,y in zip(a,b))
