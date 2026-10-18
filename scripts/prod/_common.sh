#!/usr/bin/env bash
# Source from Linux deployment entry points; do not source application .env as shell code.
set -euo pipefail
[[ "$(uname -s)" == Linux ]] || { echo '此脚本仅用于 Linux 部署；Mac 使用 scripts/dev/。' >&2; exit 1; }
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_ROOT/.cache/uv}"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"

require_uv() {
  command -v uv >/dev/null || { echo '请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
}

require_nvidia() {
  command -v nvidia-smi >/dev/null || { echo '未找到 nvidia-smi，请先安装并验证 NVIDIA 驱动。' >&2; exit 1; }
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
}

require_api_environment() {
  require_uv
  [[ -x .venv/bin/python && -x .venv/bin/uvicorn ]] || { echo '请先运行 bash scripts/prod/setup.sh。' >&2; exit 1; }
  # Settings preserves process-environment precedence and validates the existing .env.
  uv run --locked --no-sync --no-dev python -m scripts.prod.check_config
}
