"""Verify actual Meep FDTD propagation and independent tmm energy conservation."""
import json
import math
import platform
from importlib.metadata import version

import meep as mp
import numpy as np
import tmm
import pytest

mp.verbosity(0)
sim = mp.Simulation(
    cell_size=mp.Vector3(0, 0, 6),
    dimensions=1,
    resolution=20,
    boundary_layers=[mp.PML(1)],
    sources=[mp.Source(mp.GaussianSource(1.0, fwidth=0.2, cutoff=3),
                       component=mp.Ex, center=mp.Vector3(0, 0, -1))],
)
monitor = sim.add_flux(1.0, 0, 1, mp.FluxRegion(center=mp.Vector3(0, 0, 1)))
sim.run(until_after_sources=40)
flux = float(mp.get_fluxes(monitor)[0])
assert math.isfinite(flux) and flux > 0, f"Expected propagated flux; got {flux}"
assert sim.meep_time() > 40, "Real timestep loop did not execute"
steps = int(sim.fields.t)
meep_time = float(sim.meep_time())
sim.reset_meep()

film = tmm.coh_tmm('s', [1, 1.5, 1], [np.inf, 0.5, np.inf], 0, 1.0)
assert abs(film['R'] + film['T'] - 1) < 1e-10
result = {
    'status': 'PASS',
    'python': platform.python_version(),
    'meep': mp.__version__,
    'meep_module': mp.__file__,
    'numpy': np.__version__,
    'tmm': version('tmm'),
    'pytest': pytest.__version__,
    'real_fdtd': {'dimensions': 1, 'resolution': 20, 'steps': steps,
                  'meep_time': meep_time, 'positive_vacuum_flux': flux},
    'tmm_slab': {'R': float(film['R']), 'T': float(film['T']),
                 'energy_sum': float(film['R'] + film['T'])},
}
print(json.dumps(result, indent=2))
