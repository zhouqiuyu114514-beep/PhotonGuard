# Independent Yee reference research

These are archived, executed full-vector research workers. They solve a diagonal-permittivity, periodic transverse-H eigenproblem using NumPy and SciPy. They do not call MPB, DeepSeek, or FDTD, and they do not create a production acceptance receipt. Their continuous propagation-constant accuracy is **not certified**.

The worker files are preserved byte for byte. Do not import them: their module initialization sets process resource limits. Geometry, material averaging, six requested modes, deterministic starting vector, shift, tolerance, and field recovery remain identical to the recorded experiments.

## Prepare without running

From the repository root, using the existing Linux/WSL Python environment:

```sh
/home/zhou/projects/PhotonGuard/.runtime/run-python -B tools/prepare_yee_research.py --profile calibration --out local-validation/yee-calibration-new
```

Preparation uses only the Python standard library. It copies the worker and a small launcher, writes the fixed plan and hashes, and prints explicit commands. It does **not** import the worker, install dependencies, or start a solver. Any existing output path, including an empty directory or symlink, is rejected.

| Profile | Fixed cases | Worker address-space limit | Output cap |
| --- | --- | --- | --- |
| `calibration` (default) | Isotropic slab n512; anisotropic slab n256, n512, half-grid n512 | 1 GiB | 120 MiB |
| `ridge` | Both wavelengths: 4 μm square n128/n256, half-grid n256, 6 μm square n192 | 1 GiB | 120 MiB |
| `ridge80` | Both wavelengths: 4 μm square n320, base and half-grid | 2 GiB | 64 MiB |

The original v2 worker has a 12-attempt hard ceiling. The calibration and ridge plans retain that required field to preserve its bytes, while their unique whitelists and launcher enforce only four and eight registered attempts. The v4 worker and ridge80 profile both allow four attempts. No numerical parameters can be supplied to the preparation tool.

To execute an explicitly chosen prepared case, use a command from the generated `RUN_COMMANDS.txt`, for example:

```sh
/home/zhou/projects/PhotonGuard/.runtime/run-python -B local-validation/yee-calibration-new/run_one.py --id slab-iso-512
```

Run one command and inspect its result before continuing. The launcher checks frozen source/plan hashes, takes an exclusive directory lock, checks that the worker's address-space limit is at most half of currently available RAM, reserves output space, and enforces a 60-second parent timeout. It checks actual output during and after execution, retains 64 KiB for the final receipt, and stops the batch if output exceeds the allowance or a log exceeds 1 MiB. These checks are monitored limits, not a filesystem quota; an overflow is retained as a failed attempt. It records observed virtual memory and RSS. The immutable worker independently applies its address-space limit and CPU/alarm limits. Run through the launcher; direct worker execution does not enforce the dynamic available-memory or single-worker checks.

A failure stops that prepared batch. Existing receipts cannot be overwritten or retried; an interrupted launch or stale lock also fails closed. A new study or changed resource allowance needs a new explicitly chosen output directory and plan. Preparation alone is not permission to treat subsequent output as a validated reference.

## Physics and interpretation

The convention is `exp(i beta z - i omega t)` and `h = Z0 H`; lengths are μm. Compatible forward/backward Yee differences avoid a collocated first-derivative checkerboard. The solver supports only the recorded positive diagonal bulk tensors and ideal rectangular geometry.

One material builder is used for slab calibration and ridge calculations. Its directional local constitutive closure is:

- `epsilon_x = average_y(1 / average_x(1 / epsilon_x_bulk))`
- `epsilon_y = average_x(1 / average_y(1 / epsilon_y_bulk))`
- `epsilon_z = area_average(epsilon_z_bulk)`

Exact rectangular fractions give normal harmonic and tangential arithmetic averaging at a single aligned planar interface. At a corner this is a local series/parallel approximation, not the exact two-dimensional cell problem. It does not import MPB effective tensors. The [planar-interface averaging paper](https://math.mit.edu/~stevenj/papers/FarjadpourRo06.pdf) and [anisotropic-interface analysis](https://arxiv.org/abs/0708.1031) support the restricted interface reasoning; they do not certify this corner closure.

Selected complex E and h fields are saved with separate coordinates for every staggered component. Compare components on a common physical grid before computing shape overlap. E/h L2 similarity is not power or a propagation-constant error bound. The native flux diagnostic also has arbitrary eigenvector amplitude, not watts.

The formal long-device task has **L = 1000 μm = 1 mm**. A reported 20 mm sensitivity is only an additional unit example. For SHG use `delta(beta_SH - 2 beta_pump) * L`, and report both the signed sum and the sum of absolute wavelength contributions. Cancellation does not certify either propagation constant.

The executed same-builder r32/r64/r80 sequence was nonmonotone, and half-grid sensitivity increased at r80. Planar slab tests, tiny algebraic residuals, mirror symmetry, and high overlap with stored MPB fields did not establish a continuous error bound. The earlier v1 ridge arithmetic builder is different and must not be mixed into that convergence sequence.

## Recorded provenance

Original plan SHA-256 values refer to exact archived JSON bytes, not a reserialized JSON digest:

| Source | SHA-256 |
| --- | --- |
| Executed v2 worker, archived here as `yee_reference_v2.py` | `86705bd8aaac3c4b8b1eecee84608b4c7d31771b926aa015b136d868bfb31f5e` |
| Original `interface-v2/plan.json` | `333fdffbcbc1080f7154821c0a80a557b6fdf3f8dfcdc3966c2b73e9eddb3134` |
| Executed v4 worker, archived here as `yee_reference_r80_v4.py` | `5d4e95358d1f3a00db363e04f45e8e965d851af2d98917e6a4bc9ff63de03964` |
| Original `r80-v4/plan.json` | `81da64377b0838c6dc3d17ee9fce9d90e8563b9960209d6830350301d0a4d999` |
| Fixed profile catalog | `1e7981be0236068536bbd6d18645ac89b11593c7bc4eb7f458fb337cc0548bee` |

The original records remain under `local-validation/independent-reference-20261008/`. The v3 r80 pump failed during SuperLU allocation under a 1 GiB **virtual address-space** cap, despite more than 14 GiB host RAM being available. Its other three cases were not started. Separately authorized v4 changed the address-space cap to 2 GiB, preserving all scientific function ASTs and solver parameters. Its four runs succeeded, with observed peak virtual memory about 1.773 GiB. This did not turn v3 into a successful batch or change production MPB/FDTD limits.

The small launcher here generalizes that resource monitoring and adds a directory lock. It is not an archived physics worker. The selected worker, launcher, profile catalog, and preparation tool are bound into each newly prepared plan. Preparing or testing this utility does not repeat the historical solves.
