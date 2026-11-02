#!/bin/zsh
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { print -u2 "此脚本仅用于 macOS 开发；Linux 使用 scripts/prod/。"; exit 1; }
cd "${0:A:h:h:h}"
command -v ollama >/dev/null || { print -u2 '请先运行 brew install ollama'; exit 1; }
# 默认值只影响当前进程；不要修改 Shell profile 或 launch agent。
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-8192}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
export OLLAMA_NOPRUNE="${OLLAMA_NOPRUNE:-true}"
# 复用标准 Ollama 存储目录，或使用显式传入的 OLLAMA_MODELS。
exec ollama serve
