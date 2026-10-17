#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
export UV_CACHE_DIR="$PWD/.cache/uv"
export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_NO_INSTALL_CLEANUP=1
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"
mkdir -p .logs verification

print '1/5 检查工具（已有工具直接复用）'
[[ "$(uname -s)" == Darwin ]] || { print -u2 '此安装脚本适用于 macOS。Linux 使用 README 中的 uv 命令。'; exit 1; }
command -v brew >/dev/null || { print -u2 '未找到 Homebrew，请先从 https://brew.sh 安装后重试。'; exit 1; }
command -v uv >/dev/null || brew install uv
command -v ollama >/dev/null || brew install ollama
brew --version
uv --version
uv python find 3.12 >/dev/null 2>&1 || uv python install 3.12

print '2/5 创建 Python 环境并验证代码'
if [[ -f uv.lock ]]; then
  uv sync --locked
else
  uv sync
fi
[[ -e .env ]] || cp -n .env.example .env
uv run --locked python -m unittest discover -s tests -v

print '3/5 复用已有服务，或启动本项目的 macOS 用户会话服务'
zsh scripts/services.sh start
ready=0
for attempt in {1..30}; do
  if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && \
     curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
(( ready == 1 )) || { print -u2 '服务启动失败，请检查 .logs/*-service.*.log'; exit 1; }
ollama --version

print '4/5 下载或复用 Qwen3.5 9B Q4_K_M（约 6.6GB，已有层会复用）'
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3.5:9b-q4_K_M
OLLAMA_HOST=127.0.0.1:11434 ollama show qwen3.5:9b-q4_K_M

print '5/5 实际模型推理 + FastAPI 验证'
BUSINESS_API_URL="${BUSINESS_API_URL:-http://127.0.0.1:8000}" uv run --locked python -m scripts.verify_live
OLLAMA_HOST=127.0.0.1:11434 ollama ps
print '完成。服务已运行。查看状态：zsh scripts/services.sh status'
