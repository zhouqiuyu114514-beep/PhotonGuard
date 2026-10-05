"""Trusted worker: the only executable FDTD recipe. Input is data, never source."""
from __future__ import annotations
import hashlib
import json
import math
import resource
import sys
import time
from pathlib import Path
import meep as mp
import numpy as np


def run(request):
    mp.verbosity(0)
    t0=time.monotonic()
    task=request["task"]
    candidate=request["candidate"]
    num=candidate["numerics"]
    wf=candidate["workflow"]
    variant=request["variant"]
    resolution=round(num["resolution"]*variant.get("resolution_factor",1))
    after=num["after_sources"]*variant.get("time_factor",1)
    pml=num["pml_um"]*variant.get("pml_factor",1)
    # Physical coordinates remain fixed for the PML-thickness study.
    thickness=sum(l["thickness_um"] for l in candidate["layers"])
    air=num["air_um"]
    cell_z=thickness+2*air+2*pml
    source_z=-thickness/2-2
    reflection_z=-thickness/2-1.5
    transmission_z=thickness/2+1.5
    fmin=1/task["wavelength_um"][1];fmax=1/task["wavelength_um"][0]
    fcen=(fmin+fmax)/2;df=fmax-fmin
    recipe={"recipe":"film1d-v1","meep_version":mp.__version__,"dimensions":1,"component":"Ex","resolution":resolution,"courant":0.5,"cell_z":cell_z,"pml_um":pml,"source_z":source_z,"reflection_z":reflection_z,"transmission_z":transmission_z,"fcen":fcen,"df":df,"source_fwidth":2*df,"nfreq":task["nfreq"],"epsilon_averaging":True,"chunk_layout":"serial-single-process","source_cutoff":5.0,"dft_decimation_factor":1}
    def make(geometry,amplitude):
        return mp.Simulation(cell_size=mp.Vector3(0,0,cell_z),dimensions=1,resolution=resolution,Courant=.5,boundary_layers=[mp.PML(pml,direction=mp.Z)],geometry=geometry,sources=[mp.Source(mp.GaussianSource(fcen,fwidth=2*df,cutoff=5.0),component=mp.Ex,center=mp.Vector3(0,0,source_z),amplitude=amplitude)],eps_averaging=True)
    def monitors(sim):
        return (sim.add_flux(fcen,df,task["nfreq"],mp.FluxRegion(center=mp.Vector3(0,0,reflection_z),direction=mp.Z),decimation_factor=1),sim.add_flux(fcen,df,task["nfreq"],mp.FluxRegion(center=mp.Vector3(0,0,transmission_z),direction=mp.Z),decimation_factor=1))
    ref=make([],wf["reference_amplitude"])
    rref,tref=monitors(ref)
    ref.run(until_after_sources=after*wf["reference_time_factor"])
    reference_end=ref.meep_time()
    incident=np.array(mp.get_fluxes(tref),float)
    reference_reflection=np.array(mp.get_fluxes(rref),float)
    minus_data=ref.get_flux_data(rref)
    reference_freq=np.array(mp.get_flux_freqs(tref),float)
    ref.reset_meep()
    geometry=[]
    cursor=-thickness/2
    for l in candidate["layers"]:
        d=l["thickness_um"]
        material=mp.Medium(**{l["material_kind"]:l["material_value"]})
        geometry.append(mp.Block(size=mp.Vector3(mp.inf,mp.inf,d),center=mp.Vector3(0,0,cursor+d/2),material=material))
        cursor+=d
    target=make(geometry,num["source_amplitude"])
    rt,tt=monitors(target)
    if wf["subtract_incident"]: target.load_minus_flux_data(rt,minus_data)
    target.run(until_after_sources=after)
    target_end=target.meep_time()
    freq=np.array(mp.get_flux_freqs(tt),float)
    reflected=np.array(mp.get_fluxes(rt),float)
    transmitted=np.array(mp.get_fluxes(tt),float)
    target.reset_meep()
    ref_recipe={**recipe,"geometry_recipe":"empty-air-reference","source_amplitude":wf["reference_amplitude"],"after_sources":after*wf["reference_time_factor"]}
    target_recipe={**recipe,"geometry_recipe":"candidate-films","source_amplitude":num["source_amplitude"],"after_sources":after}
    return {"schema_version":1,"engine":"meep","meep_version":mp.__version__,"variant":variant,"frequency":freq.tolist(),"reference_frequency":reference_freq.tolist(),"incident_flux":incident.tolist(),"reference_reflection_plane_flux":reference_reflection.tolist(),"target_reflection_flux":reflected.tolist(),"target_transmission_flux":transmitted.tolist(),"reflection_is_incident_subtracted":wf["subtract_incident"],"reference_recipe":ref_recipe,"target_recipe":target_recipe,"reference_fingerprint":hashlib.sha256(json.dumps(ref_recipe,sort_keys=True).encode()).hexdigest(),"target_recipe_fingerprint":hashlib.sha256(json.dumps(target_recipe,sort_keys=True).encode()).hexdigest(),"actual_stop_times":{"reference":reference_end,"target":target_end},"termination_reason":"fixed post-source duration completed","wall_seconds":time.monotonic()-t0,"max_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,"fdtd_runs":2}

if __name__=="__main__":
    request=json.loads(Path(sys.argv[1]).read_text())
    result=run(request)
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
