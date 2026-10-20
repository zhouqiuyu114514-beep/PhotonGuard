"""Bounded deterministic monitor grid: no interpolation or user-code execution."""
def frequencies(task):
    lo, hi = task['wavelength_um']
    n = task['nfreq']
    if task.get('sampling') == {'kind': 'equal_wavelength'}:
        # Ascending frequencies; the corresponding wavelengths descend uniformly.
        wavelengths = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
        return [1 / w for w in reversed(wavelengths)]
    fmin, fmax = 1 / hi, 1 / lo
    return [fmin + (fmax - fmin) * i / (n - 1) for i in range(n)]

def description(task):
    equal_wavelength = task.get('sampling') == {'kind': 'equal_wavelength'}
    grid = frequencies(task)
    return {'adapter_version': 'explicit-dft-grid-v1',
        'requested_grid': 'equal_wavelength' if equal_wavelength else 'equal_frequency',
        'actual_solver_frequencies_per_um': grid,
        'actual_solver_wavelengths_um': [1 / f for f in grid],
        'actual_solver_point_count': len(grid), 'interpolated_point_count': 0,
        'interpolation_used': False,
        'display_note': 'Markers are actual DFT monitor points. Connecting lines are visual guides, not additional simulations.'}
