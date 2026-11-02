#!/usr/bin/env bash
# vLLM 容器入口：模型路径和密钥只从环境变量读取，不写入命令行或日志。
set -euo pipefail

: "${VLLM_MODEL_PATH:?请设置 VLLM_MODEL_PATH，例如 /models/Qwen3.5-9B-Q4_K_M.gguf}"
: "${VLLM_API_KEY:?请设置 VLLM_API_KEY，并与业务 API 的 LLM_API_KEY 保持一致}"

VLLM_BIN="${VLLM_BIN:-vllm}"
command -v "$VLLM_BIN" >/dev/null 2>&1 || {
  echo "未找到 vLLM 可执行文件：$VLLM_BIN" >&2
  exit 1
}

if [[ ! -e "$VLLM_MODEL_PATH" ]]; then
  if [[ "${HF_HUB_OFFLINE:-1}" != "0" ]]; then
    echo "VLLM_MODEL_PATH 不存在：$VLLM_MODEL_PATH；当前 HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}，不会联网下载。" >&2
    exit 1
  fi
  echo "VLLM_MODEL_PATH 不是本地路径，按 Hugging Face 模型 ID 处理：$VLLM_MODEL_PATH" >&2
fi

# vLLM 原生读取该变量；不要改用 --api-key 参数。
export VLLM_API_KEY

exec "$VLLM_BIN" serve "$VLLM_MODEL_PATH" \
  --served-model-name "${VLLM_SERVED_MODEL_NAME:-highway-agent}" \
  --host "${VLLM_HOST:-0.0.0.0}" \
  --port "${VLLM_PORT:-8001}" \
  "$@"
