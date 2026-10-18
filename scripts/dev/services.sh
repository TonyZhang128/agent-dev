#!/bin/zsh
# User-session services survive the shell that starts them; no login files are edited.
set -euo pipefail
cd "${0:A:h:h:h}"
[[ "$(uname -s)" == Darwin ]] || { print -u2 '此脚本使用 macOS launchd。'; exit 1; }
root="$PWD"
mkdir -p .logs

start_job() {
  local name="$1" script="$2"
  local label="local.qwen-business-dev.$name"
  if launchctl list "$label" >/dev/null 2>&1; then
    print "已注册：$label"
    return
  fi
  local -a job_env
  job_env=("PATH=$PATH" "NO_PROXY=localhost,127.0.0.1,::1" "no_proxy=localhost,127.0.0.1,::1")
  if [[ "$name" == ollama && -n "${HTTPS_PROXY:-}" ]]; then
    job_env+=("HTTPS_PROXY=$HTTPS_PROXY" "https_proxy=$HTTPS_PROXY")
  fi
  launchctl submit -l "$label" \
    -o "$root/.logs/$name-service.out.log" -e "$root/.logs/$name-service.err.log" \
    -- /usr/bin/env "${job_env[@]}" /bin/zsh "$root/scripts/dev/$script"
  print "已启动：$label"
}

stop_job() {
  local name="$1" port="$2"
  local label="local.qwen-business-dev.$name"
  if launchctl list "$label" >/dev/null 2>&1; then
    launchctl remove "$label"
    for attempt in {1..100}; do
      if ! launchctl list "$label" >/dev/null 2>&1 && \
         ! /usr/sbin/lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        print "已停止：$label"
        return
      fi
      sleep 0.1
    done
    print -u2 "服务任务仍在注销或端口 $port 尚未释放；稍后重试。"
    return 1
  fi
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
    if ! curl --noproxy '*' -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      start_job api start-api.sh
    else
      print '端口 8000 已有健康接口，保留现有进程'
    fi
    ;;
  stop)
    stop_job api 8000
    stop_job ollama 11434
    ;;
  restart-api)
    stop_job api 8000
    if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
      print -u2 '端口 8000 被其他进程占用，未停止该进程。'
      exit 1
    fi
    start_job api start-api.sh
    ;;
  status)
    for name in ollama api; do
      launchctl list "local.qwen-business-dev.$name" 2>/dev/null || print "$name：未注册本项目服务"
    done
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:11434/api/version || true
    print
    curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8000/health || true
    print
    ;;
  *) print -u2 '用法：zsh scripts/dev/services.sh start|stop|status|restart-api'; exit 2 ;;
esac
