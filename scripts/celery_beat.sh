#!/bin/bash
# ==============================================================================
# Celery Beat 启动脚本
# 用途: 启动 Celery Beat 调度定时任务
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
LOG_LEVEL="${CELERY_LOG_LEVEL:-info}"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_DIR="${PROJECT_ROOT}/run"
SCHEDULE_DIR="${PROJECT_ROOT}/run"

# 帮助信息
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "启动 Celery Beat 定时任务调度器"
    echo ""
    echo "Options:"
    echo "  -l, --log-level LEVEL 日志级别 (默认: ${LOG_LEVEL})"
    echo "  -d, --daemon          后台运行"
    echo "  -h, --help            显示帮助信息"
    echo ""
    echo "Environment Variables:"
    echo "  CELERY_BROKER_URL     Redis broker URL"
    echo "  CELERY_RESULT_BACKEND Redis result backend URL"
}

# 解析命令行参数
DAEMON_MODE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -l|--log-level)
            LOG_LEVEL="$2"
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
mkdir -p "$SCHEDULE_DIR"

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
echo -e "${YELLOW}Celery Beat 配置${NC}"
echo -e "${YELLOW}========================================${NC}"
echo -e "日志级别:       ${GREEN}${LOG_LEVEL}${NC}"
echo -e "后台模式:       ${GREEN}${DAEMON_MODE}${NC}"
echo -e "${YELLOW}========================================${NC}"

# 构建 Celery Beat 命令
CELERY_CMD="celery -A backend.celery_scheduler beat"
CELERY_CMD+=" --loglevel=${LOG_LEVEL}"
CELERY_CMD+=" --schedule=${SCHEDULE_DIR}/celerybeat-schedule"

if [[ "$DAEMON_MODE" = true ]]; then
    # 后台运行模式
    CELERY_CMD+=" --detach"
    CELERY_CMD+=" --pidfile=${PID_DIR}/celery_beat.pid"
    CELERY_CMD+=" --logfile=${LOG_DIR}/celery_beat.log"
    
    echo -e "${GREEN}启动 Celery Beat (后台模式)...${NC}"
    echo -e "日志文件: ${LOG_DIR}/celery_beat.log"
    echo -e "PID 文件: ${PID_DIR}/celery_beat.pid"
    echo -e "调度文件: ${SCHEDULE_DIR}/celerybeat-schedule"
else
    echo -e "${GREEN}启动 Celery Beat (前台模式)...${NC}"
fi

# 执行命令
echo -e "${YELLOW}执行: ${CELERY_CMD}${NC}"
exec $CELERY_CMD
