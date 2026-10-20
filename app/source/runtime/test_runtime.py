"""Isolated runtime checks, separate from PhotonGuard application tests."""
import importlib.metadata
import math
import meep as mp
import numpy as np
import tmm


def test_meep_real_fdtd():
    mp.verbosity(0)
    sim = mp.Simulation(cell_size=mp.Vector3(0, 0, 6), dimensions=1,
        resolution=20, boundary_layers=[mp.PML(1)],
        sources=[mp.Source(mp.GaussianSource(1, fwidth=0.2, cutoff=3),
                   component=mp.Ex, center=mp.Vector3(0, 0, -1))])
    monitor = sim.add_flux(1, 0, 1, mp.FluxRegion(center=mp.Vector3(0, 0, 1)))
    sim.run(until_after_sources=40)
    flux = mp.get_fluxes(monitor)[0]
    assert sim.fields.t == 2800
    assert math.isfinite(flux) and flux > 0
    sim.reset_meep()


def test_tmm_energy_conservation():
    film = tmm.coh_tmm('s', [1, 1.5, 1], [np.inf, 0.5, np.inf], 0, 1.0)
    assert abs(film['R'] + film['T'] - 1) < 1e-10


def test_pinned_solver_versions():
    assert mp.__version__ == '1.34.0'
    assert importlib.metadata.version('tmm') == '0.2.0'
