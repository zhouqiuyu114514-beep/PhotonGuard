"""Exact, conditional distance-to-failure-cone bounds; never field evidence."""
from fractions import Fraction as F
from .selector_observable_bounds import fraction, fraction_interval, sqrt_bounds, outward


def distance_down(p, threshold):
    p, t = map(fraction, (p, threshold))
    if not 0 <= t < p <= 1:
        raise ValueError('STRICT_ABOVE_THRESHOLD_REQUIRED')
    return sqrt_bounds(p*(1-t))[0] - sqrt_bounds((1-p)*t)[1]


def distance_up(p, threshold):
    p, t = map(fraction, (p, threshold))
    if not 0 <= p < t <= 1:
        raise ValueError('STRICT_BELOW_THRESHOLD_REQUIRED')
    return sqrt_bounds(t*(1-p))[0] - sqrt_bounds((1-t)*p)[1]


def lower_ratio(p, error):
    # When the cone can reach the perpendicular subspace the minimum is zero.
    if error*error >= p:
        return F(0)
    return max(F(0), sqrt_bounds(p*(1-error*error))[0]
               - sqrt_bounds((1-p)*error*error)[1])**2


def upper_ratio(p, error):
    if error*error >= 1-p:
        return F(1)
    return min(F(1), (sqrt_bounds(p*(1-error*error))[1]
                     + sqrt_bounds((1-p)*error*error)[1])**2)


def conditional_cone_bounds(p, core, outer, error, gamma, *,
                            epsilon_regions, mean_epsilon):
    p, core, outer = map(fraction_interval, (p, core, outer))
    e, gamma = map(fraction, (error, gamma))
    if not 0 <= e < 1 or gamma < 1:
        raise ValueError('ERROR_OR_GAMMA_DOMAIN')
    if not epsilon_regions:
        raise ValueError('MATERIAL_REQUIRED')
    diagonals = []
    for matrix in epsilon_regions:
        if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
            raise ValueError('DIAGONAL_3_BY_3_REQUIRED')
        for i in range(3):
            for j in range(3):
                x = fraction(matrix[i][j])
                if i != j and x != 0:
                    raise ValueError('NONDIAGONAL_EPSILON_UNSUPPORTED')
                if i == j:
                    if x <= 0:
                        raise ValueError('POSITIVE_EPSILON_REQUIRED')
                    diagonals.append(x)
    lo, hi = map(fraction, mean_epsilon)
    if not min(diagonals) <= lo <= hi <= max(diagonals):
        raise ValueError('MEAN_EPSILON_DOMAIN')
    if gamma*gamma < hi/min(diagonals):
        raise ValueError('GAMMA_UPPER_BOUND_INSUFFICIENT')
    delta = gamma*e
    # delta>=1 is a valid but wholly uninformative conversion, not evidence.
    pl = F(0) if delta >= 1 else lower_ratio(p[0], delta)
    cl, ou = lower_ratio(core[0], e), upper_ratio(outer[1], e)
    thresholds = [F(.55), F(.35), F(.05)]
    distances = [distance_down(p[0], thresholds[0]) if p[0] > thresholds[0] else F(0),
                 distance_down(core[0], thresholds[1]) if core[0] > thresholds[1] else F(0),
                 distance_up(outer[1], thresholds[2]) if outer[1] < thresholds[2] else F(0)]
    margins = [distances[0]-delta, distances[1]-e, distances[2]-e]
    return {
        'status': 'CONDITIONAL_SELECTOR_CONE_BOUNDS_ONLY',
        'bounds_exact': list(map(str, (pl, cl, ou))),
        'polarization_lower': outward(pl, False), 'core_lower': outward(cl, False),
        'outer_upper': outward(ou, True), 'cone_margins_exact': list(map(str, margins)),
        'thresholds_binary64_exact': list(map(str, thresholds)),
        'strict_filters_would_pass_if_inputs_certified': all(m > 0 for m in margins)
            and pl > thresholds[0] and cl > thresholds[1] and ou < thresholds[2],
        'continuous_field_or_error_certified': False, 'unlocks_target_binding': False,
    }
