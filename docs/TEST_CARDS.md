# Frozen development test cards

Policy version: development-v0.1.0. Policy hash: 289c883ef4f0c1a2fac02ab54c92e1c76d445bcdaca9706774c167c005be9fde.

The code and each run record the policy hash. A future policy change requires fresh confirmation and fresh numerical acceptance. Model output cannot change thresholds or omit tests.

## Task–parameter consistency

Inputs: independently confirmed task and original candidate. Check layer count/order, physical thickness and material interpretation. For real isotropic nonmagnetic media epsilon=n². Epsilon2 alone is legal. A mismatch is FAIL only when it contradicts confirmed intent. Missing intent is INCONCLUSIVE. Allowed recovery: restore one candidate value to the task; never change the task to match a suspect candidate.

## Reference pairing and reflection isolation

The trusted worker creates fresh empty-air references for every numerical configuration. Source profile, frequency grid, spatial discretization, cell, monitors, amplitude, Courant, DFT decimation and chunk layout are recorded. Amplitude mismatch is a known invalid pairing. Different final stop times are not automatically invalid; measured spectral/time sensitivity must decide. Reflection uses load_minus_flux_data before Fourier accumulation; transmission does not subtract incident fields. Original raw arrays remain available.

## Full requested-frequency coverage

All arrays must have exactly the requested number of finite entries. Actual reference and target frequencies must match the full requested uniform-frequency grid. Every incident flux must be positive and at least1e-12 and1e-6 of the spectrum maximum. No weak endpoints are dropped. Insufficient coverage is INCONCLUSIVE and blocks a PASS.

## Independent thin-film reference

Use tmm0.2.0 at the actual Meep frequencies, deriving all material/thickness values from the locked task. Max absolute error across R and T at every requested bin must be≤0.01. The reference is not fed candidate material values. This is an engineering development tolerance, not a calibrated universal uncertainty.

## Lossless energy and power bounds

Only within the supported complete-channel lossless1D model, max|R+T−1|≤0.01; R and T must be in[0,1] within the same numerical tolerance. Nothing is clipped or rescaled. Both a correct film and the wrong lossless material may conserve energy, so this never replaces task matching or independent reference.

## Numerical and PML sensitivity

Rerun fresh reference/target pairs at resolution×1.5, post-source time×2 and PML×1.5. All physical source/device/monitor positions are fixed during the PML change, while the outer domain expands. Max absolute R/T change must be≤0.005. Raw incident spectra also compare using max absolute difference divided by the baseline peak, tolerance0.005. These are tested-setting comparisons, not proof of asymptotic convergence. A missing required run, worker failure or exhausted resource budget is INCONCLUSIVE, preserving any independently known FAIL.

## Applicable sources

- Meep basic tutorial: https://meep.readthedocs.io/en/latest/Python_Tutorials/Basics/
- Meep normalization introduction: https://meep.readthedocs.io/en/latest/Introduction/
- Meep FAQ: https://meep.readthedocs.io/en/latest/FAQ/
- Meep PML: https://meep.readthedocs.io/en/latest/Perfectly_Matched_Layer/
- Meep Python API: https://meep.readthedocs.io/en/latest/Python_User_Interface/
- tmm implementation: https://github.com/sbyrnes321/tmm

Actual runtime versions and code hashes are in every evidence bundle. Documentation URLs are explanatory sources, not dependency locks.
