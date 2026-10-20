"""Frozen, deterministic checks. Model output cannot alter these thresholds."""
from __future__ import annotations
import math
from .core import POLICY, consistency


def check(id,status,summary,**metrics):
    return {"id":id,"status":status,"summary":summary,"metrics":metrics}

def static_checks(task,candidate):
    wf=candidate["workflow"];num=candidate["numerics"]
    matched=consistency(task,candidate)
    amplitude=wf["reference_amplitude"]==num["source_amplitude"]
    time_match=wf["reference_time_factor"]==1
    return [
        check("task_parameters","PASS" if matched else "FAIL","Candidate material/thickness matches confirmed task" if matched else "Confirmed task differs from candidate material/thickness; energy balance alone cannot detect this"),
        check("reference_pairing","PASS" if amplitude else "FAIL","Reference source amplitude matches target; unequal stop times require numerical evidence, not an automatic failure" if amplitude else "Reference source amplitude differs from target",reference_amplitude=wf["reference_amplitude"],target_amplitude=num["source_amplitude"],reference_time_factor=wf["reference_time_factor"]),
        check("reflection_subtraction","PASS" if wf["subtract_incident"] else "FAIL","Incident fields subtracted before reflection flux accumulation" if wf["subtract_incident"] else "Reflection monitor contains incident plus reflected fields; not a reflection-power measurement"),
    ]

def evaluate_raw(raw,task):
    """Never mask, clip, drop NaNs or silently delete weak-spectrum frequencies."""
    import numpy as np
    fields=("frequency","reference_frequency","incident_flux","reference_reflection_plane_flux","target_reflection_flux","target_transmission_flux")
    values={}
    for k in fields:
        try: a=np.asarray(raw[k],dtype=float)
        except (KeyError,TypeError,ValueError): return [check("signal_coverage","INCONCLUSIVE",f"Missing/invalid raw array {k}")],None
        if a.ndim!=1 or len(a)!=task["nfreq"] or not np.all(np.isfinite(a)):
            return [check("signal_coverage","INCONCLUSIVE",f"Incomplete/nonfinite raw array {k}")],None
        values[k]=a
    from .sampling import frequencies
    expected=np.asarray(frequencies(task))
    if not np.allclose(values["frequency"],expected,atol=1e-12,rtol=1e-12) or not np.allclose(values["reference_frequency"],expected,atol=1e-12,rtol=1e-12):
        return [check("signal_coverage","INCONCLUSIVE","Actual target/reference frequency arrays do not cover the complete requested frequency grid")],None
    incident=values["incident_flux"]
    maximum=float(np.max(incident));floor=POLICY["incident_relative_floor"]
    weak=np.flatnonzero((incident<POLICY["incident_absolute_floor"])|(incident<maximum*floor)).tolist()
    if maximum<=0 or weak:
        return [check("signal_coverage","INCONCLUSIVE","Requested frequencies have insufficient incident signal; no bins were discarded",weak_frequency_indices=weak,relative_floor=floor,absolute_floor=POLICY["incident_absolute_floor"])],None
    # This reference derives from the locked task, never from candidate material values.
    from tmm import coh_tmm
    ns=[1]+[l["n"] for l in task["layers"]]+[1]
    ds=[float("inf")]+[l["thickness_um"] for l in task["layers"]]+[float("inf")]
    reference=[coh_tmm("s",ns,ds,0,1/f) for f in values["frequency"]]
    rr=np.array([r["R"] for r in reference]);tr=np.array([r["T"] for r in reference])
    r=-values["target_reflection_flux"]/incident;t=values["target_transmission_flux"]/incident
    if not np.all(np.isfinite(r)) or not np.all(np.isfinite(t)):
        return [check("signal_coverage","INCONCLUSIVE","Normalized output is nonfinite")],None
    deviation=float(max(np.max(np.abs(r-rr)),np.max(np.abs(t-tr))))
    energy=float(np.max(np.abs(r+t-1)))
    tol=POLICY["rt_absolute_tolerance"]
    rows=[{"frequency":float(f),"wavelength_um":float(1/f),"R":float(rv),"T":float(tv),"R_reference":float(rref),"T_reference":float(tref)} for f,rv,tv,rref,tref in zip(values["frequency"],r,t,rr,tr)]
    checks=[check("signal_coverage","PASS","All requested frequencies have finite, positive incident signal",min_relative_signal=float(np.min(incident)/maximum),frequency_count=len(incident)),check("independent_tmm","PASS" if deviation<=tol else "FAIL","Maximum absolute R/T error against locked-task tmm reference",max_absolute_error=deviation,tolerance=tol),check("energy_balance","PASS" if energy<=tol else "FAIL","Complete-channel lossless R+T balance; necessary but not sufficient",max_absolute_residual=energy,tolerance=tol)]
    bounds=float(max(0,-np.min(r),-np.min(t),np.max(r)-1,np.max(t)-1))
    checks.append(check("physical_bounds","PASS" if bounds<=tol else "FAIL","Lossless power bounds without clipping",max_violation=bounds,tolerance=tol))
    return checks,rows

def sensitivity(base,variant,kind):
    import numpy as np
    if base is None or variant is None: return check(kind,"INCONCLUSIVE","Complete spectra unavailable for sensitivity check")
    err=max(abs(a[k]-b[k]) for a,b in zip(base,variant) for k in ("R","T"))
    tol=POLICY["sensitivity_absolute_tolerance"]
    return check(kind,"PASS" if err<=tol else "FAIL","Sensitivity at the tested pair of settings, not proof of asymptotic convergence",max_absolute_change=float(err),tolerance=tol)

def aggregate(checks):
    statuses={c["status"] for c in checks}
    if "FAIL" in statuses:return "FAIL"
    if "UNSUPPORTED" in statuses:return "UNSUPPORTED"
    if "INCONCLUSIVE" in statuses:return "INCONCLUSIVE"
    return "PASS"
