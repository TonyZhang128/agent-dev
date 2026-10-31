#!/bin/zsh
# 前台隧道入口；后台任务管理由 services.sh 负责。
set -euo pipefail
cd "${0:A:h:h:h}"
[[ "$(uname -s)" == Darwin ]] || { print -u2 '此脚本用于 macOS 开发环境。'; exit 1; }
case "${1:-}" in
  ''|--check) ;;
  *) print -u2 '用法：zsh scripts/dev/start-frpc.sh [--check]'; exit 2 ;;
esac
(( $# <= 1 )) || { print -u2 '参数过多。'; exit 2; }
command -v frpc >/dev/null || { print -u2 '未安装 frpc，请运行 brew install frpc。'; exit 1; }
[[ -s config/dev/frp/frpc.toml ]] || { print -u2 '缺少 config/dev/frp/frpc.toml。'; exit 1; }
for credential in token ca.crt; do
  [[ -s ".secrets/frp/$credential" ]] || {
    print -u2 "缺少或为空：.secrets/frp/$credential；配置方法见 docs/frp.md。"
    exit 1
  }
done
frpc verify -c config/dev/frp/frpc.toml
if ! curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8309/health >/dev/null 2>&1; then
  print -u2 '本机 FastAPI 127.0.0.1:8309 尚未就绪；先运行 zsh scripts/dev/services.sh start。'
  exit 1
fi
[[ "${1:-}" == --check ]] && exit 0
exec frpc -c config/dev/frp/frpc.toml
