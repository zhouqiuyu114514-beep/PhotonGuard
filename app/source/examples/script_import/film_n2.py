"""Recognized flux-acquisition recipe. Meep units must be confirmed separately.
The importer reads this file as data; it never executes it.
"""
import meep as mp

n = 2.0
d = 0.3
pml = 1.0
air = 3.0
cell_z = d + 2 * air + 2 * pml
resolution = 80
fmin = 1 / 1.7
fmax = 1 / 1.3
fcen = (fmin + fmax) / 2
df = fmax - fmin
nfreq = 41
after = 100
cell = mp.Vector3(0, 0, cell_z)
boundaries = [mp.PML(pml, direction=mp.Z)]
pulse = mp.GaussianSource(fcen, fwidth=2 * df, cutoff=5.0)
source = mp.Source(pulse, component=mp.Ex,
                   center=mp.Vector3(0, 0, -d / 2 - 2), amplitude=1.0)
ref = mp.Simulation(cell_size=cell, dimensions=1, resolution=resolution,
                    Courant=0.5, boundary_layers=boundaries, geometry=[],
                    sources=[source], eps_averaging=True)
rref = ref.add_flux(fcen, df, nfreq,
                     mp.FluxRegion(center=mp.Vector3(0, 0, -d / 2 - 1.5), direction=mp.Z),
                     decimation_factor=1)
tref = ref.add_flux(fcen, df, nfreq,
                     mp.FluxRegion(center=mp.Vector3(0, 0, d / 2 + 1.5), direction=mp.Z),
                     decimation_factor=1)
ref.run(until_after_sources=after)
incident_flux = mp.get_fluxes(tref)
incident_data = ref.get_flux_data(rref)
ref.reset_meep()

layer = mp.Block(size=mp.Vector3(mp.inf, mp.inf, d), center=mp.Vector3(0, 0, 0),
                 material=mp.Medium(index=n))
target = mp.Simulation(cell_size=cell, dimensions=1, resolution=resolution,
                       Courant=0.5, boundary_layers=boundaries, geometry=[layer],
                       sources=[source], eps_averaging=True)
rflux = target.add_flux(fcen, df, nfreq,
                         mp.FluxRegion(center=mp.Vector3(0, 0, -d / 2 - 1.5), direction=mp.Z),
                         decimation_factor=1)
tflux = target.add_flux(fcen, df, nfreq,
                         mp.FluxRegion(center=mp.Vector3(0, 0, d / 2 + 1.5), direction=mp.Z),
                         decimation_factor=1)
target.load_minus_flux_data(rflux, incident_data)
target.run(until_after_sources=after)
reflected_flux = mp.get_fluxes(rflux)
transmitted_flux = mp.get_fluxes(tflux)
frequencies = mp.get_flux_freqs(tflux)
target.reset_meep()
