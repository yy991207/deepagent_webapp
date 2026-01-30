#!/bin/bash
# ==============================================================================
# Agent API 测试脚本
# 
# 用于测试播客生成的完整流程：
# 1. 提交任务 -> 返回 task_id
# 2. 轮询状态 -> 直到终态
# 3. 获取结果
#
# 使用方法:
#   ./scripts/test_agent_api.sh
#
# 前置条件:
#   - 启动 web stack: ./start_web_stack.sh
#   - 设置环境变量: export USE_CELERY=1
# ==============================================================================

set -e

# 配置
BASE_URL="${BASE_URL:-http://localhost:7777}"
AGENT_ID="podcast"
POLL_INTERVAL=3  # 轮询间隔（秒）
MAX_POLLS=60     # 最大轮询次数

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ==============================================================================
# 测试 1: 列出已注册的 Agent
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 1: 列出已注册的 Agent"
echo "=============================================="
log_info "GET ${BASE_URL}/api/agent/registry"

curl -s -X GET "${BASE_URL}/api/agent/registry" \
    -H "Content-Type: application/json" | jq .

echo ""

# ==============================================================================
# 测试 2: 获取指定 Agent 信息
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 2: 获取 podcast Agent 信息"
echo "=============================================="
log_info "GET ${BASE_URL}/api/agent/registry/${AGENT_ID}"

curl -s -X GET "${BASE_URL}/api/agent/registry/${AGENT_ID}" \
    -H "Content-Type: application/json" | jq .

echo ""

# ==============================================================================
# 测试 3: 检查 Agent 健康状态
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 3: 检查 Agent 健康状态"
echo "=============================================="
log_info "GET ${BASE_URL}/api/agent/registry/${AGENT_ID}/health"

curl -s -X GET "${BASE_URL}/api/agent/registry/${AGENT_ID}/health" \
    -H "Content-Type: application/json" | jq .

echo ""

# ==============================================================================
# 测试 4: 提交播客生成任务（新格式）
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 4: 提交播客生成任务（新 API 格式）"
echo "=============================================="
log_info "POST ${BASE_URL}/api/agent/run"

# 新格式请求体
PAYLOAD='{
    "agent_id": "podcast",
    "config": {
        "episode_profile": "tech_discussion",
        "speaker_profile": "diverse_panel",
        "episode_name": "测试播客_'$(date +%Y%m%d_%H%M%S)'",
        "source_ids": [],
        "briefing_suffix": "这是一个测试播客"
    },
    "meta_info": {
        "user_id": "test_user",
        "session_id": "test_session_'$(date +%s)'",
        "request_id": "'$(uuidgen 2>/dev/null || echo "test-request-$(date +%s)")'",
        "client_ip": "127.0.0.1"
    }
}'

log_info "请求体:"
echo "$PAYLOAD" | jq .

RESPONSE=$(curl -s -X POST "${BASE_URL}/api/agent/run" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

echo ""
log_info "响应:"
echo "$RESPONSE" | jq .

# 提取 task_id
TASK_ID=$(echo "$RESPONSE" | jq -r '.task_id // empty')

if [ -z "$TASK_ID" ]; then
    log_error "未获取到 task_id，请检查 Celery 是否启动"
    log_warning "提示: export USE_CELERY=1 然后重启服务"
    exit 1
fi

log_success "任务已提交, task_id: $TASK_ID"

echo ""

# ==============================================================================
# 测试 5: 轮询任务状态
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 5: 轮询任务状态"
echo "=============================================="
log_info "GET ${BASE_URL}/api/agent/task/${TASK_ID}/poll"

poll_count=0
final_status=""

while [ $poll_count -lt $MAX_POLLS ]; do
    poll_count=$((poll_count + 1))
    
    POLL_RESPONSE=$(curl -s -X GET "${BASE_URL}/api/agent/task/${TASK_ID}/poll" \
        -H "Content-Type: application/json")
    
    STATUS=$(echo "$POLL_RESPONSE" | jq -r '.status // "UNKNOWN"')
    MESSAGE=$(echo "$POLL_RESPONSE" | jq -r '.message // ""')
    PROGRESS=$(echo "$POLL_RESPONSE" | jq -r '.progress // 0')
    
    log_info "[${poll_count}/${MAX_POLLS}] 状态: ${STATUS} | 进度: ${PROGRESS}% | ${MESSAGE}"
    
    # 检查终态
    if [ "$STATUS" = "SUCCESS" ]; then
        log_success "任务执行成功!"
        final_status="SUCCESS"
        break
    elif [ "$STATUS" = "FAILURE" ]; then
        log_error "任务执行失败!"
        echo "$POLL_RESPONSE" | jq .
        final_status="FAILURE"
        break
    elif [ "$STATUS" = "CANCELLED" ]; then
        log_warning "任务已取消"
        final_status="CANCELLED"
        break
    fi
    
    # 等待后继续轮询
    sleep $POLL_INTERVAL
done

if [ -z "$final_status" ]; then
    log_warning "轮询超时，任务可能仍在执行中"
fi

echo ""

# ==============================================================================
# 测试 6: 获取任务详细状态
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 6: 获取任务详细状态"
echo "=============================================="
log_info "GET ${BASE_URL}/api/agent/task/${TASK_ID}/status"

curl -s -X GET "${BASE_URL}/api/agent/task/${TASK_ID}/status" \
    -H "Content-Type: application/json" | jq .

echo ""

# ==============================================================================
# 测试 7: 取消任务（示例，注释掉以避免影响正在运行的任务）
# ==============================================================================
echo ""
echo "=============================================="
echo "测试 7: 取消任务（示例命令，已注释）"
echo "=============================================="
log_info "POST ${BASE_URL}/api/agent/cancel"

cat << 'EOF'
# 取消任务命令示例:
curl -X POST "${BASE_URL}/api/agent/cancel" \
    -H "Content-Type: application/json" \
    -d '{
        "task_id": "<TASK_ID>",
        "agent_id": "podcast"
    }'
EOF

echo ""
echo "=============================================="
echo "测试完成"
echo "=============================================="
log_success "所有测试执行完毕"
