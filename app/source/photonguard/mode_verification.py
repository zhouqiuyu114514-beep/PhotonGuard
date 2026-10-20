"""Field identity and tested-setting sensitivity, not rigorous true-error bounds."""
from pathlib import Path
import math
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from .core import load

def cross_candidate_identity(before,after,policy):
    """Repair must track the same physical field mode, including competing bands."""
    checks=[]
    for path in sorted(Path(before).glob('base-*/result.json')):
        first=load(path);wave=first['wavelength_um'];other=Path(after)/('base-'+str(wave))
        second=load(other/'result.json');a=first['selected_mode'];b=second['selected_mode']
        if a is None or b is None:checks.append({'wavelength_um':wave,'status':'INCONCLUSIVE'});continue
        values=[(m['band'],overlap_squared(path.parent,a,other,m)) for m in second['all_modes']]
        chosen=next(value for band,value in values if band==b['band'])
        margin=chosen-max((value for band,value in values if band!=b['band']),default=0)
        checks.append({'wavelength_um':wave,'overlap_squared':chosen,'identity_margin':margin,
            'old_band':a['band'],'new_band':b['band'],'status':'PASS' if chosen>=policy['min_overlap_squared'] and margin>=policy['min_identity_margin'] else 'INCONCLUSIVE'})
    return {'status':'PASS' if checks and all(c['status']=='PASS' for c in checks) else 'INCONCLUSIVE','checks':checks,
        'band_number_is_not_identity':True}

def overlap_squared(root_a,mode_a,root_b,mode_b):
    with np.load(Path(root_a)/mode_a['fields_npz'],allow_pickle=False) as first, np.load(Path(root_b)/mode_b['fields_npz'],allow_pickle=False) as second:
        a=first['E'][:,:,0,:];b=second['E'][:,:,0,:]
        x,y=first['x_um'],first['y_um'];xx,yy=np.meshgrid(x,y,indexing='ij')
        points=np.stack([xx.ravel(),yy.ravel()],axis=-1)
        interpolator=RegularGridInterpolator((second['x_um'],second['y_um']),b,bounds_error=False,fill_value=0)
        sampled=interpolator(points).reshape(a.shape)
        numerator=abs(np.vdot(a,sampled))**2;denominator=np.vdot(a,a).real*np.vdot(sampled,sampled).real
        return float(numerator/denominator) if denominator>0 else 0

def verify(records,policy):
    checks=[];mode_inputs=[]
    waves=sorted({r['result']['wavelength_um'] for r in records},reverse=True)
    if not waves:return {'verification_status':'INCONCLUSIVE','design_goal_status':'NOT_EVALUATED','checks':[], 'mode_inputs':[], 'reason':'No actual mode evidence'}
    for wavelength in waves:
        group={r['variant']:r for r in records if r['result']['wavelength_um']==wavelength}
        if set(group)!={'base','grid','domain'} or len([r for r in records if r['result']['wavelength_um']==wavelength])!=3:
            checks.append({'id':f'{wavelength}.required_settings','status':'INCONCLUSIVE'});continue
        selected=[group[k]['result'].get('selected_mode') for k in ('base','grid','domain')]
        if any(m is None for m in selected):
            checks.append({'id':f'{wavelength}.mode_identity','status':'INCONCLUSIVE','reason':'No unambiguous guided polarization candidate'});continue
        base,grid,domain=selected
        overlaps=[];margins=[]
        for variant in ('grid','domain'):
            other=group[variant];choice=other['result']['selected_mode']
            values=[(m['band'],overlap_squared(group['base']['path'],base,other['path'],m)) for m in other['result']['all_modes']]
            selected_overlap=next(v for band,v in values if band==choice['band'])
            alternatives=[v for band,v in values if band!=choice['band']]
            overlaps.append(selected_overlap);margins.append(selected_overlap-max(alternatives,default=0))
        identity_ok=min(overlaps)>=policy['min_overlap_squared'] and min(margins)>=policy['min_identity_margin']
        checks.append({'id':f'{wavelength}.mode_identity','status':'PASS' if identity_ok else 'INCONCLUSIVE',
            'overlap_squared':overlaps,'identity_margins':margins,'selected_bands':[m['band'] for m in selected]})
        delta_grid=abs(grid['neff']-base['neff']);delta_domain=abs(domain['neff']-base['neff'])
        numeric_ok=delta_grid<=policy['max_neff_grid_delta'] and delta_domain<=policy['max_neff_domain_delta']
        checks.append({'id':f'{wavelength}.tested_setting_sensitivity','status':'PASS' if numeric_ok else 'FAIL',
            'grid_neff_change':delta_grid,'domain_neff_change':delta_domain,'grid_limit':policy['max_neff_grid_delta'],'domain_limit':policy['max_neff_domain_delta']})
        closure=max(abs(m['frequency_cycles_per_um']-1/wavelength) for m in selected)
        units_ok=all(math.isclose(m['beta_rad_per_um'],2*math.pi*m['k_cycles_per_um'],rel_tol=1e-10)
            and math.isclose(m['neff'],m['k_cycles_per_um']*wavelength,rel_tol=1e-10) for m in selected)
        settings_ok=units_ok and closure<1e-7 and all(m['outer_cell_energy_fraction']<=policy['max_outer_energy_fraction'] for m in selected)
        checks.append({'id':f'{wavelength}.root_and_boundary','status':'PASS' if settings_ok else 'FAIL','frequency_closure':closure,
            'outer_cell_energy_fractions':[m['outer_cell_energy_fraction'] for m in selected],'cycles_to_radians_and_neff_verified':units_ok})
        mode_inputs.append({'wavelength_um':wavelength,'neff':base['neff'],'beta_rad_per_um':base['beta_rad_per_um'],
            'mode_id':f'xcut-yprop-quasiTE-fundamental-{wavelength}',
            'verification_status':'PASS' if identity_ok and numeric_ok and settings_ok else 'INCONCLUSIVE',
            'neff_sensitivity_estimate':max(delta_grid,delta_domain),'selected_band':base['band']})
    states=[c['status'] for c in checks]
    status='FAIL' if 'FAIL' in states else 'INCONCLUSIVE' if 'INCONCLUSIVE' in states or len(mode_inputs)!=len(waves) else 'PASS'
    return {'verification_status':status,'design_goal_status':'NOT_EVALUATED','checks':checks,'mode_inputs':mode_inputs,
        'limitations':['Sensitivity at tested grids and supercells is not a rigorous error bound',
            'Field overlap tracks identity between numerical settings at each wavelength; not a dense wavelength branch scan',
            'Full vector E/H normalization is MPB energy normalization, not 1 W',
            'Synthetic rectangular ridge and artificial nondispersive lower cladding are not a user manufactured device']}
