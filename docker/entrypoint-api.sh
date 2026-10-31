#!/usr/bin/env bash
# 业务 API 容器入口：只做配置自检和启动，运行时不安装或同步依赖。
set -euo pipefail

# 误用 Ollama 地址、开发模型名或占位密钥时，启动即失败。
python -m scripts.prod.check_config

exec uvicorn app.main:app \
  --host "${API_HOST:-0.0.0.0}" \
  --port "${API_PORT:-8309}" \
  --workers "${API_WORKERS:-1}" \
  --timeout-graceful-shutdown "${API_GRACEFUL_TIMEOUT:-30}" \
  "$@"
