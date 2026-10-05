# Third-party resources and provenance

Recorded 2026-10-05 UTC. This project independently implements a constrained orchestration/checking workflow, not a new Maxwell solver or thin-film method.

| Resource | Actual use | Version / license | Source |
|---|---|---|---|
| Meep / pymeep | Actual serial FDTD solver and field-subtraction API | 1.34.0, GPL-2.0-or-later | https://github.com/NanoComp/meep |
| tmm | Independent task-derived characteristic-matrix reference | 0.2.0, MIT | https://github.com/sbyrnes321/tmm |
| Python | CLI, worker orchestration and local HTTP UI | 3.12.14, PSF | https://www.python.org/ |
| NumPy | Numerical arrays and finite/full-band validation | 2.5.3, BSD-3-Clause | https://numpy.org/ |
| pytest | Tests | 9.1.1, MIT | https://docs.pytest.org/ |
| conda-forge / micromamba | Isolated trusted-package environment installation | Exact build URLs/hashes in runtime lock; micromamba2.9.0 | https://conda-forge.org/ |
| Meep docs | 1D coordinates, normalization, PML and sensitivity design | Retrieved2026-10-05; documentation not bundled/copied wholesale | https://meep.readthedocs.io/en/latest/ |
| DeepSeek API documentation | Optional bounded JSON API adapter; no live calls yet | Official docs retrieved2026-10-05; explicit model required | https://api-docs.deepseek.com/zh-cn/guides/json_mode/ |
| GPT development assistance | Code authoring, independent review and documentation | Development process, not runtime AI evidence | No runtime LLM call recorded |

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
