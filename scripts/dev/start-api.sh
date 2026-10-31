#!/bin/zsh
# 用法：zsh scripts/dev/start-api.sh [--debug] [uvicorn 参数...]
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { print -u2 "此脚本仅用于 macOS 开发；Linux 使用 scripts/prod/。"; exit 1; }
cd "${0:A:h:h:h}"
export UV_CACHE_DIR="$PWD/.cache/uv"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"

# 保持普通前台和 launchd 启动方式不变；仅在显式指定时启用 debugpy。
debug=0
uvicorn_args=()
for arg in "$@"; do
  case "$arg" in
    --debug) debug=1 ;;
    *) uvicorn_args+=("$arg") ;;
  esac
done

if (( debug )); then
  for arg in "${uvicorn_args[@]}"; do
    case "$arg" in
      --reload|--reload=*)
        print -u2 "调试模式不支持 uvicorn --reload；请在 VS Code 中重新启动调试。"
        exit 2
        ;;
    esac
  done
  exec uv run --locked python -m debugpy \
    --listen "127.0.0.1:${DEBUGPY_PORT:-5678}" \
    -m uvicorn app.main:app --host 127.0.0.1 --port 8309 "${uvicorn_args[@]}"
fi

exec uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8309 "$@"
