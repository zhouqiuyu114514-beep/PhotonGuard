# Read-only Meep script import: exact supported scope

## Current checkpoint

`import-script` now recognizes a deliberately narrow **sequential flux-acquisition recipe**, then emits a reviewable **canonical film1d-v1 recipe representation**. It does not execute the supplied Python, import Meep from it, evaluate Python source, or prove equivalence for arbitrary scripts. The deterministic AST parser is not an AI contribution or an intent parser.

The existing strict JSON input is unchanged. The supplied reference ZIP that previously failed to download remains uninspected and was not used to implement this importer.

## Preview, confirm intent separately, run the trusted recipe

```sh
.runtime/run-python -m photonguard import-script examples/script_import/film_n2.py --out imports/film_n2
.runtime/run-python -m photonguard prepare-task imports/film_n2/candidate.json --out inputs/film_n2_review
# Inspect imports/film_n2/import-report.json and candidate.json before proceeding.
# Read inputs/film_n2_review/REVIEW.zh.md; unknown task fields remain null.
# Independently write/review task JSON. The task below is only a known developer fixture.
.runtime/run-python -m photonguard confirm examples/film_n2/task.json --candidate imports/film_n2/candidate.json --lock imports/film_n2/task.lock.json --approve
.runtime/run-python -m photonguard run examples/film_n2/task.json imports/film_n2/candidate.json --lock imports/film_n2/task.lock.json
```

Preview does not create a task, a lock, approval, or an FDTD pass. Its status is `EXTRACTED` or `UNSUPPORTED`. `EXTRACTED` only means the complete recognized input can be represented by the declared canonical recipe. The CLI returns 0 for extraction and 4 for unsupported source; malformed CLI/filesystem inputs return 3.

`prepare-task` creates a separate unapproved worksheet and Chinese review guide after reparsing the original import receipt. It leaves physical assumptions, units, material intent, layer count, spectrum and provenance unconfirmed. Script observations are kept in a separate file. CLI `confirm` rejects incomplete/out-of-scope tasks and existing lock paths; `--candidate` additionally checks imported provenance and spectrum. Material discrepancies remain diagnosable. The runner still validates task, lock, provenance and spectrum independently; none of these preparation steps establishes PASS.

The operator must separately confirm physics, material intent, wavelength endpoints, frequency count and **one micrometre per Meep unit**. Meep's dimensionless source does not establish that physical scale. No comments, docstrings, variable names, candidate material values, or LLM output establish the user's intent. An incomplete task stays INCONCLUSIVE; an invalid/missing task lock blocks execution.

The confirmed task's frequency grid must match all imported source/monitor settings. Unlike layer n/thickness mismatches, which are faithfully preserved for diagnosis, an incompatible spectrum cannot currently be represented independently in the candidate schema. It is rejected before any FDTD rather than silently substituted from the task.

## Exact grammar and Meep calls

Use `examples/script_import/film_n2.py` as the complete supported writing pattern. This is a template recognizer, not general compatibility with Meep examples or executable notebooks.

- UTF-8 source (optional BOM and CRLF; a coding declaration must also specify UTF-8 and agree with the BOM), at most 128 KiB, 12,000 AST nodes, depth 64, 512 assignment bindings, 256 unique dependency source locations per value
- Optional initial inert module docstring; arbitrary inert comments
- One initial `import meep as <alias>`; no other import, `from` import, implicit imports, or dependency execution
- Single-name assignments; each name assigned once, no underscore-prefixed names or shadowing the Meep alias
- Previously bound names/aliases and finite numeric constants with parentheses and `+`, `-`, `*`, `/`, unary signs, and bounded `**`; no function-based constant evaluation
- Numeric magnitude <= 1e12 at every intermediate step; power exponent in [-16,16], real result only; division by zero/nonfinite results rejected
- Explicit flat lists of at most eight PML/Source/Block recipe objects (no nested/numeric lists), and the whitelisted Meep calls below; Boolean literal `True` only where the specific call permits it
- `mp.Vector3(x,y,z)`: exactly three positional coordinates; finite except `mp.inf` in the two transverse block-size coordinates
- `mp.Medium(index=...)` **or** `mp.Medium(epsilon=...)`: exactly one finite real scalar property, without reinterpretation
- `mp.Block(size=...,center=...,material=...)`
- `mp.GaussianSource(fcen,fwidth=2*df,cutoff=5.0)`
- `mp.Source(pulse,component=mp.Ex,center=...,amplitude=...)`
- `mp.PML(thickness,direction=mp.Z)`
- `mp.FluxRegion(center=...,direction=mp.Z)`
- `mp.Simulation(cell_size=...,dimensions=1,resolution=...,Courant=0.5,boundary_layers=...,geometry=...,sources=...,eps_averaging=True)`: exact keywords, no implicit defaults
- `sim.add_flux(fcen,df,nfreq,region,decimation_factor=1)`: exactly four positional arguments and the stated keyword
- `sim.run(until_after_sources=finite_duration)`; no absolute `until`, callbacks or stopping functions
- `sim.get_flux_data(monitor)`, `sim.load_minus_flux_data(monitor,data)`, `sim.reset_meep()`
- `mp.get_fluxes(monitor)` and optional `mp.get_flux_freqs(monitor)` assigned to names

Unknown statements, control flow (even `if False`), definitions, lambdas, comprehensions, attribute mutation, name reassignment, indexing, tuple assignment, f-strings, arbitrary calls, extra keywords, star arguments, I/O, postprocessing, plotting and output operations are rejected. Readout arithmetic, including user-supplied R/T normalization, is not interpreted. The sample is a flux-acquisition recipe ending in raw readouts; the trusted runner computes R/T from its own raw output. Never describe that as checking the original program's postprocessing.

## Required physical and workflow semantics

- Exactly two tracked simulations: an empty-air reference and a 1..8-layer target
- Both are 1D z / Ex, Courant=0.5, epsilon averaging on, one Gaussian source and one z PML; all current bounded film1d-v1 numerical limits remain in force
- Layers are infinite in x/y, finite thickness along z, in list order, contiguous without gaps/overlaps, total stack centered at z=0
- With total candidate thickness D, cell z length is D+2*air+2*pml, source z=-D/2-2, reflection z=-D/2-1.5, transmission z=D/2+1.5; transverse coordinates are zero
- Reference and target cell, resolution, PML, source frequency/width/cutoff, and monitor frequency grids agree. fwidth=2*df; all monitor grids have positive frequency endpoints, equal nfreq in [3,201], and reciprocal wavelength endpoints in [0.5,5] confirmed micrometre units. Numeric recipe-equality comparisons allow at most 1e-12 absolute/relative floating-point roundoff
- Each simulation adds exactly two distinct reflection/transmission monitors before a single fixed-duration run; reference must reset before target construction; both eventually reset
- Reference transmission flux and target reflection/transmission flux must be read after their corresponding run and before reset. Monitor identity is tracked through aliases, not guessed from variable names
- If subtraction is present, reference reflection Fourier data must be captured after its run and loaded into the target reflection monitor after both target monitors are added and before the target run. Wrong source/target monitor or order is UNSUPPORTED
- Missing subtraction is represented as `subtract_incident=false`, never inserted automatically. Unequal legal amplitudes and reference stop-time factors are retained for the existing checks. Reference duration must be between zero and target duration because this is the current candidate schema's range
- Spectrum, Courant, geometry placement, source/monitor positions, epsilon averaging and other unrepresentable differences are rejected, not normalized into a passing template

## Evidence and provenance

A new preview directory contains exact `script.original.py` bytes and `import-report.json`. Only fully extracted inputs receive `candidate.json`. Rejected inputs retain an explicit unresolved field/expression/reason/location, safe previously resolved numeric bindings, and null partial recipe groups; **no runnable partial candidate** is emitted.

Accepted candidate provenance embeds base64 original bytes, their SHA-256, byte-independent source name, importer version, extracted-recipe hash, spectral settings and per-field source locations. Locations use one-based source lines and zero-based UTF-8 byte columns in decoded source, with an optional BOM removed. They include parameter declarations and expression/use sites. This is inspectable provenance, not a signature or external attestation.

Before execution, the runner freshly parses embedded original bytes, checks the complete receipt and candidate against that extraction, and verifies the locked task's spectrum. It does not read any path claimed inside provenance. Presence of any import marker or patch history requires the full receipt; deleting only the receipt cannot bypass validation. Original source bytes are also copied into the run evidence if their embedded hash is valid, including when the source/task scope is rejected. Raw input JSON remains retained in every run.

Approved bounded patches retain the original script and full patch chain. The runner replays that chain with the existing frozen patch constraints before accepting a changed canonical recipe. The original script is never rewritten, and a repaired recipe's PASS is never presented as the original script passing. Both JSON and HTML evidence state `script_executed=false` and distinguish original extraction from any modified recipe.

## What remains unproved or unsupported

- No arbitrary Meep script execution or general Python behavioral-equivalence proof
- No imported-script postprocessing, alternate source/monitor layouts, absorption, dispersion, anisotropy, oblique incidence, substrates, 2D or 3D models
- No natural-language intent parser, automatic task approval, configuration-effort study, independently held-out writing-style benchmark, or measured AI advantage
- Canonical-recipe PASS retains the existing discrete-frequency and development-threshold limitations; sensitivity at tested settings is not asymptotic convergence
- The earlier small assistant-mediated GPT smoke comparison produced the same observed outcomes as deterministic rules. This parser does not alter that result or establish DeepSeek performance

The original JSON-only v0.1 source package and evidence remain frozen. This is a later development checkpoint, with new evidence stored separately.
