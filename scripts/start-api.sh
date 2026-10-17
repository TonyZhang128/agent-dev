#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
export UV_CACHE_DIR="$PWD/.cache/uv"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"
exec uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 "$@"
