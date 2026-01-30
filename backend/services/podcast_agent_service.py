"""
独立播客生成服务（Podcast Agent Service）

此服务作为独立进程运行，接收 Celery Worker 的投递请求，
异步执行播客生成，完成后通过 callback 通知结果。

架构位置：
┌──────────────┐    ┌───────────────┐    ┌──────────────┐
│   FastAPI    │───▶│ Celery Worker │───▶│ Podcast Agent│ ◀── 本服务
│   (提交任务) │    │ (快速投递)    │    │   Service    │
└──────────────┘    └───────────────┘    └──────┬───────┘
       ▲                                        │
       │            ┌───────────────┐           │
       └────────────│   Callback    │◀──────────┘
                    │   (结果回调)  │
                    └───────────────┘

启动方式：
  python -m backend.services.podcast_agent_service
  或
  uvicorn backend.services.podcast_agent_service:app --host 0.0.0.0 --port 8888
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("podcast_agent_service")

app = FastAPI(
    title="Podcast Agent Service",
    description="独立播客生成服务，接收任务投递，异步执行后回调结果",
    version="1.0.0",
)

# 存储正在执行的任务
_running_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = threading.Lock()


class TaskRunRequest(BaseModel):
    """任务投递请求"""
    task_id: str
    run_id: str
    callback_url: str
    task_type: str = "podcast_generation"
    agent_id: str | None = None
    
    # 播客生成配置字段
    episode_profile: str | None = None
    speaker_profile: str | None = None
    episode_name: str | None = None
    source_ids: list[str] | None = None
    briefing_suffix: str | None = None


class TaskCancelRequest(BaseModel):
    """任务取消请求"""
    task_id: str


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    running_tasks: int
    timestamp: str


# ==============================================================================
# API 端点
# ==============================================================================

@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """健康检查"""
    with _tasks_lock:
        running_count = len(_running_tasks)
    return HealthResponse(
        status="healthy",
        running_tasks=running_count,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/api/agent/run")
def run_agent_task(request: TaskRunRequest) -> dict[str, Any]:
    """接收任务投递，启动异步执行。
    
    此接口立即返回，不等待任务执行完成。
    执行完成后通过 callback_url 通知结果。
    """
    task_id = request.task_id
    run_id = request.run_id
    callback_url = request.callback_url
    
    logger.info(f"[Agent] 收到任务投递 | task_id={task_id} | run_id={run_id}")
    logger.info(f"[Agent] 播客配置 | episode_profile={request.episode_profile} | speaker_profile={request.speaker_profile}")
    
    # 检查任务是否已在执行
    with _tasks_lock:
        if task_id in _running_tasks:
            raise HTTPException(
                status_code=409,
                detail=f"任务已在执行中: {task_id}"
            )
        
        # 记录任务（包含播客配置）
        _running_tasks[task_id] = {
            "run_id": run_id,
            "callback_url": callback_url,
            "started_at": datetime.utcnow().isoformat(),
            "status": "RUNNING",
            # 播客配置
            "episode_profile": request.episode_profile,
            "speaker_profile": request.speaker_profile,
            "episode_name": request.episode_name,
            "source_ids": request.source_ids,
            "briefing_suffix": request.briefing_suffix,
        }
    
    # 启动后台线程执行任务
    thread = threading.Thread(
        target=_execute_podcast_generation,
        args=(task_id, run_id, callback_url, request),
        daemon=True,
    )
    thread.start()
    
    return {
        "success": True,
        "task_id": task_id,
        "run_id": run_id,
        "message": "任务已接收，开始异步执行",
    }


@app.post("/api/agent/cancel")
def cancel_agent_task(request: TaskCancelRequest) -> dict[str, Any]:
    """取消任务（标记为取消，实际执行可能无法中断）"""
    task_id = request.task_id
    
    with _tasks_lock:
        if task_id not in _running_tasks:
            raise HTTPException(
                status_code=404,
                detail=f"任务不存在: {task_id}"
            )
        
        _running_tasks[task_id]["status"] = "CANCELLED"
    
    logger.info(f"[Agent] 任务已标记取消 | task_id={task_id}")
    
    return {
        "success": True,
        "task_id": task_id,
        "message": "任务已标记为取消",
    }


@app.get("/api/agent/tasks")
def list_running_tasks() -> dict[str, Any]:
    """列出正在执行的任务"""
    with _tasks_lock:
        tasks = list(_running_tasks.values())
    return {"tasks": tasks, "count": len(tasks)}


# ==============================================================================
# 任务执行逻辑
# ==============================================================================

def _execute_podcast_generation(
    task_id: str,
    run_id: str,
    callback_url: str,
    request: TaskRunRequest,
) -> None:
    """执行播客生成（在独立线程中运行）
    
    流程：
    1. 检查是否已取消
    2. 在 MongoDB 创建播客运行记录（如果不存在）
    3. 调用 middleware._run_generation 执行生成
    4. 获取结果并发送回调
    """
    logger.info(f"[Agent] 开始执行任务 | task_id={task_id} | run_id={run_id}")
    
    result_data = None
    error_message = None
    status = "SUCCESS"
    
    try:
        # 检查是否已取消
        with _tasks_lock:
            task_info = _running_tasks.get(task_id, {})
            if task_info.get("status") == "CANCELLED":
                logger.info(f"[Agent] 任务已取消，跳过执行 | task_id={task_id}")
                status = "CANCELLED"
                error_message = "任务被取消"
                return
        
        # 导入播客中间件
        from backend.middleware.podcast_middleware import build_podcast_middleware
        
        middleware = build_podcast_middleware()
        
        # 检查是否已存在运行记录
        existing_run = middleware.get_run_detail(run_id=run_id)
        
        if not existing_run:
            # 创建新的播客运行记录
            logger.info(f"[Agent] 创建播客运行记录 | run_id={run_id}")
            
            # 验证必要配置
            if not request.episode_profile or not request.speaker_profile:
                raise ValueError(
                    f"缺少播客配置: episode_profile={request.episode_profile}, "
                    f"speaker_profile={request.speaker_profile}"
                )
            
            # 直接插入运行记录到 MongoDB（使用传入的 run_id）
            from datetime import timezone
            now = datetime.now(timezone.utc)
            doc = {
                "run_id": run_id,
                "status": "queued",
                "episode_profile": request.episode_profile,
                "speaker_profile": request.speaker_profile,
                "episode_name": request.episode_name or run_id,
                "source_ids": request.source_ids or [],
                "briefing_suffix": request.briefing_suffix,
                "created_at": now,
                "updated_at": now,
            }
            middleware._col(middleware._runs_collection).insert_one(doc)
            
            logger.info(f"[Agent] 播客运行记录已创建 | run_id={run_id}")
        else:
            # 已存在记录，更新配置字段（确保使用最新的配置）
            logger.info(f"[Agent] 更新已存在的运行记录配置 | run_id={run_id}")

            # 验证必要配置
            if not request.episode_profile or not request.speaker_profile:
                raise ValueError(
                    f"缺少播客配置: episode_profile={request.episode_profile}, "
                    f"speaker_profile={request.speaker_profile}"
                )

            from datetime import timezone
            now = datetime.now(timezone.utc)
            middleware._col(middleware._runs_collection).update_one(
                {"run_id": run_id},
                {"$set": {
                    "episode_profile": request.episode_profile,
                    "speaker_profile": request.speaker_profile,
                    "episode_name": request.episode_name or run_id,
                    "source_ids": request.source_ids or [],
                    "briefing_suffix": request.briefing_suffix,
                    "status": "queued",
                    "updated_at": now,
                }}
            )
        
        # 调用核心生成方法
        middleware._run_generation(run_id)
        
        # 获取执行结果
        result = middleware.get_result(run_id=run_id)
        run_detail = middleware.get_run_detail(run_id=run_id)
        
        if run_detail and run_detail.get("status") == "done":
            status = "SUCCESS"
            result_data = result
            logger.info(f"[Agent] 任务执行成功 | task_id={task_id}")
        else:
            status = "FAILURE"
            error_message = run_detail.get("message") if run_detail else "执行失败"
            logger.error(f"[Agent] 任务执行失败 | task_id={task_id} | error={error_message}")
            
    except Exception as e:
        status = "FAILURE"
        error_message = str(e)
        logger.exception(f"[Agent] 任务执行异常 | task_id={task_id} | error={e}")
    
    finally:
        # 清理任务记录
        with _tasks_lock:
            _running_tasks.pop(task_id, None)
        
        # 发送回调通知
        _send_callback(task_id, run_id, callback_url, status, result_data, error_message)


def _send_callback(
    task_id: str,
    run_id: str,
    callback_url: str,
    status: str,
    result_data: dict[str, Any] | None,
    error_message: str | None,
) -> None:
    """发送回调通知"""
    logger.info(f"[Agent] 发送回调 | task_id={task_id} | status={status} | url={callback_url}")
    
    callback_payload = {
        "task_id": task_id,
        "run_id": run_id,
        "status": status,
        "result_data": result_data,
        "error_message": error_message,
        "completed_at": datetime.utcnow().isoformat(),
    }
    
    # 重试发送回调
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(
                callback_url,
                json=callback_payload,
                timeout=30,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            logger.info(f"[Agent] 回调成功 | task_id={task_id} | attempt={attempt + 1}")
            return
        except requests.RequestException as e:
            logger.warning(f"[Agent] 回调失败 | task_id={task_id} | attempt={attempt + 1} | error={e}")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))  # 指数退避
    
    logger.error(f"[Agent] 回调最终失败 | task_id={task_id} | 已尝试 {max_retries} 次")


# ==============================================================================
# 主入口
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    
    host = os.environ.get("PODCAST_AGENT_HOST", "0.0.0.0")
    port = int(os.environ.get("PODCAST_AGENT_PORT", "8888"))
    
    logger.info(f"启动 Podcast Agent Service | host={host} | port={port}")
    uvicorn.run(app, host=host, port=port)
