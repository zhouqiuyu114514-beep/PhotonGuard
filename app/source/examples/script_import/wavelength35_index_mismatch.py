"""Recognized flux-acquisition recipe. Meep units must be confirmed separately.
The importer reads this file as data; it never executes it.
"""
import meep as mp

n = 1.4
d = 0.25
pml = 1.0
air = 3.0
cell_z = d + 2 * air + 2 * pml
resolution = 160
fmin = 1 / 1.65
fmax = 1 / 1.35
fcen = (fmin + fmax) / 2
df = fmax - fmin
nfreq = 35
frequencies_for_monitors = [0.6060606060606061, 0.6093189964157706, 0.6126126126126126, 0.6159420289855072, 0.6193078324225865, 0.6227106227106227, 0.6261510128913444, 0.6296296296296297, 0.633147113594041, 0.6367041198501873, 0.64030131826742, 0.6439393939393939, 0.6476190476190475, 0.6513409961685824, 0.6551059730250482, 0.6589147286821706, 0.6627680311890838, 0.6666666666666666, 0.6706114398422091, 0.6746031746031745, 0.6786427145708582, 0.6827309236947791, 0.6868686868686869, 0.6910569105691057, 0.6952965235173825, 0.6995884773662552, 0.7039337474120082, 0.7083333333333333, 0.7127882599580713, 0.7172995780590716, 0.7218683651804672, 0.7264957264957265, 0.7311827956989247, 0.7359307359307359, 0.7407407407407407]
after = 100
cell = mp.Vector3(0, 0, cell_z)
boundaries = [mp.PML(pml, direction=mp.Z)]
pulse = mp.GaussianSource(fcen, fwidth=2 * df, cutoff=5.0)
source = mp.Source(pulse, component=mp.Ex,
                   center=mp.Vector3(0, 0, -d / 2 - 2), amplitude=1.0)
ref = mp.Simulation(cell_size=cell, dimensions=1, resolution=resolution,
                    Courant=0.5, boundary_layers=boundaries, geometry=[],
                    sources=[source], eps_averaging=True)
rref = ref.add_flux(frequencies_for_monitors,
                     mp.FluxRegion(center=mp.Vector3(0, 0, -d / 2 - 1.5), direction=mp.Z),
                     decimation_factor=1)
tref = ref.add_flux(frequencies_for_monitors,
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
rflux = target.add_flux(frequencies_for_monitors,
                         mp.FluxRegion(center=mp.Vector3(0, 0, -d / 2 - 1.5), direction=mp.Z),
                         decimation_factor=1)
tflux = target.add_flux(frequencies_for_monitors,
                         mp.FluxRegion(center=mp.Vector3(0, 0, d / 2 + 1.5), direction=mp.Z),
                         decimation_factor=1)
target.load_minus_flux_data(rflux, incident_data)
target.run(until_after_sources=after)
reflected_flux = mp.get_fluxes(rflux)
transmitted_flux = mp.get_fluxes(tflux)
frequencies = mp.get_flux_freqs(tflux)
target.reset_meep()
