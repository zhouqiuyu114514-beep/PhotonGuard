"""Calibration of ideal models; equality within one theory is not certification."""
import builtins
import json
import math

import numpy as np
import pytest

from photonguard.experiments.optics import evaluate


def slit(**changes):
    p = dict(aperture='double_slit', wavelength_nm=633, focal_length_mm=200,
             slit_width_um=20, slit_height_um=100, slit_separation_um=126.6,
             relative_phase_rad=0, grid_size=256, window_mm=.5)
    p.update(changes)
    return p


def gaussian(**changes):
    p = dict(wavelength_nm=633, waist_radius_um=500, waist_z_mm=0,
             focal_length_mm=100, screen_distance_mm=100, z_max_mm=200)
    p.update(changes)
    return p


def stack(count, center=.633):
    return [{'n': n, 'thickness_um': center/(4*n)} for n in [2.4, 1.45]*(count//2)]


def test_single_slit_sinc_parseval_and_symmetry():
    p = slit(aperture='single_slit')
    del p['slit_separation_um'], p['relative_phase_rad']
    result = evaluate('diffraction', p)
    assert result['all_checks_passed']
    assert result['checks']['analytic_central_envelope']['value'] < .01
    assert result['checks']['double_resolution']['value'] < .01
    assert result['metrics']['first_zero_mm'] == pytest.approx(6.33)
    image = np.array(result['data']['intensity_2d'])
    assert image.shape == (256, 256)
    assert np.ptp(image[:, 128]) > 0  # actual two-dimensional finite height
    x = np.array(result['data']['x_mm'])*1e-3
    wavelength, focal, width, height = 633e-9, .2, 20e-6, 100e-6
    analytic = (width*height/(wavelength*focal))**2 * np.outer(
        np.sinc(height*x/(wavelength*focal))**2,
        np.sinc(width*x/(wavelength*focal))**2)
    central = np.outer(np.abs(height*x/(wavelength*focal)) <= 1,
                       np.abs(width*x/(wavelength*focal)) <= 1)
    assert np.linalg.norm((image-analytic)[central])/np.linalg.norm(analytic[central]) < .01
    assert result['resources']['field_calculations'] == 2


@pytest.mark.parametrize('phase,ratio', [(0, 1), (math.pi/2, .5), (math.pi, 0)])
def test_double_slit_analytic_phase_and_same_normalization(phase, ratio):
    result = evaluate('diffraction', slit(relative_phase_rad=phase))
    assert result['all_checks_passed']
    assert result['metrics']['fringe_period_mm'] == pytest.approx(1)
    assert result['metrics']['central_intensity_ratio'] == pytest.approx(ratio, abs=1e-12)
    assert result['data']['normalization'] == 'incident_irradiance_one'
    assert result['metrics']['central_intensity'] == pytest.approx(ratio * .00099828046190437, abs=1e-14)
    if phase == math.pi/2:
        assert 'symmetry' not in result['checks']


def test_phase_revision_does_not_change_geometry_or_power():
    original = slit()
    dark = dict(original, relative_phase_rad=math.pi)
    a, b = evaluate('diffraction', original), evaluate('diffraction', dark)
    for key in original:
        if key != 'relative_phase_rad':
            assert a['parameters'][key] == b['parameters'][key]
    assert b['metrics']['central_intensity'] < a['metrics']['central_intensity']*1e-20
    assert a['metrics']['input_power_m2'] == pytest.approx(b['metrics']['input_power_m2'])
    assert a['metrics']['output_power_m2'] == pytest.approx(b['metrics']['output_power_m2'])


def test_diffraction_two_resolutions_and_json_budget():
    result = evaluate('diffraction', slit(grid_size=512))
    assert result['all_checks_passed']
    assert result['resources']['grid_sizes'] == [512, 1024]
    assert len(json.dumps(result, allow_nan=False).encode()) < 64*1024**2


def test_numpy_fallback_is_named_and_numerically_equal(monkeypatch):
    reference = evaluate('diffraction', slit())
    real_import = builtins.__import__
    def without_lightpipes(name, *args, **kwargs):
        if name == 'LightPipes':
            raise ImportError('test optional dependency absence')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_lightpipes)
    fallback = evaluate('diffraction', slit())
    assert 'fallback' in fallback['engine']['name']
    assert np.allclose(reference['data']['intensity_2d'], fallback['data']['intensity_2d'])


@pytest.mark.parametrize('bad', [dict(grid_size=1024), dict(grid_size=True), dict(window_mm=2),
                                dict(slit_separation_um=10), dict(slit_width_um=float('nan')),
                                dict(focal_length_mm=float('inf')), dict(arbitrary_script='print(1)')])
def test_diffraction_rejects_unsupported_or_underresolved_parameters(bad):
    with pytest.raises(ValueError):
        evaluate('diffraction', slit(**bad))


@pytest.mark.parametrize('n,thickness', [(1.45, .21), (2, .3), (2.4, .51)])
def test_single_film_against_airy_expression(n, thickness):
    wave = [.5, .55, .633, 1.1, 1.55]
    result = evaluate('film', {'layers': [{'n': n, 'thickness_um': thickness}], 'wavelengths_um': wave})
    factor = (n*n-1)**2/(4*n*n)
    s = np.sin(2*np.pi*n*thickness/np.array(wave))**2
    expected = factor*s/(1+factor*s)
    assert np.allclose(result['data']['R'], expected, atol=1e-12, rtol=1e-12)
    assert result['all_checks_passed']


def test_film_index_matched_layer_has_no_reflection():
    result = evaluate('film', {'layers': [{'n': 1, 'thickness_um': 1}], 'wavelengths_um': [.633, 1.55]})
    assert max(result['data']['R']) == pytest.approx(0, abs=1e-14)
    assert result['data']['T'] == pytest.approx([1, 1])


def test_quarter_wave_stack_reference_and_finite_comparison():
    results = []
    for count in (2, 4, 6, 8):
        result = evaluate('film', {'layers': stack(count), 'wavelengths_um': [.633]})
        admittance = (2.4/1.45)**count
        expected = ((admittance-1)/(admittance+1))**2
        assert result['data']['R'][0] == pytest.approx(expected, abs=1e-12)
        assert result['all_checks_passed']
        results.append(result)
    winner = max(results, key=lambda x:x['metrics']['reflectance_min'])
    assert winner['metrics']['layer_count'] == 8
    limited = [r for r in results if r['metrics']['layer_count'] <= 6]
    assert max(limited, key=lambda x:x['metrics']['reflectance_min'])['metrics']['layer_count'] == 6
    assert winner['resources']['final_fdtd_runs'] == 0  # tmm is not Meep validation


@pytest.mark.parametrize('parameters', [
    {'layers': stack(10), 'wavelengths_um': [.633]},
    {'layers': [{'n':2,'thickness_um':6}], 'wavelengths_um': [.633]},
    {'layers': [{'n':2,'thickness_um':3}]*2, 'wavelengths_um': [.633]},
    {'layers': stack(2), 'wavelengths_um': [.633,.633]},
    {'layers': stack(2), 'wavelengths_um': [.8,.633]},
    {'layers': stack(2), 'wavelengths_um': np.linspace(.5,1,202).tolist()},
    {'layers': [{'n':2+1j,'thickness_um':.1}], 'wavelengths_um': [.633]},
])
def test_film_limits(parameters):
    with pytest.raises(ValueError):
        evaluate('film', parameters)


@pytest.mark.parametrize('focal,expected', [(100,40.29803159), (150,171.46926584), (200,253.22703519)])
def test_gaussian_screen_reference(focal, expected):
    result = evaluate('gaussian', gaussian(focal_length_mm=focal))
    assert result['metrics']['screen_radius_um'] == pytest.approx(expected, rel=1e-9)
    assert result['all_checks_passed']
    idx = result['data']['z_mm'].index(100)
    assert result['data']['radius_um'][idx] == pytest.approx(expected, rel=1e-9)


@pytest.mark.parametrize('waist_z,focal', [(-120,150), (80,200), (-100,-150)])
def test_gaussian_nonzero_waist_against_lightpipes_abcd(waist_z, focal):
    lp = pytest.importorskip('LightPipes')
    p = gaussian(waist_z_mm=waist_z, focal_length_mm=focal)
    result = evaluate('gaussian', p)
    field = lp.Begin(.01, p['wavelength_nm']*1e-9, 64)
    field = lp.GaussBeam(field, p['waist_radius_um']*1e-6)
    field = lp.ABCD(field, [[1, -waist_z*1e-3], [0,1]])
    field = lp.ABCD(field, [[1,0], [-1/(focal*1e-3),1]])
    field = lp.ABCD(field, [[1,p['screen_distance_mm']*1e-3], [0,1]])
    # LightPipes uses the opposite imaginary-q sign convention.
    library_radius = math.sqrt(-field.lam/math.pi*(field._q.imag+field._q.real**2/field._q.imag))*1e6
    assert result['metrics']['screen_radius_um'] == pytest.approx(library_radius, rel=1e-12)
    assert result['all_checks_passed']


def test_gaussian_finite_catalog_choice_and_screen_revision_preserve_input():
    results = [evaluate('gaussian', gaussian(focal_length_mm=f)) for f in (100,150,200)]
    qualifying = [r for r in results if r['metrics']['screen_radius_um'] < 50]
    assert [r['parameters']['focal_length_mm'] for r in qualifying] == [100]
    revised = evaluate('gaussian', gaussian(screen_distance_mm=150))
    for key in ('wavelength_nm','waist_radius_um','waist_z_mm','focal_length_mm'):
        assert results[0]['parameters'][key] == revised['parameters'][key]
    assert revised['metrics']['screen_radius_um'] > 50


@pytest.mark.parametrize('bad', [dict(waist_radius_um=True), dict(waist_radius_um=1), dict(waist_z_mm=float('nan')),
                                dict(focal_length_mm=0), dict(screen_distance_mm=300), dict(M2=2)])
def test_gaussian_rejects_undefined_or_nonparaxial_parameters(bad):
    with pytest.raises(ValueError):
        evaluate('gaussian', gaussian(**bad))


def test_result_archive_does_not_overwrite_evidence(tmp_path):
    result = evaluate('gaussian', gaussian(), tmp_path)
    saved = json.loads((tmp_path/'optics-result.json').read_text())
    assert saved['metrics'] == result['metrics']
    assert result['artifacts'][0]['bytes'] > 0
    with pytest.raises(FileExistsError):
        evaluate('gaussian', gaussian(), tmp_path)


def test_unknown_domain_is_not_imported_or_executed():
    with pytest.raises(ValueError):
        evaluate('os.system', {})