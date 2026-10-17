#!/bin/zsh
set -uo pipefail
# Explicit proxy URL argument, or the detected v2rayN local HTTP endpoint.
proxy_url="${1:-http://127.0.0.1:10808}"
print '检测模式：直连和显式代理。不会修改系统代理，也不会显示代理凭据。'
for target in https://formulae.brew.sh/api/formula/ollama.json https://pypi.org/simple/fastapi/ https://registry.ollama.ai/v2/; do
  print -r -- "目标：$target"
  print '  直连：'
  curl --noproxy '*' --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '  HTTP %{http_code}\n' "$target"
  print '  代理：'
  curl --noproxy '' --proxy "$proxy_url" --connect-timeout 5 --max-time 15 -sS -o /dev/null -w '  HTTP %{http_code}\n' "$target"
done
