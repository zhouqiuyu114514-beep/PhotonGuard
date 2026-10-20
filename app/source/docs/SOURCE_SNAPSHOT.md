# Source-only development snapshot

Prepared 2026-10-05 for continued work in a private repository.

## Contents

- Current PhotonGuard package, including the bounded read-only Meep AST importer
- All application tests and the three real-Meep runtime tests
- Public, labeled development examples and their developer confirmation records
- Re-runnable JSON and script-import development matrix drivers
- Linux x86_64 installer, exact conda package lock, micromamba checksum and dependency version record
- Scope, scientific limitations, provenance and disabled DeepSeek integration documentation

The runtime package source and tests were copied byte-for-byte from the current development tree. README/runtime documentation and `.gitignore` were adjusted for this source-only transfer. `SOURCE_MANIFEST.sha256` lists each shipped file except the manifest itself.

## Excluded

Installed environments and binaries, caches, inputs, raw simulation logs, generated evidence, historical benchmark outputs, model requests/responses, credentials, local approval configurations/ledgers, private evaluation labels and existing delivery ZIPs are not included. Only explicitly labeled public development examples are present. Historical delivered archives have not been rewritten.

## Validation of this exact source snapshot

Using the already installed pinned Linux runtime, from the source snapshot directory:

```sh
PYTHONDONTWRITEBYTECODE=1 <existing-runtime>/run-python -m pytest -q -p no:cacheprovider tests runtime/test_runtime.py
```

Result: **311 tests passed, 13 subtests passed in 14.58 seconds**, including three real-Meep runtime tests. All 28 Python files parsed successfully, and `bash -n runtime/bootstrap.sh` passed. A pattern-based credential scan found only three intentionally synthetic/rejected examples in the offline backend tests; no real credential was found. This is a bounded source scan, not a security certification.

These checks reused the existing runtime and did **not** reinstall dependencies on the target cloud environment or rerun the full development matrix. That environment must run its own bootstrap and checks. There is no GitHub Actions workflow in this source snapshot.

## Scientific and model status

The validator supports the documented lossless one-dimensional film subset. AST extraction does not execute the input Python, prove arbitrary script equivalence, confirm user intent or establish PASS. Any PASS applies only to the verified canonical recipe, assumptions, discrete frequencies and recorded development tolerances.

The default runtime remains rules-only. DeepSeek compatibility tests use synthetic transport, and the configuration template is unapproved with a zero spending budget. No live DeepSeek call, measured AI advantage, independently held-out model evaluation or new secure credential setup is established by this upload.
