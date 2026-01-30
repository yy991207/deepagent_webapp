# Celery 调度模块

用于播客生成任务的分布式调度系统，基于 Celery + Redis + MongoDB 实现。

## 架构概述

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   FastAPI   │────▶│   Celery    │────▶│   MongoDB   │
│   Gateway   │     │   Worker    │     │  (存储层)   │
└─────────────┘     └─────────────┘     └─────────────┘
                          │
                          ▼
                    ┌─────────────┐
                    │    Redis    │
                    │  (Broker)   │
                    └─────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install celery[redis] redis pymongo
```

### 2. 配置环境变量

```bash
# Redis 配置
export CELERY_BROKER_URL="redis://localhost:6379/0"
export CELERY_RESULT_BACKEND="redis://localhost:6379/1"

# MongoDB 配置
export MONGODB_URI="mongodb://localhost:27017"
export MONGODB_DATABASE="podcast_db"

# 启用 Celery 模式（在 FastAPI 中）
export USE_CELERY=1
```

或在 `.env` 文件中配置。

### 3. 启动服务

推荐使用统一的启动脚本 `start_web_stack.sh`：

```bash
# 启动全部服务（后端 + 前端 + Celery）
./start_web_stack.sh start

# 只启动 Celery 服务
./start_web_stack.sh start celery

# 只启动 Celery Worker
./start_web_stack.sh start celery-worker

# 只启动 Celery Beat
./start_web_stack.sh start celery-beat

# 查看服务状态
./start_web_stack.sh status

# 查看日志（交互式菜单）
./start_web_stack.sh logs

# 停止全部服务
./start_web_stack.sh stop

# 重启 Celery 服务
./start_web_stack.sh restart celery
```

### 4. 生产环境部署

#### 使用 Supervisor

```bash
# 复制配置文件
sudo cp scripts/supervisor/celery.conf /etc/supervisor/conf.d/

# 编辑配置，修改路径
sudo vim /etc/supervisor/conf.d/celery.conf

# 重新加载配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动服务
sudo supervisorctl start celery:*
```

#### 使用 Systemd

```bash
# 复制服务文件
sudo cp scripts/systemd/celery-*.service /etc/systemd/system/

# 编辑配置，修改路径
sudo vim /etc/systemd/system/celery-worker.service
sudo vim /etc/systemd/system/celery-beat.service

# 重新加载并启动
sudo systemctl daemon-reload
sudo systemctl enable celery-worker celery-beat
sudo systemctl start celery-worker celery-beat
```

## 模块结构

```
backend/celery_scheduler/
├── __init__.py           # 模块入口，导出 celery_app
├── config.py             # 配置管理（环境变量读取）
├── celery_app.py         # Celery 应用配置
├── README.md             # 本文档
├── storage/
│   ├── __init__.py
│   └── task_storage.py   # MongoDB 任务存储（CRUD + 幂等保证）
└── tasks/
    ├── __init__.py
    └── podcast_tasks.py  # Celery 任务定义
```

## API 接口

### 生成播客

```bash
POST /api/podcast/generate
Content-Type: application/json

{
    "episode_profile": "tech_news",
    "speaker_profile": "dual_host",
    "episode_name": "科技周报",
    "source_ids": ["doc_id_1", "doc_id_2"]
}
```

响应（Celery 模式）：
```json
{
    "run_id": "run_abc123",
    "status": "pending",
    "created_at": "2024-01-30T12:00:00",
    "celery_task_id": "celery_task_xyz",
    "mode": "celery"
}
```

响应（线程模式）：
```json
{
    "run_id": "run_abc123",
    "status": "pending",
    "created_at": "2024-01-30T12:00:00",
    "mode": "thread"
}
```

### 查询 Celery 任务状态

```bash
GET /api/podcast/celery/task/{celery_task_id}
```

响应：
```json
{
    "celery_task_id": "celery_task_xyz",
    "status": "SUCCESS",
    "ready": true,
    "successful": true,
    "result": {
        "run_id": "run_abc123",
        "status": "done"
    }
}
```

### 启动已创建的任务

```bash
POST /api/podcast/runs/{run_id}/start
```

## 任务状态流转

```
PENDING ──▶ STARTED ──▶ SUCCESS
                   └──▶ FAILURE
                   └──▶ REVOKED (被取消)
```

### 幂等性保证

- 终态（SUCCESS/FAILURE/REVOKED）不可被覆盖
- 使用 MongoDB 原子操作确保状态更新的一致性
- 支持任务重试（非终态任务可重新执行）

## 定时任务

Celery Beat 配置了以下定时任务：

| 任务 | 周期 | 说明 |
|------|------|------|
| check-timeout-tasks | 每 5 分钟 | 检查超时任务，标记为 FAILURE |

默认任务超时时间为 30 分钟，可通过环境变量 `CELERY_TASK_SOFT_TIME_LIMIT` 配置。

## 监控

### 查看 Worker 状态

```bash
celery -A backend.celery_scheduler inspect active
celery -A backend.celery_scheduler inspect stats
```

### 查看队列长度

```bash
celery -A backend.celery_scheduler inspect reserved
```

### 使用 Flower（Web 监控）

```bash
pip install flower
celery -A backend.celery_scheduler flower --port=5555
```

访问 http://localhost:5555 查看监控面板。

## 故障排查

### Worker 无法启动

1. 检查 Redis 连接：`redis-cli ping`
2. 检查环境变量是否正确配置
3. 查看日志：`./start_web_stack.sh logs` 选择 3

### 任务一直处于 PENDING

1. 确认 Worker 正在运行：`./start_web_stack.sh status`
2. 检查队列是否正确：任务应该在 `celery` 或 `podcast` 队列
3. 查看 Worker 日志是否有错误

### 任务超时

1. 检查 `CELERY_TASK_SOFT_TIME_LIMIT` 配置
2. 对于长时间任务，考虑增加超时时间
3. 检查任务执行逻辑是否有阻塞

## 配置参考

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| CELERY_BROKER_URL | redis://localhost:6379/0 | Redis broker URL |
| CELERY_RESULT_BACKEND | redis://localhost:6379/1 | Redis result backend URL |
| MONGODB_URI | mongodb://localhost:27017 | MongoDB 连接字符串 |
| MONGODB_DATABASE | podcast_db | MongoDB 数据库名 |
| CELERY_TASK_SOFT_TIME_LIMIT | 1800 | 任务软超时（秒） |
| CELERY_TASK_TIME_LIMIT | 3600 | 任务硬超时（秒） |
| CELERY_CONCURRENCY | 4 | Worker 并发数 |
| USE_CELERY | 0 | 启用 Celery 模式 |
