"""Bounded deterministic optical tools; no user code is executed.

Fourier-plane intensities use unit incident irradiance and SI diffraction
scaling. They are never divided by a candidate's peak. Gaussian radii are
1/e^2 intensity radii. These are calibrated ideal models, not certificates.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import time
from pathlib import Path

import numpy as np

SOURCES = {
    'diffraction': ['https://opticspy.github.io/lightpipes/command-reference.html#LightPipes.PipFFT',
                    'https://opticspy.github.io/lightpipes/manual.html'],
    'film': ['https://github.com/sbyrnes321/tmm', 'https://arxiv.org/abs/1603.02720'],
    'gaussian': ['https://opticspy.github.io/lightpipes/command-reference.html#LightPipes.ABCD'],
}
MAX_RESULT_BYTES = 64 * 1024 * 1024
CALIBRATION_TOLERANCES = {'analytic_relative_l2': 0.04, 'resolution_relative_l2': 0.04,
                          'parseval_relative': 1e-10, 'symmetric_relative': 1e-10,
                          'film_energy_absolute': 1e-10, 'gaussian_moments_relative': 1e-10}


def _number(value, name, low=None, high=None, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite number')
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f'{name} must be finite' + (' and positive' if positive else ''))
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f'{name} outside supported range [{low}, {high}]')
    return value


def _required(p, keys, optional=()):
    if not isinstance(p, dict):
        raise ValueError('parameters must be an object')
    missing = set(keys) - set(p)
    extra = set(p) - set(keys) - set(optional)
    if missing or extra:
        raise ValueError(f'parameter fields missing={sorted(missing)} unsupported={sorted(extra)}')


def _check(value, tolerance, note=''):
    return {'passed': bool(value <= tolerance), 'value': float(value),
            'tolerance': float(tolerance), 'note': note}


def _version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _rect_pixels(x, width, center, dx):
    # Exact cell overlap preserves area and phase balance under subpixel shifts.
    return np.clip((np.minimum(x + dx/2, center + width/2) -
                    np.maximum(x - dx/2, center - width/2)) / dx, 0, 1)


def _fft_field(p, n):
    wavelength = p['wavelength_nm'] * 1e-9
    focal = p['focal_length_mm'] * 1e-3
    window = p['window_mm'] * 1e-3
    width = p['slit_width_um'] * 1e-6
    height = p['slit_height_um'] * 1e-6
    separation = p.get('slit_separation_um', 0) * 1e-6
    phase = p.get('relative_phase_rad', 0)
    dx = window/n
    x = (np.arange(n) - n//2) * dx
    if p['aperture'] == 'double_slit':
        ex = (_rect_pixels(x, width, -separation/2, dx) +
              np.exp(1j*phase) * _rect_pixels(x, width, separation/2, dx))
    else:
        ex = _rect_pixels(x, width, 0, dx).astype(complex)
    aperture = np.outer(_rect_pixels(x, height, 0, dx), ex)
    try:
        from LightPipes import Begin, PipFFT
    except ImportError:
        spectrum = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(aperture)))
        engine = 'numpy.fft.fft2 (explicit fallback; LightPipes unavailable)'
        version = np.__version__
    else:
        field = Begin(window, wavelength, n)
        field.field = aperture
        spectrum = PipFFT(field, 1).field
        engine = 'LightPipes.PipFFT / NumPy FFT; ideal lens focal plane'
        version = _version('LightPipes')
    intensity = np.abs(spectrum * dx**2 / (wavelength*focal))**2
    frequency = np.fft.fftshift(np.fft.fftfreq(n, dx))
    screen = frequency * wavelength * focal
    ds = wavelength*focal/window
    input_power = float(np.sum(np.abs(aperture)**2) * dx**2)
    output_power = float(np.sum(intensity) * ds**2)
    analytic_line = (width*height/(wavelength*focal) * np.sinc(width*frequency))**2
    if p['aperture'] == 'double_slit':
        analytic_line *= 2 + 2*np.cos(phase - 2*np.pi*separation*frequency)
    # Central envelope is the declared trustworthy comparison region. High-angle
    # FFT bins are kept as mathematical diagnostics, never a nonparaxial claim.
    region = (np.abs(frequency*width) <= 1) & (np.abs(screen/focal) <= 0.1)
    line = intensity[n//2]
    denom = max(float(np.linalg.norm(analytic_line[region])), np.finfo(float).tiny)
    analytic_error = float(np.linalg.norm(line[region]-analytic_line[region])/denom)
    return {'intensity': intensity, 'line': line, 'screen': screen, 'analytic_line': analytic_line,
            'region': region, 'input_power': input_power, 'output_power': output_power,
            'analytic_error': analytic_error, 'engine': engine, 'version': version, 'dx': dx}


def _diffraction(parameters, *, validate_only=False):
    required = ('aperture', 'wavelength_nm', 'focal_length_mm', 'slit_width_um',
                'slit_height_um', 'grid_size', 'window_mm')
    _required(parameters, required, ('slit_separation_um', 'relative_phase_rad'))
    p = dict(parameters)
    if p['aperture'] not in ('single_slit', 'double_slit'):
        raise ValueError('aperture must be single_slit or double_slit')
    if type(p['grid_size']) is not int or p['grid_size'] not in (256, 512):
        raise ValueError('ordinary grid_size must be 256 or 512; 1024 is internal calibration only')
    for key, bounds in {'wavelength_nm': (200, 2000), 'focal_length_mm': (1, 10000),
                        'slit_width_um': (1, 5000), 'slit_height_um': (1, 10000),
                        'window_mm': (0.01, 20)}.items():
        p[key] = _number(p[key], key, *bounds)
    if p['aperture'] == 'double_slit':
        if 'slit_separation_um' not in p or 'relative_phase_rad' not in p:
            raise ValueError('double_slit needs slit_separation_um and relative_phase_rad')
        p['slit_separation_um'] = _number(p['slit_separation_um'], 'slit_separation_um', 1, 10000)
        p['relative_phase_rad'] = _number(p['relative_phase_rad'], 'relative_phase_rad', -100*math.pi, 100*math.pi)
        if p['slit_separation_um'] <= p['slit_width_um']:
            raise ValueError('double slits must be disjoint (separation > width)')
    elif 'slit_separation_um' in p or 'relative_phase_rad' in p:
        raise ValueError('single_slit does not accept separation or relative phase')
    span_um = p['slit_width_um'] + p.get('slit_separation_um', 0)
    window_um = p['window_mm'] * 1000
    if max(span_um, p['slit_height_um']) > 0.8*window_um:
        raise ValueError('aperture must fit inside 80% of the aperture-plane window')
    dx_um = window_um/p['grid_size']
    if min(p['slit_width_um'], p['slit_height_um'])/dx_um < 8:
        raise ValueError('slit width/height need at least 8 pixels; reduce window or use 512 grid')
    if p['wavelength_nm']*1e-3/min(p['slit_width_um'], p['slit_height_um']) > 0.1:
        raise ValueError('aperture too narrow for the declared paraxial main lobe')
    if validate_only:return p
    base = _fft_field(p, p['grid_size'])
    # One bounded second resolution, 512 or 1024. This is a real additional FFT.
    refined = _fft_field(p, p['grid_size']*2)
    n = p['grid_size']
    refined_common = refined['line'][n//2:3*n//2]
    region = base['region']
    denominator = max(float(np.linalg.norm(refined_common[region])), np.finfo(float).tiny)
    resolution_error = float(np.linalg.norm(base['line'][region]-refined_common[region])/denominator)
    parseval = abs(base['input_power']-base['output_power'])/base['input_power']
    checks = {'analytic_central_envelope': _check(base['analytic_error'], 0.04,
                  'sinc/double-slit formula, same scalar theory; central envelope |x| <= lambda*f/width and |x/f| <= 0.1'),
              'double_resolution': _check(resolution_error, 0.04, f'{n} and {n*2}; agreement, not an asymptotic convergence proof'),
              'parseval_discrete': _check(parseval, 1e-10, 'discrete pixel-averaged field; not exact geometric open area')}
    phase = p.get('relative_phase_rad', 0)
    if abs(math.sin(phase)) <= 1e-12:
        mirrored = np.roll(base['line'][::-1], 1)
        symmetry = float(np.max(np.abs(base['line']-mirrored))/max(float(np.max(base['line'])), 1e-300))
        checks['symmetry'] = _check(symmetry, 1e-10, 'applicable for symmetric aperture at phase 0 or pi')
    wavelength = p['wavelength_nm']*1e-9
    focal = p['focal_length_mm']*1e-3
    area = p['slit_width_um']*p['slit_height_um']*1e-12*(2 if p['aperture']=='double_slit' else 1)
    coherent_reference = (area/(wavelength*focal))**2
    central = float(base['line'][n//2])
    metrics = {'central_intensity': central, 'peak_intensity': float(np.max(base['intensity'])),
               'central_intensity_ratio': central/coherent_reference,
               'input_power_m2': base['input_power'], 'output_power_m2': base['output_power'],
               'first_zero_mm': wavelength*focal/(p['slit_width_um']*1e-6)*1000,
               'analytic_relative_l2': base['analytic_error'], 'resolution_relative_l2': resolution_error}
    if p['aperture'] == 'double_slit':
        metrics['fringe_period_mm'] = wavelength*focal/(p['slit_separation_um']*1e-6)*1000
    return {'engine': {'name': base['engine'], 'version': base['version'], 'numpy': np.__version__},
            'parameters': p,
            'assumptions': ['coherent unit incident irradiance; ideal thin lens focal plane',
                            'scalar paraxial rectangular apertures; no material phase-plate design',
                            'true 2D FFT of pixel-area averaged aperture; main-lobe calibration',
                            'intensity is relative to unit incident irradiance, no per-candidate peak normalization',
                            'central_intensity_ratio uses the same-geometry zero-phase coherent reference',
                            'fringe_period_mm and first_zero_mm are analytic geometry-derived metrics, not peak-fit measurements',
                            'high-angle FFT bins are diagnostic only; |x/f| and |y/f| <= 0.1 are the paraxial display region'],
            'metrics': metrics, 'checks': checks,
            'data': {'x_mm': (base['screen']*1000).tolist(), 'y_mm': (base['screen']*1000).tolist(),
                     'intensity_2d': base['intensity'].tolist(), 'centerline_intensity': base['line'].tolist(),
                     'analytic_centerline_intensity': base['analytic_line'].tolist(),
                     'incident_intensity': 1.0, 'normalization': 'incident_irradiance_one',
                     'paraxial_max_abs_x_mm': 0.1*p['focal_length_mm'],
                     'display_scale_policy': 'same linear intensity scale across compared candidates'},
            'resources': {'field_calculations': 2, 'grid_sizes': [n, n*2],
                          'main_grid_points': n*n, 'calibration_grid_points': 4*n*n,
                          'final_fdtd_runs': 0, 'declared_memory_ceiling_bytes': 1024**3}}


def _film(parameters, *, validate_only=False):
    _required(parameters, ('layers', 'wavelengths_um'))
    layers = parameters['layers']
    if not isinstance(layers, list) or not 1 <= len(layers) <= 8:
        raise ValueError('layers must have 1 to 8 entries')
    normalized = []
    for layer in layers:
        _required(layer, ('n', 'thickness_um'))
        normalized.append({'n': _number(layer['n'], 'n', 1, 5),
                           'thickness_um': _number(layer['thickness_um'], 'thickness_um', 0.02, 5)})
    if sum(layer['thickness_um'] for layer in normalized) > 5 + 1e-12:
        raise ValueError('total layer thickness must be <= 5 um')
    wave = parameters['wavelengths_um']
    if not isinstance(wave, list) or not 1 <= len(wave) <= 201:
        raise ValueError('wavelengths_um must have 1 to 201 explicit points')
    wave = [_number(x, 'wavelengths_um', 0.5, 5) for x in wave]
    if any(a >= b for a, b in zip(wave, wave[1:])):
        raise ValueError('wavelengths_um must be strictly increasing and unique')
    if validate_only:return {'layers':normalized,'wavelengths_um':wave}
    from tmm import coh_tmm
    ns = [1.0] + [layer['n'] for layer in normalized] + [1.0]
    ds = [np.inf] + [layer['thickness_um'] for layer in normalized] + [np.inf]
    records = [coh_tmm('s', ns, ds, 0.0, x) for x in wave]
    reflectance = np.array([float(r['R']) for r in records])
    transmittance = np.array([float(r['T']) for r in records])
    absorbance = 1-reflectance-transmittance
    energy_error = float(np.max(np.abs(absorbance)))
    bounds_error = float(max(0, -np.min(reflectance), np.max(reflectance)-1,
                             -np.min(transmittance), np.max(transmittance)-1))
    metrics = {}
    for name, values in (('reflectance', reflectance), ('transmittance', transmittance)):
        for operation in ('min', 'mean', 'max'):
            metrics[f'{name}_{operation}'] = float(getattr(np, operation)(values))
    metrics.update(layer_count=len(normalized), total_thickness_um=sum(layer['thickness_um'] for layer in normalized))
    return {'engine': {'name': 'tmm.coh_tmm', 'version': _version('tmm'), 'numpy': np.__version__},
            'parameters': {'layers': normalized, 'wavelengths_um': wave},
            'assumptions': ['normal incidence; air on both sides; nonmagnetic isotropic lossless nondispersive layers',
                            'coherent 1D transfer matrix; wavelength goals use explicit evaluated points',
                            'min/mean/max refer only to the listed samples, not continuous bandwidth',
                            'fast candidate calculation; independent Meep validation is a separate action'],
            'metrics': metrics, 'data': {'wavelengths_um': wave, 'R': reflectance.tolist(),
                                         'T': transmittance.tolist(), 'A': absorbance.tolist()},
            'checks': {'energy_balance': _check(energy_error, 1e-10),
                       'physical_bounds': _check(bounds_error, 1e-10)},
            'resources': {'tmm_wavelength_calculations': len(wave), 'field_calculations': 0, 'final_fdtd_runs': 0}}


def _gaussian(parameters, *, validate_only=False):
    keys = ('wavelength_nm', 'waist_radius_um', 'waist_z_mm', 'focal_length_mm',
            'screen_distance_mm', 'z_max_mm')
    _required(parameters, keys)
    bounds = {'wavelength_nm': (200, 2000), 'waist_radius_um': (1, 10000),
              'waist_z_mm': (-10000, 10000), 'focal_length_mm': (-10000, 10000),
              'screen_distance_mm': (0, 10000), 'z_max_mm': (0.001, 10000)}
    p = {key: _number(parameters[key], key, *bounds[key]) for key in keys}
    if abs(p['focal_length_mm']) < 1:
        raise ValueError('absolute focal_length_mm must be >= 1')
    if p['z_max_mm'] < p['screen_distance_mm']:
        raise ValueError('z_max_mm must include the screen')
    wavelength = p['wavelength_nm']*1e-9
    w0 = p['waist_radius_um']*1e-6
    waist_z = p['waist_z_mm']*1e-3
    focal = p['focal_length_mm']*1e-3
    rayleigh = math.pi*w0*w0/wavelength
    q_in = complex(-waist_z, rayleigh)
    q_after = q_in/(1-q_in/focal)
    new_waist_radius = math.sqrt(wavelength*q_after.imag/math.pi)
    divergence = wavelength/(math.pi*new_waist_radius)
    if max(wavelength/(math.pi*w0), divergence) > 0.1:
        raise ValueError('input or transformed divergence exceeds the supported 0.1 rad paraxial range')
    if validate_only:return p
    # Include the exact requested screen, no interpolation for goal evaluation.
    z = np.unique(np.r_[np.linspace(0, p['z_max_mm']*1e-3, 201), p['screen_distance_mm']*1e-3])
    q = q_after+z
    radius = np.sqrt(wavelength/(-math.pi*np.imag(1/q)))
    screen_q = q_after+p['screen_distance_mm']*1e-3
    screen_radius = math.sqrt(wavelength/(-math.pi*(1/screen_q).imag))
    # Independent algebraic implementation of the same Gaussian/ABCD theory.
    a = 1-z/focal
    b = z-a*waist_z
    moment_radius = np.sqrt((a*w0)**2 + (b*wavelength/(math.pi*w0))**2)
    moment_error = float(np.max(np.abs(radius-moment_radius)/moment_radius))
    metrics = {'screen_radius_um': screen_radius*1e6, 'new_waist_radius_um': new_waist_radius*1e6,
               'new_waist_z_mm': -q_after.real*1000, 'waist_radius_um': new_waist_radius*1e6,
               'divergence_rad': divergence, 'input_rayleigh_range_mm': rayleigh*1000,
               'screen_radius_second_moment_um': float(np.interp(p['screen_distance_mm']*1e-3, z, moment_radius)*1e6)}
    return {'engine': {'name': 'Gaussian q / ABCD (deterministic NumPy)', 'version': '1', 'numpy': np.__version__},
            'parameters': p,
            'assumptions': ['ideal TEM00; M2=1; air; one ideal thin lens at z=0',
                            'radius means 1/e^2 intensity radius, not diameter',
                            'waist_z_mm is the signed incident-beam waist position relative to the lens',
                            'ideal paraxial propagation; no aberration, clipping, material damage or real-lens certification',
                            'new_waist_z_mm may be negative (virtual/upstream waist); curve covers z>=0'],
            'metrics': metrics, 'data': {'z_mm': (z*1000).tolist(), 'radius_um': (radius*1e6).tolist(),
                                        'screen_distance_mm': p['screen_distance_mm'],
                                        'q_before_lens_m': [q_in.real, q_in.imag],
                                        'q_after_lens_m': [q_after.real, q_after.imag]},
            'checks': {'second_moment_same_theory': _check(moment_error, 1e-10,
                       'implementation calibration within the same paraxial theory; not independent scientific certification')},
            'resources': {'abcdn_points': len(z), 'field_calculations': 0, 'final_fdtd_runs': 0}}


def validate_parameters(domain, parameters):
    """Use the solver's own support checks without FFT, TMM, Meep or field output."""
    adapters={'film':_film,'diffraction':_diffraction,'gaussian':_gaussian}
    if domain not in adapters:raise ValueError('unsupported optical domain')
    return adapters[domain](parameters,validate_only=True)


def evaluate(domain, parameters, output_dir=None):
    """Execute one whitelisted ideal optical model; return a JSON-compatible record.

    Diffraction includes a second-resolution check, so one candidate costs two
    field calculations. A supplied output_dir must be caller-owned and empty
    with respect to optics-result.json; existing evidence is never overwritten.
    """
    adapters = {'film': _film, 'diffraction': _diffraction, 'gaussian': _gaussian}
    if domain not in adapters:
        raise ValueError('unsupported optical domain')
    started = time.perf_counter()
    result = adapters[domain](parameters)
    result.update(schema='photonguard.optics.v1', domain=domain,
                  validation_level='MODEL_CALIBRATION_NOT_CERTIFICATION',
                  sources=SOURCES[domain],
                  all_checks_passed=all(item['passed'] for item in result['checks'].values()))
    # Shared presentation contract; physical arrays remain available verbatim.
    data = result['data']
    resources = result['resources']
    resources['worker_count'] = 1
    resources['fast_evaluations'] = 2 if domain == 'diffraction' else 1
    if domain == 'film':
        data.update(x=data['wavelengths_um'], x_label='Wavelength (um)', y_label='Power fraction',
                    series=[{'label': 'R', 'y': data['R']}, {'label': 'T', 'y': data['T']}])
        resources['scalar_calculations'] = len(data['wavelengths_um'])
    elif domain == 'gaussian':
        data.update(x=data['z_mm'], x_label='Distance after lens (mm)', y_label='1/e^2 intensity radius (um)',
                    series=[{'label': 'Beam radius', 'y': data['radius_um']}])
        resources['scalar_calculations'] = len(data['z_mm'])
    else:
        indices = [i for i, x in enumerate(data['x_mm']) if abs(x) <= data['paraxial_max_abs_x_mm']]
        screen = [data['x_mm'][i] for i in indices]
        shown_intensity = [[data['intensity_2d'][j][i] for i in indices] for j in indices]
        data.update(x=screen, x_label='Focal-plane x (mm)', y_label='Intensity / incident irradiance',
                    series=[{'label': 'FFT center line', 'y': [data['centerline_intensity'][i] for i in indices]},
                            {'label': 'Analytic center line', 'y': [data['analytic_centerline_intensity'][i] for i in indices]}],
                    image={'x': screen, 'y': screen, 'values': shown_intensity,
                           'normalization_label': 'Unit incident irradiance; common linear scale across candidates',
                           'x_label': 'Focal-plane x (mm)', 'y_label': 'Focal-plane y (mm)',
                           'suggested_linear_vmin': 0.0,
                           'candidate_physical_peak': result['metrics']['peak_intensity'],
                           'comparison_vmax_rule': 'max(candidate_physical_peak over the whole compared batch)'})
    result['resources']['elapsed_seconds'] = time.perf_counter()-started
    # Disallow NaN/Infinity and cap the actual UTF-8 JSON representation.
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError('optics result exceeds 64 MiB limit')
    result['resources']['json_bytes_before_artifact_metadata'] = len(encoded)
    if output_dir is not None:
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder/'optics-result.json'
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        with destination.open('xb') as stream:
            stream.write(encoded)
        result['artifacts'] = [{'name': destination.name, 'sha256': hashlib.sha256(encoded).hexdigest(), 'bytes': len(encoded)}]
    return result
