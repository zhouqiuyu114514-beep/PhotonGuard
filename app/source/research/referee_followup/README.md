# Referee follow-up research sources

These are separate research recipes, not production adapters.

- `frozen_tensor_controls.py`: corrected E1 fixed-k window, with retained null-window linkage. Requires original evidence under local-validation; existing start/output guards refuse replay over the old window. The initial failed wrapper is retained only in the immutable evidence delivery.
- `corner_primal_dual.py`: exact-boundary P2 / rotated-P1 local electrostatic energies. `--calibrate` performs zero linear solves. Full execution requires a separately frozen plan and refuses an existing STARTED marker.
- `periodic_maxwell_graph.py`: independent full-vector periodic first-order graph-form FLOATING preflight. Takes a JSON job path and writes a new subdirectory. It is not an interval eigensolver or beta certificate.

The source copies differ from frozen E1/E2 workers only by resolving the repository root relative to this file. They are not the hash-identical archived worker. Runtime/evidence paths and one-use plans must be explicitly configured for a new experiment; do not overwrite or silently rerun old windows. Resource supervision scripts and exact executed files are included in the follow-up evidence package.

See `docs/REFEREE_FOLLOWUP_20261008_ZH.md` for results, resource accounting (including the extra failed E1 capture), mathematical scope and incomplete certification work. No research result upgrades production QPM/design status.
