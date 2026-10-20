#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -n "${PHOTONGUARD_PYTHON:-}" ]]; then
  pg_python="$PHOTONGUARD_PYTHON"
elif [[ -x .runtime/run-python ]]; then
  pg_python="$PWD/.runtime/run-python"
else
  printf '%s\n' '请先运行 bash runtime/bootstrap.sh，或设置 PHOTONGUARD_PYTHON 指向已有兼容解释器。' >&2
  exit 3
fi
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MPLBACKEND=Agg
exec "$pg_python" -B -m photonguard.workflow "$@"
