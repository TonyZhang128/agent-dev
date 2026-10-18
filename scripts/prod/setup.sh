#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/_common.sh"
require_uv
uv --version
uv python find 3.12 >/dev/null 2>&1 || uv python install 3.12
uv sync --locked --no-dev
if [[ ! -e .env ]]; then
  (umask 077; cp -n scripts/prod/api.env.example .env)
  echo '已从生产模板创建 .env，请按模型服务填写配置。'
else
  echo '保留已有 .env，请确认其指向生产模型服务。'
fi
echo '业务环境已准备好；vLLM 需在独立环境部署，GPU 检查由 start-vllm.sh / verify.sh 执行。'
