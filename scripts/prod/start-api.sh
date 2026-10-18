#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"
for arg in "$@"; do
  case "$arg" in
    --reload*) echo '生产入口禁止 --reload；开发使用 scripts/dev/start-api.sh。' >&2; exit 2 ;;
  esac
done
require_api_environment
# Dependencies are installed at setup time, never synchronized during service startup.
exec uv run --locked --no-sync --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000 "$@"
