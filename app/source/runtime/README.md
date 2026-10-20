# Real Meep runtime

This is the **actual serial Meep FDTD solver**, installed from the official
`conda-forge` PyMeep distribution. It is not the unrelated PyPI package named
`meep`, and it is not a mock. No root access is required.

## Run in this project

From the project root:

```sh
.runtime/run-python runtime/smoke_runtime.py
.runtime/run-python -m pytest -q runtime/test_runtime.py
.runtime/run-python -m pytest -q
.runtime/run-python -m photonguard --help
```

The executable is `.runtime/env/bin/python`. The recommended wrapper
`.runtime/run-python` selects the noninteractive Matplotlib backend, places caches
under `.runtime/cache`, and defaults OpenMP and OpenBLAS to one thread unless
explicitly configured otherwise. Application source imports work from the project
root. There is no need to alter the system Python or activate a shell environment.

## Recreate from trusted packages

Supported and tested target: **Linux x86_64**, Debian 13, with a compatible glibc.
The pinned lock is platform-specific; it is not a macOS or Windows lock.

The bootstrap also needs `bash`, `curl`, `tar`, `sha256sum`, and `bzip2`.
A minimal Ubuntu WSL installation may omit `bzip2`; install it from Ubuntu's
official package repositories before running the bootstrap:

```sh
sudo apt-get update
sudo apt-get install --no-install-recommends bzip2
```

This supplies the archive decompressor only; the solver still comes from the
unchanged conda-forge lock below.

```sh
bash runtime/bootstrap.sh
```

The installer downloads micromamba **2.9.0 build 0** from conda-forge, checks its
SHA-256 against `micromamba.sha256`, and extracts only its executable. It installs
all package builds using `conda-linux-64.lock` (an explicit conda lock with package
URLs and hashes). `environment.yml` also records the main dependency pins.
An existing project-local interpreter is preserved and smoke-tested, rather than
overwritten. To rebuild a different environment, first move the old `.runtime`
folder aside. The runtime is roughly 1 GB including downloaded packages and cache.

The installation's HOME, conda package cache, environment, and plotting caches are
all project-local. This is necessary in this cloud workspace because the ordinary
home directory is read-only. No global package installation, credentials, paid
service, or user-computer access is involved.

## Verified dependencies

- Python 3.12.14
- Meep / PyMeep 1.34.0, `nompi_py312h1c86e9f_101`
- NumPy 2.5.3, SciPy 1.18.1
- h5py 3.16.0, HDF5 1.14.6 (serial)
- Matplotlib 3.11.2
- tmm 0.2.0
- pytest 9.1.1

`versions.json` contains all 124 installed package versions and build strings.

## Actual verification

On 2026-10-05 UTC, `smoke_runtime.py` ran a real one-dimensional Meep vacuum
propagation problem for **2,800 FDTD timesteps**, reaching Meep time 70.0 at
resolution 20. The downstream spectral flux was **1.5713144172499156**, finite
and positive. An independent tmm lossless air / n=1.5 film / air calculation gave
R = 0.14792899408284022 and T = 0.8520710059171595, with R+T =
0.9999999999999997. These verify installation and numerical execution; they do
not certify arbitrary optical models.

The separate runtime pytest suite passed **3 tests in 0.62 seconds**. Historical logs are preserved in the separate frozen delivery, not in this
source-only repository. A fresh bootstrap writes its own verification logs to
`.runtime/logs/`. Application validation is separate.

## Upstream references

- [Meep installation documentation](https://meep.readthedocs.io/en/latest/Installation/)
- [Official conda-forge PyMeep feedstock](https://github.com/conda-forge/pymeep-feedstock)
- [Meep source](https://github.com/NanoComp/meep)

Do not use `pip install meep` to obtain this solver. The official documentation
recommends the conda package named `pymeep`, whose Python import is `meep`.
