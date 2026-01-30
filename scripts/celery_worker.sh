#!/bin/bash
# ==============================================================================
# Celery Worker 启动脚本
# 用途: 启动 Celery Worker 处理异步任务
# ==============================================================================

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 默认配置
WORKER_NAME="${CELERY_WORKER_NAME:-podcast_worker}"
CONCURRENCY="${CELERY_CONCURRENCY:-4}"
LOG_LEVEL="${CELERY_LOG_LEVEL:-info}"
QUEUES="${CELERY_QUEUES:-celery,podcast}"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_DIR="${PROJECT_ROOT}/run"

# 帮助信息
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "启动 Celery Worker 进程"
    echo ""
    echo "Options:"
    echo "  -n, --name NAME       Worker 名称 (默认: ${WORKER_NAME})"
    echo "  -c, --concurrency N   并发进程数 (默认: ${CONCURRENCY})"
    echo "  -l, --log-level LEVEL 日志级别 (默认: ${LOG_LEVEL})"
    echo "  -Q, --queues QUEUES   监听队列，逗号分隔 (默认: ${QUEUES})"
    echo "  -d, --daemon          后台运行"
    echo "  -h, --help            显示帮助信息"
    echo ""
    echo "Environment Variables:"
    echo "  CELERY_BROKER_URL     Redis broker URL"
    echo "  CELERY_RESULT_BACKEND Redis result backend URL"
    echo "  MONGODB_URI           MongoDB 连接字符串"
    echo "  MONGODB_DATABASE      MongoDB 数据库名"
}

# 解析命令行参数
DAEMON_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name)
            WORKER_NAME="$2"
            shift 2
            ;;
        -c|--concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        -l|--log-level)
            LOG_LEVEL="$2"
            shift 2
            ;;
        -Q|--queues)
            QUEUES="$2"
            shift 2
            ;;
        -d|--daemon)
            DAEMON_MODE=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}未知选项: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# 进入项目根目录
cd "$PROJECT_ROOT"

# 创建必要目录
mkdir -p "$LOG_DIR"
mkdir -p "$PID_DIR"

# 检查虚拟环境（优先使用 conda）
CONDA_ENV="${CONDA_ENV:-deepagent}"
if [[ -n "$CONDA_PREFIX" ]]; then
    echo -e "${GREEN}已在 conda 环境中: $CONDA_PREFIX${NC}"
elif [[ -f "/Users/yang/miniconda3/etc/profile.d/conda.sh" ]]; then
    echo -e "${GREEN}激活 conda 环境: ${CONDA_ENV}${NC}"
    source /Users/yang/miniconda3/etc/profile.d/conda.sh
    conda activate "$CONDA_ENV"
elif [[ -d "$PROJECT_ROOT/venv" ]]; then
    echo -e "${GREEN}激活虚拟环境: $PROJECT_ROOT/venv${NC}"
    source "$PROJECT_ROOT/venv/bin/activate"
elif [[ -d "$PROJECT_ROOT/.venv" ]]; then
    echo -e "${GREEN}激活虚拟环境: $PROJECT_ROOT/.venv${NC}"
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# 加载环境变量
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    echo -e "${GREEN}加载环境变量: $PROJECT_ROOT/.env${NC}"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# 检查必要依赖
if ! command -v celery &> /dev/null; then
    echo -e "${RED}错误: celery 命令未找到，请确保已安装 celery${NC}"
    exit 1
fi

# 显示配置
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Celery Worker 配置${NC}"
echo -e "${YELLOW}========================================${NC}"
echo -e "Worker 名称:    ${GREEN}${WORKER_NAME}${NC}"
echo -e "并发进程数:     ${GREEN}${CONCURRENCY}${NC}"
echo -e "日志级别:       ${GREEN}${LOG_LEVEL}${NC}"
echo -e "监听队列:       ${GREEN}${QUEUES}${NC}"
echo -e "后台模式:       ${GREEN}${DAEMON_MODE}${NC}"
echo -e "${YELLOW}========================================${NC}"

# 构建 Celery 命令
CELERY_CMD="celery -A backend.celery_scheduler worker"
CELERY_CMD+=" --hostname=${WORKER_NAME}@%h"
CELERY_CMD+=" --concurrency=${CONCURRENCY}"
CELERY_CMD+=" --loglevel=${LOG_LEVEL}"
CELERY_CMD+=" --queues=${QUEUES}"

if [[ "$DAEMON_MODE" = true ]]; then
    # 后台运行模式
    CELERY_CMD+=" --detach"
    CELERY_CMD+=" --pidfile=${PID_DIR}/celery_worker_${WORKER_NAME}.pid"
    CELERY_CMD+=" --logfile=${LOG_DIR}/celery_worker_${WORKER_NAME}.log"
    
    echo -e "${GREEN}启动 Celery Worker (后台模式)...${NC}"
    echo -e "日志文件: ${LOG_DIR}/celery_worker_${WORKER_NAME}.log"
    echo -e "PID 文件: ${PID_DIR}/celery_worker_${WORKER_NAME}.pid"
else
    echo -e "${GREEN}启动 Celery Worker (前台模式)...${NC}"
fi

# 执行命令
echo -e "${YELLOW}执行: ${CELERY_CMD}${NC}"
exec $CELERY_CMD
