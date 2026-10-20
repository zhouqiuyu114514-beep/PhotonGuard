from fractions import Fraction as F
import pytest
from research.goal_certificate.selected_record_sidecar import verified_endpoint


def test_temple_input_reconstructed_from_integrals_not_claimed_shift():
    value={'integrals':{'mass':[2,2],'N':[3,3],'residual2':[.1,.2]},'true_rayleigh_interval':['0','0'],'arbitrary_residual_shift_exact':'100'}
    out=verified_endpoint(value)
    assert list(map(F,out['true_rayleigh_interval']))==[F(3,2)]*2
    assert F(out['true_rayleigh_residual2_upper'])==F(.2)/2


def test_endpoint_rejects_nonpositive_normalization():
    with pytest.raises(ValueError):verified_endpoint({'integrals':{'mass':[-1,1],'N':[1,1],'residual2':[0,1]}})
