#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
COMPOSE_PATH="$ROOT_DIR/$COMPOSE_FILE"

if [ ! -f "$COMPOSE_PATH" ]; then
  echo "[ERROR] 找不到 docker compose 文件: $COMPOSE_PATH"
  exit 1
fi

COMPOSE_CMD=(docker compose -f "$COMPOSE_PATH")

log_info() {
  echo "[INFO] $1"
}

log_error() {
  echo "[ERROR] $1"
}

ensure_docker_ready() {
  if ! docker info >/dev/null 2>&1; then
    log_error "Docker 当前不可用，请先启动 Docker Desktop。"
    exit 1
  fi
}

resolve_services() {
  local target="${1:-}"

  case "$target" in
    ""|all)
      return 0
      ;;
    backend|frontend|worker|beat|mongo|redis)
      printf '%s\n' "$target"
      ;;
    podcast-agent|agent)
      printf '%s\n' "podcast-agent"
      ;;
    celery)
      printf '%s\n' "worker"
      printf '%s\n' "beat"
      ;;
    *)
      return 1
      ;;
  esac
}

show_help() {
  cat <<'HELP'
用法: ./start_web_stack.sh <命令> [服务名]

命令:
  start [服务]     启动 Docker 服务（不重建镜像）
  rebuild [服务]   重建镜像并启动 Docker 服务
  stop [服务]      停止 Docker 服务
  restart [服务]   重启 Docker 服务
  status           查看服务状态
  logs [服务]      查看日志（tail + follow）
  down             停止并移除容器/网络
  help             查看帮助

可选服务名:
  backend          后端 API
  frontend         前端 Nginx
  worker           Celery Worker
  beat             Celery Beat
  celery           worker + beat
  podcast-agent    播客生成服务
  agent            podcast-agent 别名
  mongo            MongoDB
  redis            Redis

示例:
  ./start_web_stack.sh start
  ./start_web_stack.sh rebuild
  ./start_web_stack.sh start backend
  ./start_web_stack.sh rebuild backend
  ./start_web_stack.sh logs backend
  ./start_web_stack.sh stop celery
  ./start_web_stack.sh down
HELP
}

run_with_optional_services() {
  local action="$1"
  local target="${2:-}"

  local services=()
  local resolved_services=""
  if ! resolved_services="$(resolve_services "$target")"; then
    log_error "未知服务: $target"
    show_help
    exit 1
  fi

  if [ -n "$resolved_services" ]; then
    while IFS= read -r service; do
      if [ -n "$service" ]; then
        services+=("$service")
      fi
    done <<< "$resolved_services"
  fi

  case "$action" in
    start)
      if [ "${#services[@]}" -eq 0 ]; then
        log_info "启动全部 Docker 服务"
        "${COMPOSE_CMD[@]}" up -d
      else
        log_info "启动服务: ${services[*]}"
        "${COMPOSE_CMD[@]}" up -d "${services[@]}"
      fi
      ;;
    rebuild)
      if [ "${#services[@]}" -eq 0 ]; then
        log_info "重建并启动全部 Docker 服务"
        "${COMPOSE_CMD[@]}" up -d --build
      else
        log_info "重建并启动服务: ${services[*]}"
        "${COMPOSE_CMD[@]}" up -d --build "${services[@]}"
        # 关键逻辑：前端 Nginx 对 backend 的 DNS 解析在启动时缓存。
        # backend 被重建后，若 IP 变化，前端需要重启一次避免 502。
        if printf '%s\n' "${services[@]}" | grep -q '^backend$'; then
          log_info "检测到 backend 重建，自动重启 frontend 以刷新 upstream 解析"
          "${COMPOSE_CMD[@]}" restart frontend
        fi
      fi
      ;;
    stop)
      if [ "${#services[@]}" -eq 0 ]; then
        log_info "停止全部 Docker 服务"
        "${COMPOSE_CMD[@]}" stop
      else
        log_info "停止服务: ${services[*]}"
        "${COMPOSE_CMD[@]}" stop "${services[@]}"
      fi
      ;;
    restart)
      if [ "${#services[@]}" -eq 0 ]; then
        log_info "重启全部 Docker 服务"
        "${COMPOSE_CMD[@]}" restart
      else
        log_info "重启服务: ${services[*]}"
        "${COMPOSE_CMD[@]}" restart "${services[@]}"
      fi
      ;;
    logs)
      if [ "${#services[@]}" -eq 0 ]; then
        log_info "查看全部日志（Ctrl+C 退出）"
        "${COMPOSE_CMD[@]}" logs --tail=200 -f
      else
        log_info "查看日志: ${services[*]}（Ctrl+C 退出）"
        "${COMPOSE_CMD[@]}" logs --tail=200 -f "${services[@]}"
      fi
      ;;
    *)
      log_error "不支持的动作: $action"
      exit 1
      ;;
  esac
}

ensure_docker_ready

case "${1:-help}" in
  start)
    run_with_optional_services start "${2:-}"
    ;;
  rebuild)
    run_with_optional_services rebuild "${2:-}"
    ;;
  stop)
    run_with_optional_services stop "${2:-}"
    ;;
  restart)
    run_with_optional_services restart "${2:-}"
    ;;
  logs|logs-all)
    run_with_optional_services logs "${2:-}"
    ;;
  status)
    "${COMPOSE_CMD[@]}" ps
    ;;
  down)
    log_info "停止并移除容器与网络"
    "${COMPOSE_CMD[@]}" down
    ;;
  help|--help|-h)
    show_help
    ;;
  *)
    log_error "未知命令: $1"
    show_help
    exit 1
    ;;
esac
