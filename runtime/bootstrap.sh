#!/usr/bin/env bash
# Install the real serial PyMeep runtime without root or global Python changes.
set -euo pipefail
PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME="$PROJECT/.runtime"
export HOME="$RUNTIME/home"
export MAMBA_ROOT_PREFIX="$RUNTIME/mamba"
export CONDA_PKGS_DIRS="$MAMBA_ROOT_PREFIX/pkgs"
export XDG_CACHE_HOME="$RUNTIME/cache"
mkdir -p "$RUNTIME"/{bin,downloads,logs} "$HOME/.conda" "$XDG_CACHE_HOME"
if [[ ! -x "$RUNTIME/bin/micromamba" ]]; then
  curl -fL --retry 2 \
    https://conda.anaconda.org/conda-forge/linux-64/micromamba-2.9.0-0.tar.bz2 \
    -o "$RUNTIME/downloads/micromamba.tar.bz2"
  (cd "$RUNTIME/downloads" && sha256sum --check "$PROJECT/runtime/micromamba.sha256")
  tar -xjf "$RUNTIME/downloads/micromamba.tar.bz2" -C "$RUNTIME" bin/micromamba
fi
if [[ -x "$RUNTIME/env/bin/python" ]]; then
  echo "Using existing project-local runtime; verifying below."
elif [[ -f "$PROJECT/runtime/conda-linux-64.lock" ]]; then
  "$RUNTIME/bin/micromamba" create -y --no-rc -p "$RUNTIME/env" \
    --file "$PROJECT/runtime/conda-linux-64.lock" \
    2>&1 | tee "$RUNTIME/logs/bootstrap.log"
else
  "$RUNTIME/bin/micromamba" create -y --no-rc --override-channels \
    -c conda-forge -p "$RUNTIME/env" --file "$PROJECT/runtime/environment.yml" \
    2>&1 | tee "$RUNTIME/logs/bootstrap.log"
fi
cp "$PROJECT/runtime/run-python.template" "$RUNTIME/run-python"
chmod +x "$RUNTIME/run-python"
"$RUNTIME/run-python" "$PROJECT/runtime/smoke_runtime.py" \
  2>&1 | tee "$RUNTIME/logs/smoke-runtime.log"
