#!/bin/zsh
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { print -u2 "此脚本仅用于 macOS 开发；Linux 使用 scripts/prod/。"; exit 1; }
cd "${0:A:h:h:h}"
export UV_CACHE_DIR="$PWD/.cache/uv"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"
exec uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8309 "$@"
