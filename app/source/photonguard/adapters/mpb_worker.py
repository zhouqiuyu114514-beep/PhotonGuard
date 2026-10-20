"""Owned full-vector MPB kernel; takes only a validated task/check plan, never code."""
from pathlib import Path
import json,sys,time,resource
import numpy as np
import meep as mp
from meep import mpb

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from photonguard.materials.ln_sellmeier import dielectric_tensor,XCUT_ROTATION
from photonguard.mpb_metadata import actual_grid,restore_array,energy_audit,runtime_build_fingerprint

def solve(wavelength,resolution,domain,out,requirements,*,calibration_slab=False,quarter_turn=False):
    started=time.monotonic();sx,sy=domain
    rotation=np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])
    material=dielectric_tensor(wavelength,rotation=rotation@XCUT_ROTATION if quarter_turn else None)
    tensor=np.asarray(material['laboratory_epsilon'])
    crystal=mp.Medium(epsilon_diag=mp.Vector3(*np.diag(tensor)),epsilon_offdiag=mp.Vector3(tensor[0,1],tensor[0,2],tensor[1,2]))
    film= requirements['film_thickness_um'];slab=requirements['slab_thickness_um'];width=requirements['ridge_width_um']
    if calibration_slab:
        if quarter_turn:raise ValueError('Use the 2D equivalent-rotation check, not a collapsed-axis permutation.')
        lattice=mp.Lattice(size=mp.Vector3(0,sy,0))
        geometry=[mp.Block(size=mp.Vector3(mp.inf,film,mp.inf),material=crystal)]
        default=mp.Medium(index=1.44)
    else:
        lattice=mp.Lattice(size=mp.Vector3(sx,sy,0))
        # Rotate geometry and tensor together. z and the propagation direction are unchanged.
        def block(w,h,cx,cy,medium):
            return mp.Block(size=mp.Vector3(h,w,mp.inf) if quarter_turn else mp.Vector3(w,h,mp.inf),
                center=mp.Vector3(-cy,cx,0) if quarter_turn else mp.Vector3(cx,cy,0),material=medium)
        transverse_height=sx if quarter_turn else sy
        # The slab and cap have disjoint interiors and the same continuous LN union
        # as a full-film ridge over the slab. This removes artificial object corners
        # on the physically flat LN/substrate face from MPB's interface averaging.
        geometry=[block(mp.inf,transverse_height/2-film/2,0,-transverse_height/4-film/4,mp.Medium(index=requirements['bottom_index'])),
            block(mp.inf,slab,0,-film/2+slab/2,crystal),block(width,film-slab,0,slab/2,crystal)]
        default=mp.Medium(index=requirements['top_index'])
    solver=mpb.ModeSolver(geometry_lattice=lattice,geometry=geometry,default_material=default,
        resolution=resolution,num_bands=4,tolerance=1e-9,deterministic=True,mesh_size=7,
        optimize_grid_size=True,filename_prefix=str(out/'mpb-'))
    count={'eigenproblem_solves':0};original_solve=solver.solve_kpoint
    def counted_solve(*args,**kwargs):
        count['eigenproblem_solves']+=1
        return original_solve(*args,**kwargs)
    solver.solve_kpoint=counted_solve;modes=[]
    def capture(ms,band):
        grid=actual_grid(list(ms.mode_solver.get_dims()),[0 if calibration_slab else sx,sy,0],
                         resolution,optimized=ms.optimize_grid_size)
        nx,ny,nz=grid['shape_xyz']
        if nz!=1:raise ValueError('MPB_PROPAGATION_AXIS_NOT_COLLAPSED')
        field=restore_array(ms.get_efield(band,bloch_phase=False),grid,vector=True)
        hfield=restore_array(ms.get_hfield(band,bloch_phase=False),grid,vector=True)
        energy=restore_array(ms.get_dpwr(band),grid,vector=False)
        raw_energy=energy_audit(energy)
        if raw_energy['minimum'] < -1e-12*max(abs(raw_energy['maximum']),np.finfo(float).tiny):
            raise ValueError('MPB_DPWR_SIGNIFICANT_NEGATIVE')
        if raw_energy['raw_sum']<=0:raise ValueError('MPB_DPWR_NONPOSITIVE_TOTAL')
        # Restoring collapsed zero axes is required by the MPB get_dims API.
        x=np.array([0.]) if calibration_slab else (np.arange(nx)/nx-.5)*sx
        y=(np.arange(ny)/ny-.5)*sy;X,Y=np.meshgrid(x,y,indexing='ij')
        core=(abs(X)<=film/2)&(abs(Y)<=width/2) if quarter_turn else (abs(Y)<=film/2)&((abs(X)<=width/2) if not calibration_slab else True)
        boundary=(abs(Y)>.45*sy)|((abs(X)>.45*sx) if not calibration_slab else False)
        density=np.maximum(energy[:,:,0],0);norm=np.sum(abs(field)**2,axis=(0,1,2));fractions=(norm/norm.sum()).tolist()
        kz=float(ms.current_k.z)
        np.savez_compressed(out/f'band-{band}-fields.npz',E=field,H=hfield,electric_energy=energy,x_um=x,y_um=y)
        modes.append({'band':band,'frequency_cycles_per_um':float(ms.freqs[band-1]),'k_cycles_per_um':kz,
            'beta_rad_per_um':float(2*np.pi*kz),'neff':float(kz*wavelength),
            'electric_component_norm_fraction':fractions,'core_electric_energy_fraction':float(density[core].sum()/density.sum()),
            'outer_cell_energy_fraction':float(density[boundary].sum()/density.sum()),
            'field_shape':list(field.shape),'fields_npz':f'band-{band}-fields.npz','solver_iterations_last':ms.iterations,
            'actual_grid':grid,'raw_dpwr_audit':raw_energy,
            'electric_component_fraction_kind':'unweighted E-component L2; not anisotropic electric energy',
            'core_mask_kind':'ridge rectangle only; excludes residual slab outside ridge',
            'fixed_material_df_dk_cycles_per_um_per_cycles_per_um':float(ms.compute_one_group_velocity_component(mp.Vector3(0,0,1),band)),
            'df_dk_is_not_material_dispersive_group_velocity':True})
    upper=max(material['n_o'],material['n_e'])*1.01/wavelength
    roots=solver.find_k(mp.NO_PARITY,1/wavelength,1,4,mp.Vector3(0,0,1),1e-9,2/wavelength,.5/wavelength,upper,capture)
    for m in modes:m['returned_root_cycles_per_um']=float(roots[m['band']-1])
    dominant=1 if quarter_turn else 0
    candidates=[m for m in modes if m['electric_component_norm_fraction'][dominant]>.55 and m['neff']>1.44
        and m['core_electric_energy_fraction']>.35 and m['outer_cell_energy_fraction']<.05]
    selected=max(candidates,key=lambda m:m['neff']) if candidates else None
    result={'kind':'REAL_MPB','geometry':'symmetric-slab-calibration' if calibration_slab else 'rectangular-ridge',
        'geometry_representation':'single-full-film-slab-v1' if calibration_slab else 'non-overlapping-slab-cap-v1',
        'wavelength_um':wavelength,'resolution_pixels_per_um':resolution,'domain_um':[0 if calibration_slab else sx,sy,0],
        'requirements':requirements,'material':material,'meep_version':mp.__version__,'parity':'NO_PARITY',
        'roots_cycles_per_um':list(map(float,roots)),'all_modes':modes,'selected_mode':selected,
        'runtime_build':runtime_build_fingerprint(),
        'solver_configuration':{'eigensolver_tolerance':1e-9,'root_tolerance':1e-9,'mesh_size':7,
            'optimize_grid_size':True,'deterministic':True,'transverse_k':[0,0],
            'wavevector_units':'cycles/um; beta=2*pi*k','frequency_units':'cycles/um',
            'boundary':'transverse periodic supercell; not PML'},
        'selection_is_based_on_field_polarization_localization_and_neff_not_fixed_band':True,
        'verification_status':'NOT_YET_VERIFIED','wall_seconds':time.monotonic()-started,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'field_normalization':'MPB eigenfield normalization, not 1 W',
        'quarter_turn_calibration_only':quarter_turn,'native_dispersive_eigenproblem':False,
        'solver_counts':{'find_k_invocations':1,'requested_bands':4,'eigenproblem_solves':count['eigenproblem_solves'],'fdtd_runs':0}}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def main():
    from photonguard.adapters.mpb_modes import validate_task,plan_checks
    request=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);task=request['task'];step=request['step']
    if set(request)!={'task','step'}:raise ValueError('Worker request scope changed.')
    validate_task(task)
    if step not in plan_checks(task):raise ValueError('Not a predefined numerical check.')
    out.mkdir(parents=True,exist_ok=False)
    solve(step['wavelength_um'],step['resolution'],step['domain_um'],out,task['requirements'])

if __name__=='__main__':main()
