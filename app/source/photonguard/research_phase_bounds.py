"""Exact conditional phase bounds; no implemented continuous-mode certifier.

Rational arithmetic encloses the scalar formula, not its physical inputs.
Neither caller booleans nor file hashes can upgrade that distinction.
"""
import math
from fractions import Fraction
from functools import lru_cache


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('RESEARCH_PHASE_ENVELOPE_SCHEMA')
    return Fraction(value)


def _interval(value):
    if type(value) not in (list, tuple) or len(value) != 2:
        raise ValueError('RESEARCH_PHASE_ENVELOPE_SCHEMA')
    lo, hi = map(_number, value)
    if lo > hi:
        raise ValueError('RESEARCH_PHASE_ENVELOPE_SCHEMA')
    return lo, hi


def _float_out(value, upper):
    out = float(value)
    if (upper and Fraction(out) < value) or (not upper and Fraction(out) > value):
        out = math.nextafter(out, math.inf if upper else -math.inf)
    return out


@lru_cache(maxsize=1)
def pi_bounds():
    """Machin identity with exact alternating-series remainders (80 terms)."""
    def atan(q):
        x = Fraction(1, q)
        s = sum((-1)**j * x**(2*j+1) / (2*j+1) for j in range(80))
        return s, s + x**161 / 161
    a, b = atan(5), atan(239)
    return 16*a[0]-4*b[1], 16*a[1]-4*b[0]


def _sinc_bounds(x):
    """0 <= x <= pi; terms beyond degree 50 decrease strictly."""
    term = Fraction(1)
    partial = term
    for j in range(1, 26):
        term *= -x*x / ((2*j)*(2*j+1))
        partial += term
    # Degree 50 ends in a negative term: lower; next positive term: upper.
    return max(Fraction(0), partial), min(Fraction(1), partial + (-term*x*x/(52*53)))


def _phase_range(lo, hi):
    near = Fraction(0) if lo <= 0 <= hi else min(abs(lo), abs(hi))
    far = max(abs(lo), abs(hi))
    if far/2 <= pi_bounds()[0]:
        low = _sinc_bounds(far/2)[0]**2
        high = _sinc_bounds(near/2)[1]**2
        return low, high, 'main_lobe_monotonicity_and_exact_sine_series'
    upper = Fraction(1) if near == 0 else min(Fraction(1), 4/(near*near))
    return Fraction(0), upper, 'global_sinc_squared_envelope'


def assess_phase_interval(phase_interval_rad, target, input_provenance):
    """Independent research sidecar: robust scalar comparison conditional on Phi.

    The entire phase interval is used. A point meeting a threshold cannot make an
    interval crossing that threshold pass. Production receipts are never edited.
    """
    lo, hi = _interval(phase_interval_rad)
    eta = _number(target)
    if not 0 < eta <= 1 or type(input_provenance) is not dict:
        raise ValueError('RESEARCH_PHASE_ENVELOPE_SCHEMA')
    lower, upper, method = _phase_range(lo, hi)
    decision = 'MET' if lower >= eta else 'EXCLUDED' if upper < eta else 'INCONCLUSIVE'
    return {'research_policy': 'conditional-phase-interval-v2',
            'phase_interval_rad': list(phase_interval_rad), 'target': target,
            'conditional_phase_factor_interval': [_float_out(lower, False), _float_out(upper, True)],
            'conditional_goal_decision': decision, 'scalar_interval_method': method,
            'scalar_arithmetic_validated': True,
            'status': 'CONDITIONAL_ON_UNCERTIFIED_INPUT_INTERVAL',
            'design_goal_status': 'NOT_EVALUATED', 'continuous_truth_interval_certified': False,
            'input_provenance': input_provenance,
            'production_policy_or_previous_receipt_changed': False}


def assess_goal_envelope(interval, interval_provenance, length_um, target):
    lo, hi = _interval(interval)
    length, eta = _number(length_um), _number(target)
    if length <= 0 or not 0 < eta <= 1 or type(interval_provenance) is not dict:
        raise ValueError('RESEARCH_PHASE_ENVELOPE_SCHEMA')
    d = Fraction(0) if lo <= 0 <= hi else min(abs(lo), abs(hi))
    upper = Fraction(1) if d == 0 else min(Fraction(1), 4/(d*d*length*length))
    return {'research_policy': 'conditional-phase-envelope-v2',
            'delta_beta_interval_rad_per_um': list(interval),
            'distance_from_zero_rad_per_um': _float_out(d, False),
            'length_um': length_um, 'target': target,
            'conditional_phase_factor_upper': _float_out(upper, True),
            'conditional_exclusion_if_interval_were_certified': upper < eta,
            'status': 'CONDITIONAL_EXCLUSION_UNPROVEN', 'design_goal_status': 'NOT_EVALUATED',
            'reason': 'No independent continuous-mode interval certifier; caller Boolean/hash cannot certify an interval',
            'input_provenance': interval_provenance, 'continuous_truth_interval_certified': False,
            'scalar_arithmetic': 'exact rational operations, outward conversion to binary64',
            'production_policy_or_previous_receipt_changed': False}


def assess_neff_goal_envelope(fundamental_interval, harmonic_interval, wavelength_um,
                            period_um, length_um, target, input_provenance, qpm_order=1):
    f, s = _interval(fundamental_interval), _interval(harmonic_interval)
    wave, period = _number(wavelength_um), _number(period_um)
    if wave <= 0 or period <= 0 or type(qpm_order) is not int or qpm_order < 1:
        raise ValueError('RESEARCH_PHASE_ENVELOPE_SCHEMA')
    # SHG: delta beta = pi * (4*(n_SH-n_F)/lambda_F - 2*m/Lambda).
    a = 4*(s[0]-f[1])/wave-2*qpm_order/period
    b = 4*(s[1]-f[0])/wave-2*qpm_order/period
    p = pi_bounds()
    products = [x*y for x in (a, b) for y in p]
    residual = [_float_out(min(products), False), _float_out(max(products), True)]
    out = assess_goal_envelope(residual, input_provenance, length_um, target)
    out.update(fundamental_neff_interval=list(fundamental_interval),
               harmonic_neff_interval=list(harmonic_interval), wavelength_um=wavelength_um,
               period_um=period_um, qpm_order=qpm_order,
               pi_validation='Machin identity; exact rational alternating-series interval, 80 terms')
    return out
