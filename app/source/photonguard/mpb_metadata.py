"""Actual-axis restoration and diagnostic metadata; no solver construction."""
import hashlib, math, sys
from functools import lru_cache
from pathlib import Path
import numpy as np

def actual_grid(raw_dims, lattice_size, requested_resolution, *, optimized):
    """Restore collapsed axes by lattice semantics, never by nominal round(S*r)."""
    sizes=tuple(lattice_size);dims=list(raw_dims)
    if (len(sizes)!=3 or any(not math.isfinite(s) or s<0 for s in sizes)
        or not dims or any(type(d) is not int or d<1 for d in dims)):
        raise ValueError('MPB_ACTUAL_GRID_SCHEMA')
    active=[i for i,s in enumerate(sizes) if s>0]
    if len(dims)==3:
        full=dims
        if any(full[i]!=1 for i,s in enumerate(sizes) if s==0):
            raise ValueError('MPB_COLLAPSED_AXIS_NONUNIT')
    elif len(dims)==len(active):
        full=[1,1,1]
        for i,d in zip(active,dims):full[i]=d
    else:
        raise ValueError('MPB_ACTUAL_AXIS_AMBIGUOUS')
    return {'backend_get_dims':dims,'axis_order':['x','y','z'],'shape_xyz':full,
        'lattice_size_um':list(sizes),
        'spacing_um':[s/d if s else None for s,d in zip(sizes,full)],
        'nominal_grid_before_optimization':[max(1,math.ceil(s*requested_resolution)) for s in sizes],
        'optimize_grid_size':optimized,'coordinates':'periodic cell centers from -S/2, no duplicated endpoint'}

def restore_array(array, grid, *, vector):
    value=np.asarray(array);shape=tuple(grid['shape_xyz'])+((3,) if vector else ())
    if value.size!=math.prod(shape):raise ValueError('MPB_FIELD_ACTUAL_GRID_MISMATCH')
    if not np.all(np.isfinite(value)):raise ValueError('MPB_FIELD_NONFINITE')
    return value.reshape(shape)

def energy_audit(energy):
    value=np.asarray(energy)
    if value.size==0 or not np.all(np.isfinite(value)):raise ValueError('MPB_ENERGY_NONFINITE')
    return {'finite':True,'minimum':float(value.min()),'maximum':float(value.max()),
        'negative_sample_count':int(np.count_nonzero(value<0)),
        'negative_absolute_sum':float(-value[value<0].sum()),'raw_sum':float(value.sum()),
        'audited_before_display_clipping':True}

@lru_cache(maxsize=1)
def runtime_build_fingerprint():
    import json,meep
    from meep import mpb
    def entry(path):
        p=Path(path).resolve()
        return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    builds=[]
    for p in sorted((Path(sys.prefix)/'conda-meta').glob('*.json')):
        if p.name.startswith(('pymeep-','mpb-','libctl-')):
            data=json.loads(p.read_text());builds.append({'name':data['name'],'version':data['version'],
                'build':data['build'],'metadata':entry(p)})
    paths=set()
    for line in Path('/proc/self/maps').read_text().splitlines():
        name=line.split()[-1]
        if name.startswith('/') and any(k in Path(name).name for k in ('libmeep','libmpb','libctl','_meep')):
            if Path(name).is_file():paths.add(name)
    return {'python':sys.version.split()[0],'meep_version':meep.__version__,
        'modules':[entry(meep.__file__),entry(mpb.__file__)], 'conda_builds':builds,
        'loaded_libraries':[entry(p) for p in sorted(paths)],
        'not_a_claim_of_upstream_binary_identity':True}
