#!/bin/zsh
# 用户会话任务在启动它的 Shell 退出后继续运行；不修改登录文件。
set -euo pipefail # 有错就退出
cd "${0:A:h:h:h}" # 进入项目根目录
# 判断macOS
[[ "$(uname -s)" == Darwin ]] || { print -u2 '此脚本使用 macOS launchd。'; exit 1; }
root="$PWD"
mkdir -p .logs

start_job() {
  local name="$1" script="$2" # 函数位置参数
  shift 2
  local label="local.highway-agent.$name"
  if launchctl list "$label" >/dev/null 2>&1; then
    print "已注册：$label"
    return
  fi
  local -a job_env
  job_env=("PATH=$PATH" "NO_PROXY=localhost,127.0.0.1,::1" "no_proxy=localhost,127.0.0.1,::1")
  if [[ "$name" == ollama && -n "${HTTPS_PROXY:-}" ]]; then
    job_env+=("HTTPS_PROXY=$HTTPS_PROXY" "https_proxy=$HTTPS_PROXY")
  fi
  # 保持 Ollama 日志名，算法服务日志使用统一程序标识。
  local log_name="${name%-service}-service"
  # 注册并启动任务
  launchctl submit -l "$label" \
    -o "$root/.logs/$log_name.out.log" -e "$root/.logs/$log_name.err.log" \
    -- /usr/bin/env "${job_env[@]}" /bin/zsh "$root/scripts/dev/$script" "$@"
  print "已启动：$label"
}

stop_job() {
  local name="$1" port="$2"
  local label="local.highway-agent.$name"
  if launchctl list "$label" >/dev/null 2>&1; then
    launchctl remove "$label"
    for attempt in {1..100}; do
      if ! launchctl list "$label" >/dev/null 2>&1 && \
         { [[ -z "$port" ]] || ! /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; }; then
        print "已停止：$label"
        return
      fi
      sleep 0.1
    done
    print -u2 "服务任务仍在注销或端口 $port 尚未释放；稍后重试。"
    return 1
  fi
}

restart_api() {
  stop_job agent-service 8309
  if /usr/sbin/lsof -nP -iTCP:8309 -sTCP:LISTEN >/dev/null 2>&1; then
    print -u2 '端口 8309 被其他进程占用，未停止该进程。'
    exit 1
  fi
  start_job agent-service start-api.sh "$@"
}

case "${1:-status}" in
  start)
    command -v ollama >/dev/null
    command -v uv >/dev/null
    if ! curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
      start_job ollama start-ollama.sh
    else
      print '复用已运行的 Ollama'
    fi
    if ! curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8309/health >/dev/null 2>&1; then
      start_job agent-service start-api.sh
    else
      print '端口 8309 已有健康接口，保留现有进程'
    fi
    ;;
  stop)
    stop_job agent-service 8309
    stop_job ollama 11434
    ;;
  restart-api)
    restart_api
    ;    print '请选择 VS Code 的 Debug agent-service (attach) 连接 127.0.0.1:5678。'
    ;;
  debug-api)
    restart_api --debug
    print '请选择 VS Code 的 Debug agent-service (attach) 连接 127.0.0.1:5678。'
    ;;
  status)
    for name in ollama agent-service; do
      launchctl list "local.highway-agent.$name" 2>/dev/null || print "$name：未注册本项目服务"
    done
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:11434/api/version || true
    print
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8309/health || true
    print
    ;;
  *) print -u2 '用法：zsh scripts/dev/services.sh start|stop|status|restart-api|debug-api'; exit 2 ;;
esac
