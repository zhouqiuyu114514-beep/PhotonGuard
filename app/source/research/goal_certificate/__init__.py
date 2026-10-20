"""Research-only small continuous-model certificate checkers.

The frozen arithmetic kernels contain mathematical assertions. Refuse optimized
interpreters before any submodule import or input processing can skip them.
This is deliberately an explicit exception, not another removable assertion.
"""
if not __debug__:
    raise RuntimeError(
        "CERTIFICATE_OPTIMIZATION_UNSUPPORTED: run without -O/-OO and unset "
        "PYTHONOPTIMIZE; mandatory mathematical and conformity checks must run"
    )
