# Third-party resources and provenance

## RC7 current dependency use (2026-10-13)

The current inverse workflow reuses existing optical models, finite numerical optimization and bounded planning. This table records the development runtime inspected on 2026-10-13; optional packages are installed separately and are not bundled in the source package. `pyproject.toml` declares the `analysis` extra for SciPy. The minimal forward-only requirements intentionally omit SciPy.

| Resource | Current actual use | Inspected version / license | Primary source |
|---|---|---|---|
| Python | Local workflow, file contracts, resource-limited workers and offline examples | 3.12.14; PSF | https://www.python.org/ |
| NumPy | Observation arrays, prediction, finite differences, SVD nuisance projection and local design calculations | 2.5.3; installed metadata: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org/ |
| SciPy | `least_squares` for bounded slit/Gaussian inverse fits and profiles; `minimize_scalar` for finite single-film thickness intervals | 1.18.1; BSD-3-Clause main project license; retain distribution notices | https://scipy.org/ ; https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html |
| tmm | Known-index film reflectance in forward computation and thickness-mode evaluation | 0.2.0; MIT | https://github.com/sbyrnes321/tmm |
| LightPipes | Optional original diffraction implementation; not required for offline inverse examples | 2.1.5; BSD-3-Clause, installed distribution metadata | https://github.com/opticspy/lightpipes |
| Meep / MPB | Optional finite forward checks / frozen LN research; neither is called inside inverse fitting or acquisition scoring | Existing environment 1.34.0 / 1.12.0; GPL-2.0-or-later | https://github.com/NanoComp/meep ; https://github.com/NanoComp/mpb |
| pytest | Numerical, contract and workflow regression tests; not a user runtime dependency | 9.1.1; MIT | https://docs.pytest.org/ |
| DeepSeek API | Separately approved online task organization; the offline examples make zero model requests | External commercial service, not distributed weights or a team-owned open model | https://api-docs.deepseek.com/ |

`examples/inverse` contains public synthetic teaching examples with disclosed ideal equations and fixed noise seeds. They are not hidden evaluation cases or new human trials. The reusable facade and examples retain the GPL-2.0-or-later project declaration; this inventory does not relicense any component. API credentials, installed distributions and hidden assessment truth are excluded from the source examples. Public distribution and ownership decisions remain with the owner.

The dated sections below preserve historical provenance; earlier use labels do not replace this current capability inventory. No formal competition presentation or video is part of these development examples.

## RC1 additions (historical, 2026-10-11)

The current workbench supports bounded film, diffraction and Gaussian tasks. LightPipes 2.1.5 (BSD-3-Clause, verified from installed distribution metadata/license) supplies the optional diffraction implementation; NumPy provides an explicitly labelled fallback and q/ABCD numerical operations. Source: https://github.com/opticspy/lightpipes . tmm 0.2.0 is the fast film engine; Meep checks remain optional and separately reported. RC1 does not implement a new optical solver.

The standalone HTML summary and read-only SVG/PNG conversion are project code using Python's standard library and saved numerical data. No model-generated image is used as experimental evidence. Dependencies, browser executables, model weights and font files are not redistributed in the local candidate package. Minimal pinned dependencies are in release/requirements-fast.txt; the optional full solver environment retains runtime/conda-linux-64.lock.

All material below is historical provenance for its stated date; it does not narrow the current workbench to the old single-film entrypoint.

Dependency inventory recorded 2026-10-05 UTC; use-status corrected 2026-10-10. This project independently implements a constrained orchestration/checking workflow, not a new Maxwell solver or thin-film method.

| Resource | Actual use | Version / license | Source |
|---|---|---|---|
| Meep / pymeep | Actual serial FDTD solver and field-subtraction API | 1.34.0, GPL-2.0-or-later | https://github.com/NanoComp/meep |
| MPB | Frozen LN eigenmode research and archived evidence; no new geometry search in competition phase | 1.12.0, GPL-2.0-or-later | https://github.com/NanoComp/mpb |
| tmm | Independent task-derived characteristic-matrix reference | 0.2.0, MIT | https://github.com/sbyrnes321/tmm |
| Python | CLI, worker orchestration and local HTTP UI | 3.12.14, PSF | https://www.python.org/ |
| NumPy | Numerical arrays and finite/full-band validation | 2.5.3, BSD-3-Clause | https://numpy.org/ |
| pytest | Tests | 9.1.1, MIT | https://docs.pytest.org/ |
| conda-forge / micromamba | Isolated trusted-package environment installation | Exact build URLs/hashes in runtime lock; micromamba2.9.0 | https://conda-forge.org/ |
| Meep docs | 1D coordinates, normalization, PML and sensitivity design | Retrieved2026-10-05; documentation not bundled/copied wholesale | https://meep.readthedocs.io/en/latest/ |
| DeepSeek API documentation | Bounded JSON adapter with archived real calls; current counts are in CURRENT_STATE.json | Official docs retrieved2026-10-05; explicit model required | https://api-docs.deepseek.com/zh-cn/guides/json_mode/ |
| GPT development assistance | Code authoring, independent review and documentation | Development process, not runtime AI evidence | Development assistance is distinct from separately audited runtime DeepSeek calls |

No Meep or tmm source code was copied into this source tree. The worker follows the documented public APIs. Full dependency versions/builds are in `runtime/versions.json`; exact installation URLs and hashes are in `runtime/conda-linux-64.lock`. Transitive packages retain their own licenses. The archive excludes installed binaries and credentials.

Official technical sources:

- https://meep.readthedocs.io/en/latest/Python_Tutorials/Basics/
- https://meep.readthedocs.io/en/latest/FAQ/
- https://meep.readthedocs.io/en/latest/Perfectly_Matched_Layer/
- https://meep.readthedocs.io/en/latest/Python_User_Interface/
- https://meep.readthedocs.io/en/latest/Installation/
- https://github.com/NanoComp/meep/blob/master/COPYRIGHT
- https://github.com/sbyrnes321/tmm/blob/master/LICENSE.txt

Latest/master links support methodology but are not version locks; the actual runtime lock is authoritative for reproduction. Before external distribution, review packaging and actual dependency licenses; this document is provenance, not legal advice.


## Competition material production, 2026-10-10

| Resource | Use and distribution boundary | Obligation / status |
|---|---|---|
| DeepSeek deepseek-flash API | Paid runtime input/diagnosis; request receipts retained, no weights or key distributed | Third-party commercial API terms; disclose model, data scope and actual usage. Not a project-owned open model. https://api-docs.deepseek.com/ |
| Playwright + Microsoft Edge | Local simulated browser operation and screen recording | Playwright Apache-2.0; Edge proprietary terms. No browser executable bundled. https://github.com/microsoft/playwright |
| ReportLab + Poppler | PDF composition and rendered-page QA | ReportLab BSD; Poppler GPL. Tools are not bundled in source release. https://www.reportlab.com/opensource/ https://poppler.freedesktop.org/ |
| FFmpeg | Conversion of actual recorded UI video to MP4 | Build-specific GPL/LGPL; encoder executable not distributed. https://ffmpeg.org/legal.html |
| Windows SimHei font | Local Chinese PDF typography | System-installed font, font file not distributed; PDF uses standard CJK CID font without bundling system font data. |
| Codex development assistance | Implementation, review, automation and material authoring | Disclosed separately in AI_ASSISTANCE_ZH.md; no invented human authorship or review. |

The project's GPL notice is retained; upstream sources/binaries are not embedded into the source archive. Install dependencies separately from the pinned conda-forge lock and retain their notices. The final team must confirm actual ownership and submission authority before public distribution. This is a factual inventory, not a claim that every generated item is exclusively owned by the team.
