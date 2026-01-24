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
BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

# 使用 deepagent conda 环境
if [ -x "/Users/yang/miniconda3/envs/deepagent/bin/python" ]; then
  PYTHON_CMD=("/Users/yang/miniconda3/envs/deepagent/bin/python")
elif [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
  PYTHON_CMD=("$CONDA_PREFIX/bin/python")
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

start_backend() {
  if is_running "$BACKEND_PID_FILE"; then
    log_info "后端已在运行"
    return
  fi
  : >"$BACKEND_LOG"
  stop_port_process "$BACKEND_PORT"
  log_info "启动后端服务"
  # 关键逻辑：--reload 会导致进程重启，从而让同一 session 创建多个 OpenSandbox 容器（A 写入、B 读取）。
  # 默认关闭热重载；如需开发热更新，可通过环境变量 BACKEND_RELOAD=1 开启。
  local reload_flag=""
  if [ "${BACKEND_RELOAD:-0}" = "1" ]; then
    reload_flag="--reload"
  fi
  cd "$ROOT_DIR" && "${PYTHON_CMD[@]}" -m uvicorn "$BACKEND_MODULE" --host "$BACKEND_HOST" --port "$BACKEND_PORT" $reload_flag --log-level debug --log-config "$ROOT_DIR/uvicorn_log_config.yaml" \
    >"$BACKEND_LOG" 2>&1 &
  echo $! >"$BACKEND_PID_FILE"
  log_info "后端 PID: $(cat "$BACKEND_PID_FILE")"
}

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

stop_backend() {
  log_info "停止后端服务"
  kill_pid_file "$BACKEND_PID_FILE"
  stop_port_process "$BACKEND_PORT"
}

stop_frontend() {
  log_info "停止前端服务"
  kill_pid_file "$FRONTEND_PID_FILE"
}

status() {
  if is_running "$BACKEND_PID_FILE"; then
    log_info "后端运行中 (PID: $(cat "$BACKEND_PID_FILE"))"
  else
    log_warn "后端未运行"
  fi
  if is_running "$FRONTEND_PID_FILE"; then
    log_info "前端运行中 (PID: $(cat "$FRONTEND_PID_FILE"))"
  else
    log_warn "前端未运行"
  fi
}

logs() {
  log_info "实时日志输出，按 Ctrl+C 退出"
  touch "$BACKEND_LOG" "$FRONTEND_LOG"
  tail -n 200 -f "$BACKEND_LOG" "$FRONTEND_LOG"
}

case "$1" in
  start)
    start_backend
    start_frontend
    ;;
  stop)
    stop_backend
    stop_frontend
    ;;
  restart)
    stop_backend
    stop_frontend
    start_backend
    start_frontend
    ;;
  status)
    status
    ;;
  logs)
    logs
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
