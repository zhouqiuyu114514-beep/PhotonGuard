"""Recognized flux-acquisition recipe. Meep units must be confirmed separately.
The importer reads this file as data; it never executes it.
"""
import meep as mp

n = 3.4
d = 0.8
pml = 1.0
air = 3.0
cell_z = d + 2 * air + 2 * pml
resolution = 80
fmin = 1 / 1.1
fmax = 1 / 0.8
fcen = (fmin + fmax) / 2
df = fmax - fmin
nfreq = 35
frequencies_for_monitors = [0.9090909090909091, 0.9164420485175201, 0.9239130434782608, 0.9315068493150683, 0.9392265193370166, 0.947075208913649, 0.9550561797752809, 0.9631728045325778, 0.9714285714285713, 0.9798270893371757, 0.9883720930232559, 0.9970674486803519, 1.0059171597633136, 1.0149253731343284, 1.0240963855421685, 1.0334346504559269, 1.0429447852760736, 1.0526315789473684, 1.0625, 1.0725552050473186, 1.0828025477707006, 1.0932475884244373, 1.1038961038961037, 1.1147540983606556, 1.1258278145695364, 1.137123745819398, 1.1486486486486487, 1.1604095563139931, 1.1724137931034482, 1.1846689895470381, 1.1971830985915493, 1.2099644128113878, 1.223021582733813, 1.2363636363636363, 1.25]
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
