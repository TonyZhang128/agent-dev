#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"
require_api_environment
mkdir -p verification
require_nvidia > verification/nvidia-smi.txt
cat verification/nvidia-smi.txt
export BUSINESS_API_URL="${BUSINESS_API_URL:-http://127.0.0.1:8309}"
uv run --locked --no-sync --no-dev python -m scripts.common.verify_agents
uv run --locked --no-sync --no-dev python -m scripts.common.verify_live
echo '业务真实推理已通过；GPU 驱动信息见 verification/nvidia-smi.txt。模型 GPU 占用需结合 nvidia-smi / vLLM 日志确认。'
