"""Read-only E/H shape diagnostics, separate from frozen production identity v1.

No beta error bound, power normalization, E/H concatenation, or new PASS receipt.
Periodic interpolation is supported only for transverse kx=ky=0.
"""
from pathlib import Path
import hashlib,math
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from .mpb_metadata import energy_audit

def load_fields(path):
    with np.load(path,allow_pickle=False) as data:
        if set(data.files)!={'E','H','electric_energy','x_um','y_um'}:
            raise ValueError('RESEARCH_FIELD_KEYS')
        result={name:np.array(data[name],copy=True) for name in data.files}
    x,y=result['x_um'],result['y_um'];expected=(len(x),len(y),1,3)
    if (x.ndim!=1 or y.ndim!=1 or len(x)<2 or len(y)<2
        or not np.all(np.diff(x)>0) or not np.all(np.diff(y)>0)
        or result['E'].shape!=expected or result['H'].shape!=expected
        or result['electric_energy'].shape!=expected[:3]
        or any(not np.all(np.isfinite(v)) for v in result.values())):
        raise ValueError('RESEARCH_FIELD_SHAPE_OR_FINITE')
    return result

def audit_field_file(path,mode,domain):
    values=load_fields(path);x,y=values['x_um'],values['y_um']
    if list(values['E'].shape)!=mode['field_shape']:raise ValueError('RESEARCH_FIELD_MODE_SHAPE')
    for axis,size in ((x,domain[0]),(y,domain[1])):
        expected=(np.arange(len(axis))/len(axis)-.5)*size
        if not np.allclose(axis,expected,rtol=0,atol=1e-12):raise ValueError('RESEARCH_FIELD_COORDINATES')
    return {'filename':Path(path).name,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        'shape':list(values['E'].shape),'finite':True,'axis_ranges_um':[[float(x[0]),float(x[-1])],[float(y[0]),float(y[-1])]],
        'spacing_um':[float(x[1]-x[0]),float(y[1]-y[0])],
        'electric_energy_raw':energy_audit(values['electric_energy']),
        'electric_component_L2_fraction':(np.sum(abs(values['E'])**2,axis=(0,1,2))/np.sum(abs(values['E'])**2)).tolist(),
        'effective_tensor_component_energy_fraction':'UNAVAILABLE: D/effective epsilon tensor not saved; E L2 is not electric energy',
        'core_mask_meaning':'ridge rectangle only; excludes residual slab outside ridge'}

def _period(axis):
    # Averaging across the full span avoids amplifying cancellation in the first
    # adjacent difference: the r80 4 um grid otherwise becomes 3.999999999999986.
    return float((axis[-1]-axis[0])*len(axis)/(len(axis)-1))

def _window_axis_mask(axis,bounds):
    # Coordinates and bounds can reach the same physical endpoint through
    # slightly different floating arithmetic. Snap only roundoff-scale ties;
    # retain lower-inclusive, upper-exclusive semantics for genuine cropping.
    lower,upper=bounds
    tolerance=16*np.finfo(float).eps*max(1.,abs(lower),abs(upper),float(np.max(abs(axis))))
    return (axis>=lower-tolerance)&(axis<upper-tolerance)

def _sample_periodic(values,key,points,shift):
    x,y=values['x_um'],values['y_um'];sx,sy=_period(x),_period(y)
    coordinates=points.copy()
    coordinates[:,0]=(coordinates[:,0]+shift[0]-x[0])%sx+x[0]
    coordinates[:,1]=(coordinates[:,1]+shift[1]-y[0])%sy+y[0]
    arr=values[key][:,:,0,:]
    arr=np.concatenate((arr,arr[:1,:,:]),axis=0)
    arr=np.concatenate((arr,arr[:,:1,:]),axis=1)
    return RegularGridInterpolator((np.r_[x,x[0]+sx],np.r_[y,y[0]+sy]),arr,
        bounds_error=True)(coordinates)

def _overlap(a,b,weight=None):
    w=1 if weight is None else weight
    inner=np.sum(np.conj(a)*w*b);na=float(np.sum(abs(a)**2*w));nb=float(np.sum(abs(b)**2*w))
    if na<=0 or nb<=0:raise ValueError('RESEARCH_ZERO_FIELD_NORM')
    score=float(abs(inner)**2/(na*nb))
    if not math.isfinite(score) or score>1+1e-10:raise ValueError('RESEARCH_OVERLAP_RANGE')
    return {'squared_normalized_overlap':min(1.,score),'global_phase_alignment_rad':float(np.angle(inner))}

def _window_fractions(values,bounds):
    x,y=values['x_um'],values['y_um'];X,Y=np.meshgrid(x,y,indexing='ij')
    mask=_window_axis_mask(x,bounds[0])[:,None]&_window_axis_mask(y,bounds[1])[None,:]
    result={}
    for key in ('E','H'):
        density=np.sum(abs(values[key][:,:,0,:])**2,axis=-1)
        total=float(density.sum())
        if total<=0:raise ValueError('RESEARCH_ZERO_FIELD_NORM')
        fraction=float(density[mask].sum()/total)
        result[key+'_L2_window_fraction']=fraction;result[key+'_L2_tail_fraction']=1-fraction
    raw=values['electric_energy'][:,:,0];audit=energy_audit(raw)
    if audit['minimum']<0:
        result['electric_energy_window_fraction']=None
        result['energy_fraction_reason']='Raw negative dpwr retained; no silently clipped energy fraction'
    elif audit['raw_sum']<=0:raise ValueError('RESEARCH_ZERO_ENERGY')
    else:
        fraction=float(raw[mask].sum()/raw.sum())
        result['electric_energy_window_fraction']=fraction;result['electric_energy_tail_fraction']=1-fraction
    result['raw_energy_audit']=audit
    return result

def common_bulk_weight(x,y,requirements,material):
    """One shared positive continuous bulk tensor, not MPB's interface tensor."""
    X,Y=np.meshgrid(x,y,indexing='ij');film=requirements['film_thickness_um']
    slab=requirements['slab_thickness_um'];width=requirements['ridge_width_um']
    eps=np.ones(X.shape+(3,))*requirements['top_index']**2
    eps[Y<-film/2]=requirements['bottom_index']**2
    ln=((Y>=-film/2)&(Y<-film/2+slab))|((abs(X)<width/2)&(abs(Y)<film/2))
    eps[ln]=np.diag(np.asarray(material['laboratory_epsilon']))
    if not np.all(eps>0):raise ValueError('RESEARCH_NONPOSITIVE_WEIGHT')
    return eps

def pair_metrics(first,second,*,weight=None,shift_um=(0.,0.),transverse_k=(0.,0.)):
    if len(transverse_k)!=2 or any(k!=0 for k in transverse_k):raise ValueError('RESEARCH_NONZERO_TRANSVERSE_BLOCH_NOT_SUPPORTED')
    if len(shift_um)!=2 or any(not math.isfinite(s) for s in shift_um):raise ValueError('RESEARCH_SHIFT_SCHEMA')
    xa,ya=first['x_um'],first['y_um'];xb,yb=second['x_um'],second['y_um']
    bounds=[[-min(_period(xa),_period(xb))/2,min(_period(xa),_period(xb))/2],
            [-min(_period(ya),_period(yb))/2,min(_period(ya),_period(yb))/2]]
    ix=_window_axis_mask(xa,bounds[0]);iy=_window_axis_mask(ya,bounds[1])
    if not ix.any() or not iy.any():raise ValueError('RESEARCH_EMPTY_PHYSICAL_WINDOW')
    X,Y=np.meshgrid(xa[ix],ya[iy],indexing='ij');points=np.stack((X.ravel(),Y.ravel()),axis=-1)
    scores={};sampled={}
    for key in ('E','H'):
        a=first[key][ix][:,iy,0,:];b=_sample_periodic(second,key,points,shift_um).reshape(a.shape)
        scores[key+'_L2_overlap_research']=_overlap(a,b);sampled[key]=(a,b)
    if weight is not None:
        w=np.asarray(weight)
        if w.shape!=first['E'][:,:,0,:].shape or not np.all(np.isfinite(w)) or not np.all(w>0):
            raise ValueError('RESEARCH_COMMON_WEIGHT_INVALID')
        scores['E_common_positive_bulk_weight_overlap']=_overlap(*sampled['E'],w[ix][:,iy,:])
    phase=scores['E_L2_overlap_research']['global_phase_alignment_rad']
    hphase=scores['H_L2_overlap_research']['global_phase_alignment_rad']
    return {'metrics':scores,'common_physical_window_um':bounds,'integration_grid_shape':list(X.shape),
        'research_window_version':'periodic-window-v2-span-average-endpoint-roundoff',
        'window_endpoint_policy':'lower-inclusive upper-exclusive; 16 float64 eps times coordinate scale',
        'first_native_window_and_tail':_window_fractions(first,bounds),
        'second_native_window_and_tail':_window_fractions(second,bounds),
        'reverse_geometry_translation_sampling_um':list(shift_um),
        'common_E_global_phase_alignment_applies_to_H':True,
        'H_minus_E_phase_residual_rad':float(np.angle(np.exp(1j*(hphase-phase)))),
        'interpolation':'periodic bilinear complex field interpolation; kx=ky=0 only',
        'weight_kind':'shared continuous bulk epsilon diagonal, not effective interface tensor' if weight is not None else None,
        'not_power_or_mode_orthogonality':True,'not_a_true_beta_error_bound':True}

def competitor_matrices(first_root,first_result,second_root,second_result):
    a={m['band']:load_fields(Path(first_root)/m['fields_npz']) for m in first_result['all_modes']}
    b={m['band']:load_fields(Path(second_root)/m['fields_npz']) for m in second_result['all_modes']}
    rows=[]
    for ba,fa in a.items():
        weight=common_bulk_weight(fa['x_um'],fa['y_um'],first_result['requirements'],first_result['material'])
        for bb,fb in b.items():
            rows.append({'first_band':ba,'second_band':bb,**pair_metrics(fa,fb,weight=weight)})
    return {'first_selected_band':first_result['selected_mode']['band'],
        'second_selected_band':second_result['selected_mode']['band'],'all_competing_band_pairs':rows,
        'candidate_set':'four computed bands only; not proof of complete spectrum',
        'does_not_change_production_E_L2_overlap_v1':True}
