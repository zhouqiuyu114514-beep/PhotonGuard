"""Rational proof of the sufficient q<=.139, electric norm>=.7 budget."""
from fractions import Fraction as F
from .selector_observable_bounds import fraction, sqrt_bounds, outward


def bound(q_upper=F(139, 1000), electric_norm_lower=F(7, 10), *, projection_rank=1):
    q, a = map(fraction, (q_upper, electric_norm_lower))
    if isinstance(projection_rank, bool) or projection_rank != 1:
        raise ValueError('RANK_ONE_REQUIRED')
    if not 0 <= q < 1 or not 0 < a <= 1:
        raise ValueError('PROJECTOR_DOMAIN')
    eta = sqrt_bounds(2-2*sqrt_bounds(1-q*q)[0])[1]
    e = eta/a
    return {'status': 'CONDITIONAL_PROJECTOR_BUDGET', 'q_upper_exact': str(q),
            'electric_norm_lower_exact': str(a), 'eta_upper_exact': str(eta),
            'electric_error_upper_exact': str(e), 'electric_error_upper': outward(e, True),
            'strictly_below_one_fifth': e < F(1,5),
            'assumes_combined_mass_one': True, 'residual_or_gap_certified': False,
            'unlocks_target_binding': False}
