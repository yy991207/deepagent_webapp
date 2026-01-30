# Celery 调度服务精简版设计文档

## 1. 系统概述

### 1.1 系统定位

Celery 调度服务是一个基于 Celery 的异步任务管理系统，负责：
- 接收前端任务请求
- 将任务投递给 Celery Worker 执行
- 直接操作 MongoDB 进行任务状态持久化
- 提供任务状态查询接口

### 1.2 设计目标

| 目标 | 说明 |
|-----|------|
| **高并发** | 支持万级任务同时在队列中等待/执行 |
| **低延迟** | 任务投递毫秒级完成，不阻塞 |
| **可靠性** | 任务状态可追溯，结果持久化存储 |
| **解耦** | 与主应用解耦，支持独立部署 |
| **精简** | 移除 Java 中间层，Celery 直接操作 MongoDB |

### 1.3 架构精简说明

**原架构（移除）**：
```
前端 → Celery → Java 接口 → MongoDB
```

**精简后架构**：
```
前端 → Celery → MongoDB（直接操作）
```

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                    前端 / 业务系统                               │
│                                                                                 │
│   查询任务状态（快速）──→ Celery Redis    查询任务详情（持久化）──→ MongoDB      │
└───────────────────────────────────┬─────────────────────────────────────────────┘
                                    │ POST /api/podcast/generate
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              FastAPI Gateway                                     │
│                                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────────┐   │
│  │   podcast_      │     │   Celery        │     │   任务状态查询          │   │
│  │   router.py     │────>│   send_task     │     │   GET /api/task/{id}    │   │
│  │                 │     │   （毫秒级投递） │     │   （Redis优先MongoDB兜底）│   │
│  └─────────────────┘     └────────┬────────┘     └─────────────────────────┘   │
│                                   │                                             │
└───────────────────────────────────┼─────────────────────────────────────────────┘
                                    │ 任务入队
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Redis (Broker)                                      │
│                              任务队列 + 结果缓存                                 │
└───────────────────────────────────┬─────────────────────────────────────────────┘
                                    │ Worker 消费
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Celery Worker（可独立部署）                          │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │   podcast_tasks.py                                                       │   │
│  │   ┌───────────────────────────────────────────────────────────────────┐ │   │
│  │   │  @celery_app.task(name='generate_podcast')                        │ │   │
│  │   │  def generate_podcast_task(run_id: str):                          │ │   │
│  │   │      1. 更新状态为 STARTED（MongoDB）                              │ │   │
│  │   │      2. 调用 podcast_middleware._run_generation(run_id)           │ │   │
│  │   │      3. 更新状态为 SUCCESS/FAILURE（MongoDB）                      │ │   │
│  │   └───────────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└───────────────────────────────────┬─────────────────────────────────────────────┘
                                    │ 直接操作
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              MongoDB（持久化存储）                                │
│                                                                                 │
│  Collections:                                                                   │
│  - agent_run_records        # 运行记录                                          │
│  - podcast_generation_results  # 生成结果                                       │
│  - speaker_profile          # 说话人配置                                        │
│  - episode_profile          # 节目配置                                          │
│  - celery_task_meta         # Celery 任务元数据（可选）                          │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心流程

```
时间线 ──────────────────────────────────────────────────────────────────────────>

前端        FastAPI Gateway     Redis Queue      Celery Worker      MongoDB
 │                │                 │                │                │
 │ ─① 提交任务─>  │                 │                │                │
 │                │ ─创建run记录─────────────────────────────────────> │
 │                │                 │                │                │
 │                │ ─② 投递任务──>  │                │                │
 │ <─返回 run_id─ │                 │                │                │
 │                │                 │                │                │
 │   （毫秒级）   │                 │ ─③ Worker消费─> │                │
 │                │                 │                │ ─更新STARTED──> │
 │                │                 │                │                │
 │                │                 │                │ ④ 执行生成     │
 │                │                 │                │   （3-5分钟）   │
 │                │                 │                │                │
 │                │                 │                │ ─更新结果─────> │
 │                │                 │                │                │
 │ ─⑤ 轮询状态─>  │                 │                │                │
 │ <─返回 done─── │ <──查询 Redis/MongoDB────────────────────────────> │
```

### 2.3 前端查询分层

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端查询策略                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【第一层：Redis 快速查询】                                      │
│  ├── 数据源：Celery Result Backend (Redis)                      │
│  ├── 响应时间：毫秒级                                           │
│  ├── 数据有效期：1 小时（可配置）                                │
│  └── 适用场景：轮询任务状态、判断是否完成                        │
│                                                                 │
│  【第二层：MongoDB 持久化查询】                                  │
│  ├── 数据源：MongoDB runs/results 集合                          │
│  ├── 响应时间：10-50ms                                          │
│  ├── 数据有效期：永久                                           │
│  └── 适用场景：                                                 │
│      - Redis 数据过期后的兜底查询                                │
│      - 查询完整的任务详情                                        │
│      - 历史任务查询                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 模块设计

### 3.1 目录结构

```
backend/
├── celery_scheduler/              # 新增 Celery 调度模块
│   ├── __init__.py
│   ├── celery_app.py             # Celery 应用配置
│   ├── config.py                 # 配置管理
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── base_task.py          # 任务基类
│   │   └── podcast_tasks.py      # 播客生成任务
│   └── storage/
│       ├── __init__.py
│       └── task_storage.py       # 任务状态存储
├── middleware/
│   └── podcast_middleware.py     # 现有，保持不变
├── api/
│   └── routers/
│       └── podcast_router.py     # 更新：使用 Celery
scripts/
├── celery_worker.sh              # Worker 启动脚本
├── celery_beat.sh                # Beat 启动脚本（定时任务）
└── supervisor/
    └── celery.conf               # Supervisor 配置
```

### 3.2 核心模块职责

| 模块 | 职责 |
|-----|------|
| `celery_app.py` | Celery 应用实例、Broker/Backend 配置 |
| `config.py` | 环境变量读取、配置项管理 |
| `podcast_tasks.py` | 播客生成 Celery 任务定义 |
| `task_storage.py` | 任务状态 MongoDB CRUD 操作 |
| `podcast_middleware.py` | 播客生成核心逻辑（复用现有） |

---

## 4. 接口规范

### 4.1 接口归属总览

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              接口归属划分                                   │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  【FastAPI Gateway 实现】                                                   │
│  ├── POST /api/podcast/generate     # 提交生成任务                         │
│  ├── POST /api/podcast/runs         # 创建运行记录                         │
│  ├── GET  /api/podcast/runs         # 列出运行记录                         │
│  ├── GET  /api/podcast/runs/{id}    # 查询运行详情                         │
│  ├── DELETE /api/podcast/runs/{id}  # 删除运行记录                         │
│  ├── GET  /api/task/{task_id}       # 查询 Celery 任务状态                 │
│  └── GET  /api/task/result/{task_id}  # 查询 Celery 任务结果               │
│                                                                            │
│  【Celery Worker 执行】                                                     │
│  ├── generate_podcast               # 播客生成任务                         │
│  └── check_timeout_tasks            # 超时检查任务（Beat）                  │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 POST /api/podcast/generate - 提交生成任务

**请求**：
```http
POST /api/podcast/generate
Content-Type: application/json

{
    "episode_profile": "default",
    "speaker_profile": "two_hosts",
    "episode_name": "科技周报第10期",
    "source_ids": ["507f1f77bcf86cd799439011", "507f1f77bcf86cd799439012"],
    "briefing_suffix": "请重点关注AI领域的最新进展"
}
```

**响应**：
```json
{
    "run_id": "podcast-abc123def456",
    "task_id": "celery-task-uuid-here",
    "status": "queued",
    "created_at": "2024-01-01T10:00:00Z"
}
```

### 4.3 GET /api/task/{task_id} - 查询任务状态

**查询策略**：Redis 优先，MongoDB 兜底

**请求**：
```http
GET /api/task/{task_id}
```

**响应**：
```json
{
    "code": 0,
    "message": "success",
    "data": {
        "task_id": "celery-task-uuid-here",
        "status": "SUCCESS",
        "ready": true,
        "source": "redis"
    }
}
```

---

## 5. 数据模型

### 5.1 任务状态流转

```
                    ┌──────────────────────────────────────┐
                    │                                      │
                    ▼                                      │
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐  │
│ PENDING │───>│ STARTED │───>│ SUCCESS │    │ REVOKED │<─┘
└─────────┘    └─────────┘    └─────────┘    └─────────┘
                    │                             ▲
                    │         ┌─────────┐         │
                    └────────>│ FAILURE │─────────┘
                              └─────────┘
```

| 状态 | 说明 | 触发时机 |
|-----|------|---------|
| PENDING | 等待执行 | 任务入队（Celery 默认） |
| STARTED | 执行中 | Worker 开始执行 |
| SUCCESS | 成功 | 生成完成 |
| FAILURE | 失败 | 执行异常 |
| REVOKED | 已取消 | 用户主动取消 |

### 5.2 MongoDB 任务记录（runs 集合）

```javascript
{
    "_id": ObjectId("..."),
    "run_id": "podcast-abc123def456",
    "celery_task_id": "celery-task-uuid-here",  // 新增：关联 Celery 任务
    "status": "running",
    "episode_profile": "default",
    "speaker_profile": "two_hosts",
    "episode_name": "科技周报第10期",
    "source_ids": ["507f1f77bcf86cd799439011"],
    "briefing_suffix": "请重点关注AI领域",
    "message": null,  // 错误信息
    "created_at": ISODate("2024-01-01T10:00:00Z"),
    "updated_at": ISODate("2024-01-01T10:05:00Z")
}
```

### 5.3 MongoDB 生成结果（results 集合）

```javascript
{
    "_id": ObjectId("..."),
    "run_id": "podcast-abc123def456",
    "episode_profile": "default",
    "speaker_profile": "two_hosts",
    "episode_name": "科技周报第10期",
    "audio_file_path": "/data/podcasts/podcast-abc123def456/output.mp3",
    "transcript": [...],  // 转录文本
    "outline": {...},     // 大纲
    "processing_time": 180.5,  // 处理时间（秒）
    "created_at": ISODate("2024-01-01T10:05:00Z")
}
```

---

## 6. 生产环境配置

### 6.1 环境变量

```bash
# Redis 配置
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# MongoDB 配置
MONGODB_URI=mongodb://localhost:27017
DEEPAGENTS_MONGO_DB=deepagents_web

# Celery Worker 配置
CELERY_WORKER_CONCURRENCY=4
CELERY_TASK_TIME_LIMIT=1800      # 单任务最大执行时间（秒）
CELERY_TASK_SOFT_TIME_LIMIT=1500
CELERY_RESULT_EXPIRES=3600       # 结果过期时间（秒）

# 应用配置
DEEPAGENTS_DATA_DIR=/data/deepagents
```

### 6.2 config.yaml 示例

```yaml
# Celery 调度服务配置
celery:
  broker_url: "${CELERY_BROKER_URL:-redis://localhost:6379/0}"
  result_backend: "${CELERY_RESULT_BACKEND:-redis://localhost:6379/1}"
  
  # Worker 配置
  worker:
    concurrency: 4
    prefetch_multiplier: 1
    max_tasks_per_child: 100
  
  # 任务配置
  task:
    time_limit: 1800
    soft_time_limit: 1500
    acks_late: true
    reject_on_worker_lost: true
  
  # 结果配置
  result:
    expires: 3600
    extended: true

# MongoDB 配置
mongodb:
  uri: "${MONGODB_URI:-mongodb://localhost:27017}"
  database: "${DEEPAGENTS_MONGO_DB:-deepagents_web}"
  
  # 集合名称
  collections:
    runs: "agent_run_records"
    results: "podcast_generation_results"
    speaker_profiles: "speaker_profile"
    episode_profiles: "episode_profile"

# 任务超时检查
timeout:
  check_interval_minutes: 5
  task_timeout_minutes: 30
```

---

## 7. 独立部署方案

### 7.1 部署架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      生产环境部署架构                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  节点 1: Web Server                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  FastAPI Application (Gunicorn/Uvicorn)                 │   │
│  │  - podcast_router.py                                    │   │
│  │  - 其他路由                                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  节点 2-N: Celery Workers（可水平扩展）                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Celery Worker x N                                      │   │
│  │  - generate_podcast task                                │   │
│  │  - 独立进程，通过 Redis 接收任务                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  节点 N+1: Celery Beat（单实例）                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Celery Beat                                            │   │
│  │  - check_timeout_tasks（定时任务）                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  共享服务:                                                       │
│  ┌─────────────┐  ┌─────────────┐                              │
│  │   Redis     │  │  MongoDB    │                              │
│  │  (Broker)   │  │ (Storage)   │                              │
│  └─────────────┘  └─────────────┘                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Worker 启动脚本

```bash
#!/bin/bash
# scripts/celery_worker.sh
# Celery Worker 启动脚本

set -e

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 激活虚拟环境（如果存在）
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 加载环境变量
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# 默认配置
CONCURRENCY=${CELERY_WORKER_CONCURRENCY:-4}
LOG_LEVEL=${CELERY_LOG_LEVEL:-info}
QUEUE_NAME=${CELERY_QUEUE_NAME:-celery}

# 启动 Worker
exec celery -A backend.celery_scheduler.celery_app worker \
    --loglevel="$LOG_LEVEL" \
    --concurrency="$CONCURRENCY" \
    --queues="$QUEUE_NAME" \
    --hostname="worker@%h" \
    --prefetch-multiplier=1
```

### 7.3 Beat 启动脚本

```bash
#!/bin/bash
# scripts/celery_beat.sh
# Celery Beat 启动脚本（定时任务调度器）

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 激活虚拟环境
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 加载环境变量
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

LOG_LEVEL=${CELERY_LOG_LEVEL:-info}

# 启动 Beat
exec celery -A backend.celery_scheduler.celery_app beat \
    --loglevel="$LOG_LEVEL" \
    --scheduler=celery.beat:PersistentScheduler
```

### 7.4 Supervisor 配置

```ini
; scripts/supervisor/celery.conf
; Supervisor 配置文件

[group:celery]
programs=celery_worker,celery_beat

[program:celery_worker]
command=/path/to/project/scripts/celery_worker.sh
directory=/path/to/project
user=www-data
numprocs=1
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=600
killasgroup=true
priority=998

; 日志配置
stdout_logfile=/var/log/celery/worker.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
stderr_logfile=/var/log/celery/worker_error.log
stderr_logfile_maxbytes=50MB
stderr_logfile_backups=10

; 环境变量
environment=
    PYTHONPATH="/path/to/project",
    CELERY_WORKER_CONCURRENCY="4"

[program:celery_beat]
command=/path/to/project/scripts/celery_beat.sh
directory=/path/to/project
user=www-data
numprocs=1
autostart=true
autorestart=true
startsecs=10
stopwaitsecs=30
killasgroup=true
priority=999

stdout_logfile=/var/log/celery/beat.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=5
stderr_logfile=/var/log/celery/beat_error.log
stderr_logfile_maxbytes=10MB
stderr_logfile_backups=5

environment=
    PYTHONPATH="/path/to/project"
```

### 7.5 Systemd 配置（可选）

```ini
# /etc/systemd/system/celery-worker.service
[Unit]
Description=Celery Worker Service
After=network.target redis.service mongodb.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/path/to/project
ExecStart=/path/to/project/scripts/celery_worker.sh
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=celery-worker

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/celery-beat.service
[Unit]
Description=Celery Beat Service
After=network.target redis.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/path/to/project
ExecStart=/path/to/project/scripts/celery_beat.sh
Restart=always
RestartSec=10
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=celery-beat

[Install]
WantedBy=multi-user.target
```

---

## 8. 关键设计原则

### 8.1 先返回后落库

```
严禁写法:
┌─────────────────────────────────────────────────────────────────┐
│  await db.insert(task)        # 先写库                          │
│  task = await db.find(id)     # 再查库                          │
│  return task                  # 返回查到的数据                   │
│                               ↑ 多端点部署时可能查不到！         │
└─────────────────────────────────────────────────────────────────┘

正确做法:
┌─────────────────────────────────────────────────────────────────┐
│  run_id = generate_run_id()                                      │
│  db.insert({"run_id": run_id, "status": "queued"})              │
│  celery_app.send_task("generate_podcast", args=[run_id])        │
│  return {"run_id": run_id, "status": "queued"}  # 返回业务结果   │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 异步资源与事件循环绑定

```python
# 严禁写法：在模块级别创建异步客户端
http_client = httpx.AsyncClient()  # 模块级别创建

@celery_app.task
def task():
    asyncio.run(http_client.post(...))  # 跨线程使用 → RuntimeError!

# 正确做法：每次任务创建新的客户端
@celery_app.task
def task():
    asyncio.run(_async_work())

async def _async_work():
    async with httpx.AsyncClient() as client:  # 谁创建谁使用
        await client.post(...)
```

### 8.3 幂等性设计

```
终态定义：SUCCESS / FAILURE / REVOKED

幂等规则：
┌─────────────────────────────────────────────────────────────────┐
│  收到更新请求 → 查询当前状态 → 是否终态？                        │
│                                                                 │
│  ├── 当前 SUCCESS → 忽略，不更新                                │
│  ├── 当前 FAILURE → 忽略，不更新                                │
│  ├── 当前 REVOKED → 忽略，不更新                                │
│  └── 当前 STARTED → 正常处理，更新状态                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. 监控与运维

### 9.1 关键指标

| 指标 | 说明 | 告警阈值 |
|-----|------|---------|
| 队列积压数 | Redis 队列长度 | > 100 |
| Worker 存活数 | 活跃 Worker 数量 | < 预期数量 |
| 任务成功率 | 成功任务 / 总任务 | < 95% |
| 平均处理时间 | 任务执行耗时 | > 10 分钟 |
| STARTED 超时数 | 停留超过 30 分钟 | > 10 |

### 9.2 Flower 监控

```bash
# 启动 Flower（Celery 监控面板）
celery -A backend.celery_scheduler.celery_app flower \
    --port=5555 \
    --basic_auth=admin:password

# 访问
http://localhost:5555
```

### 9.3 健康检查接口

```python
@router.get("/api/celery/health")
def celery_health_check():
    """Celery 健康检查"""
    from backend.celery_scheduler.celery_app import celery_app
    
    try:
        # 检查 Broker 连接
        celery_app.control.ping(timeout=5)
        
        # 获取活跃 Worker 信息
        inspect = celery_app.control.inspect()
        active = inspect.active()
        
        return {
            "status": "healthy",
            "workers": list(active.keys()) if active else [],
            "broker": "connected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
```

---

## 10. 实现文件清单

### 10.1 新增文件

| 文件路径 | 说明 |
|---------|------|
| `backend/celery_scheduler/__init__.py` | 模块初始化 |
| `backend/celery_scheduler/celery_app.py` | Celery 应用配置 |
| `backend/celery_scheduler/config.py` | 配置管理 |
| `backend/celery_scheduler/tasks/__init__.py` | 任务模块初始化 |
| `backend/celery_scheduler/tasks/base_task.py` | 任务基类 |
| `backend/celery_scheduler/tasks/podcast_tasks.py` | 播客生成任务 |
| `backend/celery_scheduler/storage/__init__.py` | 存储模块初始化 |
| `backend/celery_scheduler/storage/task_storage.py` | 任务状态存储 |
| `scripts/celery_worker.sh` | Worker 启动脚本 |
| `scripts/celery_beat.sh` | Beat 启动脚本 |
| `scripts/supervisor/celery.conf` | Supervisor 配置 |

### 10.2 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `backend/api/routers/podcast_router.py` | 新增 Celery 任务提交逻辑 |
| `backend/middleware/podcast_middleware.py` | 新增 Celery 集成方法（可选） |
| `requirements.txt` | 添加 celery、redis 依赖 |

---

## 11. 开发检查清单

### 11.1 核心功能

- [ ] `celery_app.py` 配置完成，Broker/Backend 连接正常
- [ ] `podcast_tasks.py` 任务定义完成，可正常执行
- [ ] `task_storage.py` MongoDB 操作完成，状态更新正确
- [ ] `podcast_router.py` 更新完成，使用 Celery 提交任务
- [ ] Worker 启动脚本测试通过
- [ ] Supervisor/Systemd 配置测试通过

### 11.2 测试验证

- [ ] 单元测试：任务创建、状态更新
- [ ] 集成测试：端到端流程
- [ ] 压力测试：并发任务提交
- [ ] 故障测试：Worker 重启、Redis 断连

---

## 12. 版本记录

| 版本 | 日期 | 修改内容 |
|-----|------|---------|
| v1.0 | 2024-01-30 | 初始版本：精简架构设计，移除 Java 层 |
