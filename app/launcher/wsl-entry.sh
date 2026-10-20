#!/usr/bin/env bash
set -euo pipefail
operation="${1:?operation required}"
package="${2:?package directory required}"
package="$(cd -- "$package" && pwd -P)"
launcher="$package/launcher"
case "$(uname -m)" in x86_64) ;; *) echo '此试用包目前支持 x64 Windows + WSL。' >&2; exit 12;; esac
lock_hash="$(sha256sum "$launcher/environment-linux-64.lock" | cut -c1-16)"
pg_runtime="${XDG_DATA_HOME:-$HOME/.local/share}/photonguard-trial/$lock_hash"
pg_python="$pg_runtime/env/bin/python"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$package/source"
export MAMBA_ROOT_PREFIX="$pg_runtime/mamba"
export XDG_CACHE_HOME="$pg_runtime/cache"
mkdir -p "$pg_runtime" "$package/data" "$package/logs"
download() {
    local url="$1" target="$2" expected="$3"
    if [[ -f "$target" ]] && echo "$expected  $target" | sha256sum --check --status; then return; fi
    if command -v curl >/dev/null; then curl --fail --location --retry 2 --connect-timeout 20 --max-time 600 "$url" -o "$target.part"
    elif command -v wget >/dev/null; then wget --timeout=30 --tries=3 "$url" -O "$target.part"
    else echo 'WSL 中缺少 curl/wget；请使用 Ubuntu 发行版后重试。' >&2; return 13; fi
    echo "$expected  $target.part" | sha256sum --check --status || { echo '下载校验失败，请重新启动重试。' >&2; return 14; }
    mv -- "$target.part" "$target"
}
if [[ "$operation" == setup ]]; then
    if [[ ! -x "$pg_runtime/bin/micromamba" ]]; then
        echo '首次准备运行环境，需联网下载；之后复用本机环境。'
        download 'https://conda.anaconda.org/conda-forge/linux-64/micromamba-2.9.0-0.tar.bz2' "$pg_runtime/micromamba.tar.bz2" '8761c382127e6363bd9e0a2451aa3ef90d071a79133f736e2f759a3bf13040dd'
        tar -xjf "$pg_runtime/micromamba.tar.bz2" -C "$pg_runtime" bin/micromamba
    fi
    if [[ ! -f "$pg_runtime/ready.json" ]]; then
        "$pg_runtime/bin/micromamba" create -y --no-rc --prefix "$pg_runtime/env" --file "$launcher/environment-linux-64.lock"
        download 'https://files.pythonhosted.org/packages/64/1c/bd81a37ff4db724957159e3d4badaa1c639e7f6465d541e307bc3fac669e/tmm-0.2.0-py3-none-any.whl' "$pg_runtime/tmm-0.2.0-py3-none-any.whl" 'f0cde811e0785b2c13887e8d12a4d089d028d3b19c67ae280f97587ad557f724'
        "$pg_python" -m pip install --no-index --no-deps "$pg_runtime/tmm-0.2.0-py3-none-any.whl"
        "$pg_python" -B "$launcher/server.py" verify "$package" "$pg_runtime/ready.json"
    fi
    "$pg_python" -B "$launcher/server.py" verify "$package"
elif [[ "$operation" == serve ]]; then
    [[ -f "$pg_runtime/ready.json" ]] || { echo '运行环境尚未准备完成。' >&2; exit 15; }
    exec "$pg_python" -B "$launcher/server.py" serve "$package" "${3:?port required}"
elif [[ "$operation" == stop ]]; then
    [[ -x "$pg_python" ]] || exit 0
    exec "$pg_python" -B "$launcher/server.py" stop "$package"
else
    echo 'Unknown launcher operation' >&2; exit 16
fi
