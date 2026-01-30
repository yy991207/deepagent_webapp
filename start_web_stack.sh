#!/bin/bash
set -e

ROOT_DIR="/Users/yang/deepagents-webapp"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_MODULE="backend.api.web_app:app"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="7777"
FRONTEND_PORT="5173"
PYTHON_CMD=("python")
NODE_BIN="npm"
RUNTIME_DIR="$ROOT_DIR/.runtime"
PID_DIR="$RUNTIME_DIR/pids"
LOG_DIR="$RUNTIME_DIR/logs"

# 服务 PID 文件
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
CELERY_WORKER_PID_FILE="$PID_DIR/celery_worker.pid"
CELERY_BEAT_PID_FILE="$PID_DIR/celery_beat.pid"
PODCAST_AGENT_PID_FILE="$PID_DIR/podcast_agent.pid"

# 服务日志文件
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
CELERY_WORKER_LOG="$LOG_DIR/celery_worker.log"
CELERY_BEAT_LOG="$LOG_DIR/celery_beat.log"
PODCAST_AGENT_LOG="$LOG_DIR/podcast_agent.log"

# Celery 配置
CELERY_APP="backend.celery_scheduler"
CELERY_WORKER_NAME="${CELERY_WORKER_NAME:-podcast_worker}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-4}"
CELERY_LOG_LEVEL="${CELERY_LOG_LEVEL:-info}"
CELERY_QUEUES="${CELERY_QUEUES:-celery,podcast}"

# Podcast Agent Service 配置
PODCAST_AGENT_HOST="${PODCAST_AGENT_HOST:-0.0.0.0}"
PODCAST_AGENT_PORT="${PODCAST_AGENT_PORT:-8888}"

# 使用 deepagent conda 环境
if [ -x "/Users/yang/miniconda3/envs/deepagent/bin/python" ]; then
  PYTHON_CMD=("/Users/yang/miniconda3/envs/deepagent/bin/python")
elif [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
  PYTHON_CMD=("$CONDA_PREFIX/bin/python")
fi

# Celery 命令（使用相同的 Python 环境）
# 优先使用 deepagent 环境的 celery
if [ -x "/Users/yang/miniconda3/envs/deepagent/bin/celery" ]; then
  CELERY_CMD="/Users/yang/miniconda3/envs/deepagent/bin/celery"
elif [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/celery" ]; then
  CELERY_CMD="$CONDA_PREFIX/bin/celery"
else
  # 从 PYTHON_CMD 路径推导
  CELERY_CMD="${PYTHON_CMD[0]%/python}/celery"
  if [ ! -x "$CELERY_CMD" ]; then
    CELERY_CMD="celery"
  fi
fi

mkdir -p "$PID_DIR" "$LOG_DIR"

log_info() {
  echo "[INFO] $1"
}

log_warn() {
  echo "[WARN] $1"
}

log_error() {
  echo "[ERROR] $1"
}

is_running() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file")
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
  fi
  return 1
}

kill_pid_file() {
  local pid_file="$1"
  if [ -f "$pid_file" ]; then
    local pid
    pid=$(cat "$pid_file")
    if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
    rm -f "$pid_file"
  fi
}

stop_port_process() {
  local port="$1"
  local pids
  pids=$(lsof -ti ":$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    log_warn "端口 $port 被占用，尝试释放"
    echo "$pids" | xargs kill >/dev/null 2>&1 || true
    sleep 0.5
  fi
}

# ==============================================================================
# 后端服务
# ==============================================================================
start_backend() {
  if is_running "$BACKEND_PID_FILE"; then
    log_info "后端已在运行"
    return
  fi
  : >"$BACKEND_LOG"
  stop_port_process "$BACKEND_PORT"
  log_info "启动后端服务"
  local reload_flag=""
  if [ "${BACKEND_RELOAD:-0}" = "1" ]; then
    reload_flag="--reload"
  fi
  cd "$ROOT_DIR" && "${PYTHON_CMD[@]}" -m uvicorn "$BACKEND_MODULE" --host "$BACKEND_HOST" --port "$BACKEND_PORT" $reload_flag --log-level debug --log-config "$ROOT_DIR/uvicorn_log_config.yaml" \
    >"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID_FILE"
  log_info "后端 PID: $(cat "$BACKEND_PID_FILE")"
}

stop_backend() {
  log_info "停止后端服务"
  kill_pid_file "$BACKEND_PID_FILE"
  stop_port_process "$BACKEND_PORT"
}

# ==============================================================================
# 前端服务
# ==============================================================================
start_frontend() {
  if is_running "$FRONTEND_PID_FILE"; then
    log_info "前端已在运行"
    return
  fi
  stop_port_process "$FRONTEND_PORT"
  log_info "启动前端服务"
  (cd "$FRONTEND_DIR" && "$NODE_BIN" run dev -- --port "$FRONTEND_PORT") >"$FRONTEND_LOG" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
  log_info "前端 PID: $(cat "$FRONTEND_PID_FILE")"
}

stop_frontend() {
  log_info "停止前端服务"
  kill_pid_file "$FRONTEND_PID_FILE"
}

# ==============================================================================
# Celery Worker 服务
# ==============================================================================
start_celery_worker() {
  if is_running "$CELERY_WORKER_PID_FILE"; then
    log_info "Celery Worker 已在运行"
    return
  fi
  : >"$CELERY_WORKER_LOG"
  log_info "启动 Celery Worker 服务"
  cd "$ROOT_DIR" && "$CELERY_CMD" -A "$CELERY_APP" worker \
    --hostname="${CELERY_WORKER_NAME}@%h" \
    --concurrency="$CELERY_CONCURRENCY" \
    --loglevel="$CELERY_LOG_LEVEL" \
    --queues="$CELERY_QUEUES" \
    >"$CELERY_WORKER_LOG" 2>&1 &
  echo $! >"$CELERY_WORKER_PID_FILE"
  log_info "Celery Worker PID: $(cat "$CELERY_WORKER_PID_FILE")"
}

stop_celery_worker() {
  log_info "停止 Celery Worker 服务"
  kill_pid_file "$CELERY_WORKER_PID_FILE"
  # 额外清理可能残留的 worker 进程
  pkill -f "celery.*$CELERY_APP.*worker" 2>/dev/null || true
}

# ==============================================================================
# Celery Beat 服务
# ==============================================================================
start_celery_beat() {
  if is_running "$CELERY_BEAT_PID_FILE"; then
    log_info "Celery Beat 已在运行"
    return
  fi
  : >"$CELERY_BEAT_LOG"
  log_info "启动 Celery Beat 服务"
  cd "$ROOT_DIR" && "$CELERY_CMD" -A "$CELERY_APP" beat \
    --loglevel="$CELERY_LOG_LEVEL" \
    --schedule="$RUNTIME_DIR/celerybeat-schedule" \
    >"$CELERY_BEAT_LOG" 2>&1 &
  echo $! >"$CELERY_BEAT_PID_FILE"
  log_info "Celery Beat PID: $(cat "$CELERY_BEAT_PID_FILE")"
}

stop_celery_beat() {
  log_info "停止 Celery Beat 服务"
  kill_pid_file "$CELERY_BEAT_PID_FILE"
  pkill -f "celery.*$CELERY_APP.*beat" 2>/dev/null || true
}

# ==============================================================================
# Podcast Agent Service（独立播客生成服务）
# ==============================================================================
start_podcast_agent() {
  if is_running "$PODCAST_AGENT_PID_FILE"; then
    log_info "Podcast Agent Service 已在运行"
    return
  fi
  : >"$PODCAST_AGENT_LOG"
  stop_port_process "$PODCAST_AGENT_PORT"
  log_info "启动 Podcast Agent Service"
  # 加载 .env 环境变量
  if [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
  fi
  cd "$ROOT_DIR" && PODCAST_AGENT_HOST="$PODCAST_AGENT_HOST" PODCAST_AGENT_PORT="$PODCAST_AGENT_PORT" \
    "${PYTHON_CMD[@]}" -m uvicorn backend.services.podcast_agent_service:app \
    --host "$PODCAST_AGENT_HOST" --port "$PODCAST_AGENT_PORT" \
    >"$PODCAST_AGENT_LOG" 2>&1 &
  echo $! >"$PODCAST_AGENT_PID_FILE"
  log_info "Podcast Agent Service PID: $(cat "$PODCAST_AGENT_PID_FILE")"
}

stop_podcast_agent() {
  log_info "停止 Podcast Agent Service"
  kill_pid_file "$PODCAST_AGENT_PID_FILE"
  stop_port_process "$PODCAST_AGENT_PORT"
}

# ==============================================================================
# 统一启动/停止/重启
# ==============================================================================
start_all() {
  start_backend
  start_frontend
  start_celery_worker
  start_celery_beat
  start_podcast_agent
}

stop_all() {
  stop_podcast_agent
  stop_celery_beat
  stop_celery_worker
  stop_frontend
  stop_backend
}

restart_all() {
  stop_all
  sleep 1
  start_all
}

# ==============================================================================
# 服务状态
# ==============================================================================
status() {
  echo ""
  echo "╔═══════════════════════════════════════════════════════════════════╗"
  echo "║                         服务状态一览                               ║"
  echo "╠═══════════════════════════════════════════════════════════════════╣"
  
  # 后端状态
  if is_running "$BACKEND_PID_FILE"; then
    printf "║ %-20s │ %-10s │ PID: %-20s ║\n" "后端服务" "运行中 ✓" "$(cat "$BACKEND_PID_FILE")"
  else
    printf "║ %-20s │ %-10s │ %-25s ║\n" "后端服务" "已停止 ✗" ""
  fi
  
  # 前端状态
  if is_running "$FRONTEND_PID_FILE"; then
    printf "║ %-20s │ %-10s │ PID: %-20s ║\n" "前端服务" "运行中 ✓" "$(cat "$FRONTEND_PID_FILE")"
  else
    printf "║ %-20s │ %-10s │ %-25s ║\n" "前端服务" "已停止 ✗" ""
  fi
  
  # Celery Worker 状态
  if is_running "$CELERY_WORKER_PID_FILE"; then
    printf "║ %-20s │ %-10s │ PID: %-20s ║\n" "Celery Worker" "运行中 ✓" "$(cat "$CELERY_WORKER_PID_FILE")"
  else
    printf "║ %-20s │ %-10s │ %-25s ║\n" "Celery Worker" "已停止 ✗" ""
  fi
  
  # Celery Beat 状态
  if is_running "$CELERY_BEAT_PID_FILE"; then
    printf "║ %-20s │ %-10s │ PID: %-20s ║\n" "Celery Beat" "运行中 ✓" "$(cat "$CELERY_BEAT_PID_FILE")"
  else
    printf "║ %-20s │ %-10s │ %-25s ║\n" "Celery Beat" "已停止 ✗" ""
  fi
  
  # Podcast Agent 状态
  if is_running "$PODCAST_AGENT_PID_FILE"; then
    printf "║ %-20s │ %-10s │ PID: %-20s ║\n" "Podcast Agent" "运行中 ✓" "$(cat "$PODCAST_AGENT_PID_FILE")"
  else
    printf "║ %-20s │ %-10s │ %-25s ║\n" "Podcast Agent" "已停止 ✗" ""
  fi
  
  echo "╚═══════════════════════════════════════════════════════════════════╝"
  echo ""
}

# ==============================================================================
# 日志查看（交互式菜单）
# ==============================================================================
logs_menu() {
  echo ""
  echo "╔═══════════════════════════════════════════════════════════════════╗"
  echo "║                       选择要查看的日志                             ║"
  echo "╠═══════════════════════════════════════════════════════════════════╣"
  echo "║  1) 后端服务日志                                                   ║"
  echo "║  2) 前端服务日志                                                   ║"
  echo "║  3) Celery Worker 日志                                            ║"
  echo "║  4) Celery Beat 日志                                              ║"
  echo "║  5) Podcast Agent Service 日志                                    ║"
  echo "║  6) 全部日志（合并显示）                                           ║"
  echo "║  0) 退出                                                           ║"
  echo "╚═══════════════════════════════════════════════════════════════════╝"
  echo ""
  read -p "请输入序号 [0-6]: " choice
  
  case "$choice" in
    1)
      log_info "查看后端服务日志，按 Ctrl+C 退出"
      touch "$BACKEND_LOG"
      tail -n 200 -f "$BACKEND_LOG"
      ;;
    2)
      log_info "查看前端服务日志，按 Ctrl+C 退出"
      touch "$FRONTEND_LOG"
      tail -n 200 -f "$FRONTEND_LOG"
      ;;
    3)
      log_info "查看 Celery Worker 日志，按 Ctrl+C 退出"
      touch "$CELERY_WORKER_LOG"
      tail -n 200 -f "$CELERY_WORKER_LOG"
      ;;
    4)
      log_info "查看 Celery Beat 日志，按 Ctrl+C 退出"
      touch "$CELERY_BEAT_LOG"
      tail -n 200 -f "$CELERY_BEAT_LOG"
      ;;
    5)
      log_info "查看 Podcast Agent Service 日志，按 Ctrl+C 退出"
      touch "$PODCAST_AGENT_LOG"
      tail -n 200 -f "$PODCAST_AGENT_LOG"
      ;;
    6)
      log_info "查看全部日志，按 Ctrl+C 退出"
      touch "$BACKEND_LOG" "$FRONTEND_LOG" "$CELERY_WORKER_LOG" "$CELERY_BEAT_LOG" "$PODCAST_AGENT_LOG"
      tail -n 50 -f "$BACKEND_LOG" "$FRONTEND_LOG" "$CELERY_WORKER_LOG" "$CELERY_BEAT_LOG" "$PODCAST_AGENT_LOG"
      ;;
    0)
      exit 0
      ;;
    *)
      log_error "无效选项: $choice"
      exit 1
      ;;
  esac
}

# 直接查看所有日志（兼容旧行为）
logs() {
  log_info "实时日志输出，按 Ctrl+C 退出"
  touch "$BACKEND_LOG" "$FRONTEND_LOG" "$CELERY_WORKER_LOG" "$CELERY_BEAT_LOG" "$PODCAST_AGENT_LOG"
  tail -n 200 -f "$BACKEND_LOG" "$FRONTEND_LOG" "$CELERY_WORKER_LOG" "$CELERY_BEAT_LOG" "$PODCAST_AGENT_LOG"
}

# ==============================================================================
# 帮助信息
# ==============================================================================
show_help() {
  echo ""
  echo "用法: $0 <命令> [服务名]"
  echo ""
  echo "命令:"
  echo "  start [服务]     启动服务（不指定则启动全部）"
  echo "  stop [服务]      停止服务（不指定则停止全部）"
  echo "  restart [服务]   重启服务（不指定则重启全部）"
  echo "  status           查看所有服务状态"
  echo "  logs             交互式选择查看日志"
  echo "  logs-all         查看全部日志（合并）"
  echo ""
  echo "可选服务名:"
  echo "  backend          后端 API 服务"
  echo "  frontend         前端 Web 服务"
  echo "  celery-worker    Celery Worker（任务投递）"
  echo "  celery-beat      Celery Beat（定时调度）"
  echo "  celery           Celery Worker + Beat"
  echo "  podcast-agent    Podcast Agent Service（播客生成执行）"
  echo "  agent            同 podcast-agent"
  echo ""
  echo "示例:"
  echo "  $0 start                    # 启动全部服务"
  echo "  $0 start celery             # 只启动 Celery 服务"
  echo "  $0 start podcast-agent      # 只启动 Podcast Agent Service"
  echo "  $0 stop backend             # 只停止后端服务"
  echo "  $0 restart celery-worker    # 重启 Celery Worker"
  echo "  $0 logs                     # 交互式选择日志"
  echo ""
  echo "环境变量:"
  echo "  BACKEND_RELOAD=1            启用后端热重载"
  echo "  CELERY_CONCURRENCY=8        Celery Worker 并发数（默认 4）"
  echo "  CELERY_LOG_LEVEL=debug      Celery 日志级别（默认 info）"
  echo "  PODCAST_AGENT_PORT=8888     Podcast Agent 端口（默认 8888）"
  echo "  USE_CELERY=1                启用 Celery 模式（投递+回调）"
  echo ""
  echo "架构说明（投递+Callback 模式）:"
  echo "  API → Celery Worker（快速投递）→ Podcast Agent（异步执行）→ Callback"
  echo ""
}

# ==============================================================================
# 主入口
# ==============================================================================
case "$1" in
  start)
    case "$2" in
      backend)        start_backend ;;
      frontend)       start_frontend ;;
      celery-worker)  start_celery_worker ;;
      celery-beat)    start_celery_beat ;;
      celery)         start_celery_worker; start_celery_beat ;;
      podcast-agent|agent) start_podcast_agent ;;
      "")             start_all ;;
      *)              log_error "未知服务: $2"; show_help; exit 1 ;;
    esac
    ;;
  stop)
    case "$2" in
      backend)        stop_backend ;;
      frontend)       stop_frontend ;;
      celery-worker)  stop_celery_worker ;;
      celery-beat)    stop_celery_beat ;;
      celery)         stop_celery_beat; stop_celery_worker ;;
      podcast-agent|agent) stop_podcast_agent ;;
      "")             stop_all ;;
      *)              log_error "未知服务: $2"; show_help; exit 1 ;;
    esac
    ;;
  restart)
    case "$2" in
      backend)        stop_backend; start_backend ;;
      frontend)       stop_frontend; start_frontend ;;
      celery-worker)  stop_celery_worker; start_celery_worker ;;
      celery-beat)    stop_celery_beat; start_celery_beat ;;
      celery)         stop_celery_beat; stop_celery_worker; start_celery_worker; start_celery_beat ;;
      podcast-agent|agent) stop_podcast_agent; start_podcast_agent ;;
      "")             restart_all ;;
      *)              log_error "未知服务: $2"; show_help; exit 1 ;;
    esac
    ;;
  status)
    status
    ;;
  logs)
    logs_menu
    ;;
  logs-all)
    logs
    ;;
  help|--help|-h)
    show_help
    ;;
  *)
    show_help
    exit 1
    ;;
esac
