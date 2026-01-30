# Celery 调度服务实现代码

本文档包含 Celery 调度服务的完整实现代码，用于指导开发人员进行实际编码。

## 1. 目录结构

```
backend/
├── celery_scheduler/              # Celery 调度模块
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
scripts/
├── celery_worker.sh              # Worker 启动脚本
├── celery_beat.sh                # Beat 启动脚本
└── supervisor/
    └── celery.conf               # Supervisor 配置
```

---

## 2. 核心模块实现

### 2.1 backend/celery_scheduler/__init__.py

```python
"""
Celery 调度服务模块

职责：提供基于 Celery 的异步任务调度能力
设计原因：
1. 与主应用解耦，支持独立部署
2. 直接操作 MongoDB，移除 Java 中间层
3. 复用现有 podcast_middleware 的业务逻辑
"""

from backend.celery_scheduler.celery_app import celery_app

__all__ = ["celery_app"]
```

### 2.2 backend/celery_scheduler/config.py

```python
"""
配置管理模块

处理方式：同步加载，启动时一次性读取
设计原因：配置在服务启动时加载一次即可，无需异步
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class CelerySchedulerConfig:
    """
    Celery 调度服务配置类
    
    职责：
    1. 从环境变量读取配置
    2. 提供配置项的便捷访问方法
    3. 支持默认值回退
    """
    
    # ==================== Redis 配置 ====================
    
    @property
    def redis_host(self) -> str:
        return os.getenv("REDIS_HOST", "localhost")
    
    @property
    def redis_port(self) -> int:
        return int(os.getenv("REDIS_PORT", "6379"))
    
    @property
    def redis_password(self) -> str:
        return os.getenv("REDIS_PASSWORD", "")
    
    @property
    def redis_db_broker(self) -> int:
        return int(os.getenv("CELERY_BROKER_DB", "0"))
    
    @property
    def redis_db_backend(self) -> int:
        return int(os.getenv("CELERY_BACKEND_DB", "1"))
    
    @property
    def broker_url(self) -> str:
        """Celery Broker URL"""
        # 优先使用完整 URL 环境变量
        full_url = os.getenv("CELERY_BROKER_URL")
        if full_url:
            return full_url
        # 否则拼接
        pwd = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{pwd}{self.redis_host}:{self.redis_port}/{self.redis_db_broker}"
    
    @property
    def result_backend_url(self) -> str:
        """Celery Result Backend URL"""
        full_url = os.getenv("CELERY_RESULT_BACKEND")
        if full_url:
            return full_url
        pwd = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{pwd}{self.redis_host}:{self.redis_port}/{self.redis_db_backend}"
    
    # ==================== Celery Worker 配置 ====================
    
    @property
    def task_time_limit(self) -> int:
        """任务硬超时（秒）"""
        return int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800"))
    
    @property
    def task_soft_time_limit(self) -> int:
        """任务软超时（秒）"""
        return int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "1500"))
    
    @property
    def worker_concurrency(self) -> int:
        """Worker 并发数"""
        return int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))
    
    @property
    def worker_prefetch_multiplier(self) -> int:
        """Worker 预取数"""
        return int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
    
    @property
    def result_expires(self) -> int:
        """结果过期时间（秒）"""
        return int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))
    
    @property
    def timezone(self) -> str:
        """时区"""
        return os.getenv("CELERY_TIMEZONE", "Asia/Shanghai")
    
    # ==================== MongoDB 配置 ====================
    
    @property
    def mongo_url(self) -> str:
        return os.getenv("MONGODB_URI") or os.getenv("DEEPAGENTS_MONGO_URL") or "mongodb://127.0.0.1:27017"
    
    @property
    def mongo_db_name(self) -> str:
        return os.getenv("DEEPAGENTS_MONGO_DB", "deepagents_web")
    
    # ==================== 数据目录配置 ====================
    
    @property
    def data_dir(self) -> str:
        return os.getenv("DEEPAGENTS_DATA_DIR") or str(Path(__file__).resolve().parents[2] / "data")


# 全局配置实例（单例模式）
celery_config = CelerySchedulerConfig()
```

### 2.3 backend/celery_scheduler/celery_app.py

```python
"""
Celery 应用配置模块

处理方式：同步初始化
设计原因：Celery 应用在模块加载时初始化，Worker 和 API 共用同一个实例
"""
from celery import Celery

from backend.celery_scheduler.config import celery_config


def create_celery_app() -> Celery:
    """
    创建并配置 Celery 应用
    
    关键配置说明：
    1. broker: 使用 Redis 作为消息队列
    2. backend: 使用 Redis 存储任务结果
    3. task_time_limit: 任务执行的超时时间
    """
    app = Celery(
        "celery_scheduler",
        broker=celery_config.broker_url,
        backend=celery_config.result_backend_url,
        # 指定任务模块，Celery 会自动发现这些模块中的任务
        include=["backend.celery_scheduler.tasks.podcast_tasks"]
    )
    
    # Celery 配置
    app.conf.update(
        # 任务超时设置（单位：秒）
        task_time_limit=celery_config.task_time_limit,
        task_soft_time_limit=celery_config.task_soft_time_limit,
        
        # Worker 预取设置
        # 设为 1 表示每次只取一个任务，避免任务堆积在单个 Worker
        worker_prefetch_multiplier=celery_config.worker_prefetch_multiplier,
        
        # 结果过期时间（单位：秒）
        result_expires=celery_config.result_expires,
        
        # 时区设置
        timezone=celery_config.timezone,
        enable_utc=True,
        
        # 序列化设置
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        
        # 任务确认设置
        # 任务成功完成后才确认，失败则重新入队
        task_acks_late=True,
        
        # 任务跟踪设置
        task_track_started=True,
        
        # 结果扩展设置
        result_extended=True,
        
        # Beat 定时任务配置
        beat_schedule={
            "check-timeout-tasks": {
                "task": "check_timeout_tasks",
                "schedule": 300.0,  # 每 5 分钟执行一次
            },
        },
    )
    
    return app


# 全局 Celery 应用实例
celery_app = create_celery_app()
```

### 2.4 backend/celery_scheduler/storage/__init__.py

```python
"""
存储模块

职责：提供任务状态的 MongoDB 存储操作
"""

from backend.celery_scheduler.storage.task_storage import TaskStorage

__all__ = ["TaskStorage"]
```

### 2.5 backend/celery_scheduler/storage/task_storage.py

```python
"""
任务状态存储模块

职责：直接操作 MongoDB 进行任务状态的 CRUD
设计原因：
1. 精简架构，移除 Java 中间层
2. 复用现有 MongoDB 连接配置
3. 提供幂等性保证
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from pymongo import MongoClient

from backend.celery_scheduler.config import celery_config


# 终态定义
TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED"}


def is_terminal_state(status: str) -> bool:
    """判断是否为终态"""
    return status in TERMINAL_STATES


class TaskStorage:
    """
    任务状态存储类
    
    职责：
    1. 创建任务记录
    2. 更新任务状态
    3. 查询任务状态和详情
    4. 幂等性保证（终态不可覆盖）
    
    设计原因：直接操作 MongoDB，移除 Java 中间层
    """
    
    def __init__(self) -> None:
        self._client: MongoClient | None = None
        self._mongo_url = celery_config.mongo_url
        self._db_name = celery_config.mongo_db_name
    
    def _get_client(self) -> MongoClient:
        """获取 MongoDB 客户端（懒加载）"""
        if self._client is None:
            self._client = MongoClient(self._mongo_url)
        return self._client
    
    def _runs_collection(self):
        """获取 runs 集合"""
        return self._get_client()[self._db_name]["agent_run_records"]
    
    def _results_collection(self):
        """获取 results 集合"""
        return self._get_client()[self._db_name]["podcast_generation_results"]
    
    def _now(self) -> datetime:
        """获取当前 UTC 时间"""
        return datetime.now(timezone.utc)
    
    def close(self) -> None:
        """关闭 MongoDB 连接"""
        if self._client is not None:
            self._client.close()
            self._client = None
    
    # ==================== 任务记录操作 ====================
    
    def create_task(
        self,
        *,
        run_id: str,
        celery_task_id: str,
        episode_profile: str,
        speaker_profile: str,
        episode_name: str,
        source_ids: list[str],
        briefing_suffix: str | None = None,
    ) -> dict[str, Any]:
        """
        创建任务记录
        
        处理方式：幂等插入，已存在则不覆盖
        设计原因：防止重复提交导致数据覆盖
        
        Args:
            run_id: 运行 ID
            celery_task_id: Celery 任务 ID
            episode_profile: 节目配置名称
            speaker_profile: 说话人配置名称
            episode_name: 节目名称
            source_ids: 源文件 ID 列表
            briefing_suffix: 附加说明
            
        Returns:
            创建结果，包含 run_id 和 created 标志
        """
        now = self._now()
        doc = {
            "run_id": run_id,
            "celery_task_id": celery_task_id,
            "status": "queued",
            "episode_profile": episode_profile,
            "speaker_profile": speaker_profile,
            "episode_name": episode_name,
            "source_ids": source_ids,
            "briefing_suffix": briefing_suffix,
            "message": None,
            "created_at": now,
            "updated_at": now,
        }
        
        # 幂等插入：使用 upsert，$setOnInsert 只在插入时设置
        result = self._runs_collection().update_one(
            {"run_id": run_id},
            {"$setOnInsert": doc},
            upsert=True
        )
        
        return {
            "run_id": run_id,
            "created": result.upserted_id is not None
        }
    
    def update_task_status(
        self,
        *,
        run_id: str,
        status: str,
        message: str | None = None,
    ) -> dict[str, Any]:
        """
        更新任务状态
        
        处理方式：原子更新，终态不可覆盖
        设计原因：保证幂等性，防止状态回退
        
        Args:
            run_id: 运行 ID
            status: 新状态
            message: 状态消息或错误信息
            
        Returns:
            更新结果，包含 updated 标志和 reason
        """
        now = self._now()
        
        # 原子更新：只更新非终态的记录
        # 使用 $nin 确保当前状态不在终态列表中
        result = self._runs_collection().update_one(
            {
                "run_id": run_id,
                "status": {"$nin": list(TERMINAL_STATES)}
            },
            {
                "$set": {
                    "status": status,
                    "message": message,
                    "updated_at": now,
                }
            }
        )
        
        if result.matched_count == 0:
            # 可能是：1) run_id 不存在  2) 已终态
            existing = self._runs_collection().find_one({"run_id": run_id})
            if existing and is_terminal_state(existing.get("status", "")):
                return {
                    "run_id": run_id,
                    "updated": False,
                    "reason": "already_terminal"
                }
            return {
                "run_id": run_id,
                "updated": False,
                "reason": "not_found"
            }
        
        return {
            "run_id": run_id,
            "updated": True
        }
    
    def get_task_status(self, *, run_id: str) -> dict[str, Any] | None:
        """
        获取任务状态
        
        Args:
            run_id: 运行 ID
            
        Returns:
            任务状态信息，不存在返回 None
        """
        doc = self._runs_collection().find_one(
            {"run_id": run_id},
            projection={"_id": 0, "run_id": 1, "status": 1, "celery_task_id": 1}
        )
        if not doc:
            return None
        return {
            "run_id": doc.get("run_id"),
            "status": doc.get("status"),
            "celery_task_id": doc.get("celery_task_id"),
            "exists": True
        }
    
    def get_task_detail(self, *, run_id: str) -> dict[str, Any] | None:
        """
        获取任务详情
        
        Args:
            run_id: 运行 ID
            
        Returns:
            完整任务信息，不存在返回 None
        """
        doc = self._runs_collection().find_one(
            {"run_id": run_id},
            projection={"_id": 0}
        )
        if not doc:
            return None
        
        # 转换时间字段为 ISO 格式
        for field in ["created_at", "updated_at"]:
            if field in doc and hasattr(doc[field], "isoformat"):
                doc[field] = doc[field].isoformat()
        
        doc["exists"] = True
        return doc
    
    # ==================== 结果记录操作 ====================
    
    def save_result(
        self,
        *,
        run_id: str,
        episode_profile: str,
        speaker_profile: str,
        episode_name: str,
        audio_file_path: str | None,
        transcript: Any,
        outline: Any,
        processing_time: float,
    ) -> dict[str, Any]:
        """
        保存生成结果
        
        处理方式：upsert，允许更新已有结果
        设计原因：重试生成时可以覆盖之前的结果
        
        Args:
            run_id: 运行 ID
            其他参数: 生成结果数据
            
        Returns:
            保存结果
        """
        now = self._now()
        doc = {
            "run_id": run_id,
            "episode_profile": episode_profile,
            "speaker_profile": speaker_profile,
            "episode_name": episode_name,
            "audio_file_path": audio_file_path,
            "transcript": transcript,
            "outline": outline,
            "processing_time": processing_time,
            "created_at": now,
        }
        
        self._results_collection().update_one(
            {"run_id": run_id},
            {"$set": doc},
            upsert=True
        )
        
        return {"run_id": run_id, "saved": True}
    
    def get_result(self, *, run_id: str) -> dict[str, Any] | None:
        """
        获取生成结果
        
        Args:
            run_id: 运行 ID
            
        Returns:
            生成结果数据，不存在返回 None
        """
        doc = self._results_collection().find_one(
            {"run_id": run_id},
            projection={"_id": 0}
        )
        if not doc:
            return None
        
        # 转换时间字段
        if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
            doc["created_at"] = doc["created_at"].isoformat()
        
        return doc
    
    # ==================== 超时检查 ====================
    
    def find_timeout_tasks(self, *, timeout_minutes: int = 30) -> list[str]:
        """
        查找超时任务
        
        处理方式：查找 STARTED 状态超过指定时间的任务
        设计原因：定时任务检查，标记超时任务为 FAILURE
        
        Args:
            timeout_minutes: 超时时间（分钟）
            
        Returns:
            超时任务的 run_id 列表
        """
        threshold = self._now() - timedelta(minutes=timeout_minutes)
        
        cursor = self._runs_collection().find(
            {
                "status": "running",
                "updated_at": {"$lt": threshold}
            },
            projection={"run_id": 1}
        )
        
        return [doc["run_id"] for doc in cursor]
    
    def mark_timeout_tasks(self, *, run_ids: list[str]) -> int:
        """
        批量标记超时任务
        
        Args:
            run_ids: 要标记的 run_id 列表
            
        Returns:
            实际更新的数量
        """
        if not run_ids:
            return 0
        
        now = self._now()
        result = self._runs_collection().update_many(
            {
                "run_id": {"$in": run_ids},
                "status": {"$nin": list(TERMINAL_STATES)}
            },
            {
                "$set": {
                    "status": "error",
                    "message": "执行超时，已超过最大时限",
                    "updated_at": now,
                }
            }
        )
        
        return result.modified_count
```

### 2.6 backend/celery_scheduler/tasks/__init__.py

```python
"""
任务模块

职责：定义 Celery Worker 执行的任务
"""

from backend.celery_scheduler.tasks.podcast_tasks import (
    generate_podcast_task,
    check_timeout_tasks,
)

__all__ = ["generate_podcast_task", "check_timeout_tasks"]
```

### 2.7 backend/celery_scheduler/tasks/podcast_tasks.py

```python
"""
播客生成 Celery 任务模块

职责：定义播客生成相关的 Celery 任务
设计原因：
1. Worker 执行实际的播客生成逻辑
2. 直接操作 MongoDB，移除 Java 中间层
3. 复用现有 podcast_middleware 的业务逻辑
"""
from __future__ import annotations

import logging
import time
import traceback
from typing import Any

from backend.celery_scheduler.celery_app import celery_app
from backend.celery_scheduler.storage.task_storage import TaskStorage


logger = logging.getLogger("celery_scheduler.tasks")


@celery_app.task(bind=True, name="generate_podcast")
def generate_podcast_task(self, run_id: str) -> dict[str, Any]:
    """
    Celery 任务：执行播客生成
    
    处理方式：同步任务，直接调用 podcast_middleware 的生成逻辑
    设计原因：
    1. Worker 负责完整的生成流程，不再是简单的投递
    2. 直接操作 MongoDB 更新状态
    3. 复用现有 podcast_middleware 的生成逻辑
    
    执行流程：
    1. 更新状态为 running
    2. 调用 podcast_middleware._run_generation
    3. 状态会在 _run_generation 内部更新为 done/error
    
    Args:
        run_id: 运行 ID
        
    Returns:
        执行结果
    """
    celery_task_id = self.request.id
    logger.info(f"[Worker] 开始播客生成任务 | run_id={run_id} | celery_task_id={celery_task_id}")
    
    storage = TaskStorage()
    start_time = time.time()
    
    try:
        # Step 1: 更新状态为 running
        storage.update_task_status(run_id=run_id, status="running")
        
        # Step 2: 调用 podcast_middleware 的生成逻辑
        # 注意：_run_generation 是同步方法，内部会自行更新状态
        from backend.middleware.podcast_middleware import build_podcast_middleware
        
        middleware = build_podcast_middleware()
        middleware._run_generation(run_id)
        
        # Step 3: 检查最终状态
        task_info = storage.get_task_status(run_id=run_id)
        final_status = task_info.get("status") if task_info else "unknown"
        
        processing_time = time.time() - start_time
        logger.info(f"[Worker] 播客生成完成 | run_id={run_id} | status={final_status} | time={processing_time:.2f}s")
        
        return {
            "run_id": run_id,
            "status": final_status,
            "processing_time": processing_time
        }
        
    except Exception as e:
        # 生成失败，更新状态为 error
        error_msg = str(e) or "生成失败"
        logger.error(f"[Worker] 播客生成失败 | run_id={run_id} | error={error_msg}")
        logger.error(traceback.format_exc())
        
        storage.update_task_status(
            run_id=run_id,
            status="error",
            message=error_msg
        )
        
        # 抛出异常让 Celery 记录失败
        raise
        
    finally:
        storage.close()


@celery_app.task(name="check_timeout_tasks")
def check_timeout_tasks() -> dict[str, Any]:
    """
    Celery Beat 定时任务：检查超时任务
    
    处理方式：扫描 running 状态超过指定时间的任务，标记为 error
    设计原因：
    1. Agent/Worker 可能因故障未能完成任务
    2. 定期清理超时任务，保证数据一致性
    
    Returns:
        处理结果统计
    """
    logger.info("[Worker] 开始检查超时任务")
    
    storage = TaskStorage()
    
    try:
        # 查找超时任务（默认 30 分钟）
        timeout_run_ids = storage.find_timeout_tasks(timeout_minutes=30)
        
        if not timeout_run_ids:
            logger.info("[Worker] 没有发现超时任务")
            return {"checked": 0, "marked": 0}
        
        logger.info(f"[Worker] 发现 {len(timeout_run_ids)} 个超时任务")
        
        # 批量标记超时
        marked_count = storage.mark_timeout_tasks(run_ids=timeout_run_ids)
        
        logger.info(f"[Worker] 超时任务处理完成 | checked={len(timeout_run_ids)} | marked={marked_count}")
        
        return {
            "checked": len(timeout_run_ids),
            "marked": marked_count
        }
        
    finally:
        storage.close()
```

---

## 3. 路由更新

### 3.1 backend/api/routers/podcast_router.py（更新部分）

在现有 `podcast_router.py` 中添加 Celery 任务提交支持：

```python
# 在文件顶部添加导入
from backend.celery_scheduler.celery_app import celery_app
from celery.result import AsyncResult

# 修改 podcast_generate 函数
@router.post("/api/podcast/generate")
def podcast_generate(payload: dict[str, Any]) -> dict[str, Any]:
    """提交播客生成任务（使用 Celery）"""
    svc = build_podcast_middleware()
    try:
        episode_profile = str(payload.get("episode_profile") or "").strip()
        speaker_profile = str(payload.get("speaker_profile") or "").strip()
        episode_name = str(payload.get("episode_name") or "").strip()
        source_ids = payload.get("source_ids")
        if not isinstance(source_ids, list):
            source_ids = []
        source_ids = [str(x) for x in source_ids if str(x).strip()]
        briefing_suffix = payload.get("briefing_suffix")
        briefing_suffix = str(briefing_suffix).strip() if briefing_suffix is not None else None

        if not episode_profile or not speaker_profile or not episode_name:
            raise HTTPException(status_code=400, detail="missing required fields")
        if not source_ids:
            raise HTTPException(status_code=400, detail="missing source_ids")

        svc.bootstrap_profiles()
        
        # 创建运行记录
        run = svc.create_run(
            episode_profile=episode_profile,
            speaker_profile=speaker_profile,
            source_ids=source_ids,
            episode_name=episode_name,
            briefing_suffix=briefing_suffix,
        )
        
        # 提交 Celery 任务（替代原来的 threading.Thread）
        celery_task = celery_app.send_task(
            "generate_podcast",
            args=[run.id]
        )
        
        # 更新 run 记录，关联 celery_task_id
        from backend.celery_scheduler.storage.task_storage import TaskStorage
        storage = TaskStorage()
        try:
            storage._runs_collection().update_one(
                {"run_id": run.id},
                {"$set": {"celery_task_id": celery_task.id}}
            )
        finally:
            storage.close()
        
        return {
            "run_id": run.id,
            "celery_task_id": celery_task.id,
            "status": run.status,
            "created_at": run.created_at
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "generate failed") from exc


# 新增 Celery 任务状态查询接口
@router.get("/api/celery/task/{task_id}")
def get_celery_task_status(task_id: str) -> dict[str, Any]:
    """查询 Celery 任务状态"""
    task_result = AsyncResult(task_id, app=celery_app)
    
    return {
        "task_id": task_id,
        "status": task_result.status,
        "ready": task_result.ready(),
        "successful": task_result.successful() if task_result.ready() else None,
        "result": task_result.result if task_result.ready() and task_result.successful() else None,
    }


# 新增 Celery 健康检查接口
@router.get("/api/celery/health")
def celery_health_check() -> dict[str, Any]:
    """Celery 健康检查"""
    try:
        # 检查 Broker 连接
        inspect = celery_app.control.inspect()
        ping_result = inspect.ping()
        
        if ping_result:
            workers = list(ping_result.keys())
            return {
                "status": "healthy",
                "workers": workers,
                "worker_count": len(workers),
                "broker": "connected"
            }
        else:
            return {
                "status": "degraded",
                "workers": [],
                "worker_count": 0,
                "broker": "connected",
                "message": "No workers responding"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
```

---

## 4. 启动脚本

### 4.1 scripts/celery_worker.sh

```bash
#!/bin/bash
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

echo "=========================================="
echo "Starting Celery Worker"
echo "Project Root: $PROJECT_ROOT"
echo "Concurrency: $CONCURRENCY"
echo "Log Level: $LOG_LEVEL"
echo "Queue: $QUEUE_NAME"
echo "=========================================="

# 启动 Worker
exec celery -A backend.celery_scheduler.celery_app worker \
    --loglevel="$LOG_LEVEL" \
    --concurrency="$CONCURRENCY" \
    --queues="$QUEUE_NAME" \
    --hostname="worker@%h" \
    --prefetch-multiplier=1
```

### 4.2 scripts/celery_beat.sh

```bash
#!/bin/bash
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

echo "=========================================="
echo "Starting Celery Beat"
echo "Project Root: $PROJECT_ROOT"
echo "Log Level: $LOG_LEVEL"
echo "=========================================="

# 启动 Beat
exec celery -A backend.celery_scheduler.celery_app beat \
    --loglevel="$LOG_LEVEL" \
    --scheduler=celery.beat:PersistentScheduler
```

### 4.3 scripts/supervisor/celery.conf

```ini
; Supervisor 配置文件
; 将此文件复制到 /etc/supervisor/conf.d/celery.conf

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

---

## 5. 依赖更新

### 5.1 requirements.txt 新增依赖

```
celery>=5.3.0
redis>=4.5.0
```

---

## 6. 环境变量配置示例

### 6.1 .env 示例

```bash
# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# Celery 配置
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CELERY_WORKER_CONCURRENCY=4
CELERY_TASK_TIME_LIMIT=1800
CELERY_TASK_SOFT_TIME_LIMIT=1500
CELERY_RESULT_EXPIRES=3600
CELERY_LOG_LEVEL=info

# MongoDB 配置
MONGODB_URI=mongodb://localhost:27017
DEEPAGENTS_MONGO_DB=deepagents_web

# 数据目录
DEEPAGENTS_DATA_DIR=/data/deepagents
```

---

## 7. 使用说明

### 7.1 启动服务

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动 Redis（如果未运行）
redis-server

# 3. 启动 Celery Worker
chmod +x scripts/celery_worker.sh
./scripts/celery_worker.sh

# 4. 启动 Celery Beat（新终端）
chmod +x scripts/celery_beat.sh
./scripts/celery_beat.sh

# 5. 启动 FastAPI 应用（新终端）
uvicorn backend.api.web_app:app --reload
```

### 7.2 监控

```bash
# 启动 Flower 监控面板
pip install flower
celery -A backend.celery_scheduler.celery_app flower --port=5555

# 访问 http://localhost:5555
```

### 7.3 测试任务提交

```bash
# 提交播客生成任务
curl -X POST http://localhost:8000/api/podcast/generate \
  -H "Content-Type: application/json" \
  -d '{
    "episode_profile": "default",
    "speaker_profile": "two_hosts",
    "episode_name": "测试节目",
    "source_ids": ["507f1f77bcf86cd799439011"]
  }'

# 查询 Celery 任务状态
curl http://localhost:8000/api/celery/task/{task_id}

# Celery 健康检查
curl http://localhost:8000/api/celery/health
```

---

## 8. 迁移检查清单

- [ ] 创建 `backend/celery_scheduler/` 目录结构
- [ ] 实现 `config.py` 配置管理
- [ ] 实现 `celery_app.py` Celery 应用配置
- [ ] 实现 `storage/task_storage.py` MongoDB 存储
- [ ] 实现 `tasks/podcast_tasks.py` Celery 任务
- [ ] 更新 `podcast_router.py` 使用 Celery
- [ ] 创建启动脚本 `celery_worker.sh`、`celery_beat.sh`
- [ ] 创建 Supervisor 配置
- [ ] 更新 `requirements.txt`
- [ ] 配置环境变量
- [ ] 测试完整流程
