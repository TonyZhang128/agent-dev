#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"
require_nvidia
: "${VLLM_BIN:?请设置独立 vLLM 环境的可执行文件绝对路径，例如 /opt/vllm/bin/vllm}"
: "${VLLM_MODEL_PATH:?请设置 Hugging Face 模型 ID 或 Linux 本地模型目录}"
[[ "$VLLM_BIN" = /* && -x "$VLLM_BIN" ]] || { echo 'VLLM_BIN 必须是可执行文件的绝对路径。' >&2; exit 1; }
[[ "$VLLM_BIN" != "$PROJECT_ROOT/.venv/"* ]] || { echo 'vLLM 必须使用独立环境，不能安装到业务 .venv。' >&2; exit 1; }
: "${VLLM_API_KEY:?请设置 VLLM_API_KEY，并与业务 .env 中的 LLM_API_KEY 保持一致}"
# vLLM reads VLLM_API_KEY from the process environment; do not put keys in argv/logs.
export VLLM_API_KEY
exec "$VLLM_BIN" serve "$VLLM_MODEL_PATH" \
  --host 127.0.0.1 --port 8001 --served-model-name qwen-business "$@"
