#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .runtime/run-python ]]; then
  printf '%s\n' '未找到本目录的官方 Meep 运行时。请先阅读 runtime/README.md；此启动器不会自动安装或改动其他项目。' >&2
  exit 3
fi
exec .runtime/run-python -m photonguard.workflow --data workflow-data --port 8766
