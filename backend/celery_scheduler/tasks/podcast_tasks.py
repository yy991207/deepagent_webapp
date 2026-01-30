"""
Celery 任务定义 - 投递+Callback 模式

架构说明：
┌──────────────┐    ┌───────────────┐    ┌──────────────┐
│   FastAPI    │───▶│ Celery Worker │───▶│ Podcast Agent│
│   (提交任务) │    │ (快速投递)    │    │   Service    │
└──────────────┘    └───────────────┘    └──────┬───────┘
       ▲                                        │
       │            ┌───────────────┐           │
       └────────────│   Callback    │◀──────────┘
                    │   (结果回调)  │
                    └───────────────┘
                           │
                           ▼
                    ┌───────────────┐
                    │    MongoDB    │
                    └───────────────┘

执行流程：
1. API 接收请求 → 提交 Celery 任务
2. Celery Worker 向 Podcast Agent Service 发起 HTTP 请求（投递）
3. Celery Worker 立即返回（不等待执行完成）
4. Podcast Agent Service 异步执行播客生成
5. 完成后，Agent Service 调用 callback 接口通知结果
6. Callback 接口更新 MongoDB 状态和结果
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from backend.celery_scheduler.celery_app import celery_app
from backend.celery_scheduler.storage.task_storage import TaskStorage

logger = logging.getLogger(__name__)

# 默认 Podcast Agent Service 地址
PODCAST_AGENT_URL = os.environ.get("PODCAST_AGENT_URL", "http://localhost:8888")
# 投递超时（秒）
DELIVERY_TIMEOUT = int(os.environ.get("CELERY_DELIVERY_TIMEOUT", "30"))
# 回调 URL
CALLBACK_BASE_URL = os.environ.get("CALLBACK_BASE_URL", "http://localhost:7777")


def get_task_storage() -> TaskStorage:
    """获取任务存储实例。"""
    return TaskStorage()


@celery_app.task(
    bind=True,
    name="deliver_podcast_task",
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(requests.RequestException,),
)
def deliver_podcast_task(self, run_id: str) -> dict[str, Any]:
    """投递播客生成任务到 Podcast Agent Service。
    
    此任务只负责投递，不等待执行完成。执行完成后由 Agent Service 回调通知。
    
    Args:
        run_id: 播客运行 ID
        
    Returns:
        投递结果
    """
    task_id = self.request.id
    storage = get_task_storage()
    
    logger.info(f"[Celery] 开始投递任务 | run_id={run_id} | task_id={task_id}")
    
    # 1. 在 MongoDB 创建任务记录
    storage.create_task(
        task_id=task_id,
        run_id=run_id,
        task_type="podcast_generation",
        metadata={"celery_task_id": task_id},
    )
    
    # 2. 更新状态为 STARTED
    storage.update_task_status(
        task_id=task_id,
        status="STARTED",
        message="任务已投递到 Agent Service",
    )
    
    # 3. 构建回调 URL
    callback_url = f"{CALLBACK_BASE_URL}/api/podcast/callback"
    
    # 4. 构建投递请求
    delivery_payload = {
        "task_id": task_id,
        "run_id": run_id,
        "callback_url": callback_url,
        "task_type": "podcast_generation",
    }
    
    # 5. 投递到 Podcast Agent Service
    try:
        agent_endpoint = f"{PODCAST_AGENT_URL}/api/agent/run"
        logger.info(f"[Celery] 投递请求 | url={agent_endpoint} | payload={delivery_payload}")
        
        response = requests.post(
            agent_endpoint,
            json=delivery_payload,
            timeout=DELIVERY_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"[Celery] 投递成功 | run_id={run_id} | response={result}")
        
        # 更新投递成功状态
        storage.update_task_status(
            task_id=task_id,
            status="DELIVERED",
            message="任务已成功投递到 Agent Service",
        )
        
        return {
            "success": True,
            "run_id": run_id,
            "task_id": task_id,
            "status": "DELIVERED",
            "agent_response": result,
        }
        
    except requests.RequestException as e:
        logger.error(f"[Celery] 投递失败 | run_id={run_id} | error={e}")
        
        # 更新投递失败状态
        storage.update_task_status(
            task_id=task_id,
            status="DELIVERY_FAILED",
            message=f"投递失败: {str(e)}",
        )
        
        # 触发重试
        raise


@celery_app.task(name="check_timeout_tasks")
def check_timeout_tasks() -> dict[str, Any]:
    """检查超时任务并标记为失败。
    
    由 Celery Beat 定时调用。
    
    Returns:
        处理结果
    """
    logger.info("[Celery Beat] 开始检查超时任务")
    
    try:
        storage = get_task_storage()
        
        # 查找超时任务（默认 30 分钟）
        timeout_minutes = int(os.environ.get("TASK_TIMEOUT_MINUTES", "30"))
        timeout_tasks = storage.find_timeout_tasks(timeout_minutes=timeout_minutes)
        
        processed = 0
        for task in timeout_tasks:
            task_id = task.get("task_id")
            if task_id:
                storage.update_task_status(
                    task_id=task_id,
                    status="TIMEOUT",
                    message=f"任务超时（超过 {timeout_minutes} 分钟）",
                )
                logger.warning(f"[Celery Beat] 任务超时 | task_id={task_id}")
                processed += 1
        
        logger.info(f"[Celery Beat] 超时检查完成 | processed={processed}")
        return {"processed": processed, "timeout_minutes": timeout_minutes}
        
    except Exception as e:
        logger.error(f"[Celery Beat] 超时检查失败 | error={e}")
        return {"error": str(e)}


@celery_app.task(name="process_callback_result")
def process_callback_result(
    task_id: str,
    run_id: str,
    status: str,
    result_data: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """处理 Agent Service 的回调结果。
    
    此任务由 callback 接口调用，用于异步处理回调结果。
    
    Args:
        task_id: 任务 ID
        run_id: 运行 ID
        status: 任务状态（SUCCESS/FAILURE）
        result_data: 成功时的结果数据
        error_message: 失败时的错误信息
        
    Returns:
        处理结果
    """
    logger.info(f"[Celery] 处理回调结果 | task_id={task_id} | status={status}")
    
    try:
        storage = get_task_storage()
        
        if status == "SUCCESS":
            storage.update_task_status(
                task_id=task_id,
                status="SUCCESS",
                message="任务执行成功",
            )
            if result_data:
                storage.save_result(
                    task_id=task_id,
                    run_id=run_id,
                    result_data=result_data,
                )
        else:
            storage.update_task_status(
                task_id=task_id,
                status="FAILURE",
                message=error_message or "任务执行失败",
            )
        
        return {
            "success": True,
            "task_id": task_id,
            "run_id": run_id,
            "status": status,
        }
        
    except Exception as e:
        logger.error(f"[Celery] 回调处理失败 | task_id={task_id} | error={e}")
        return {"success": False, "error": str(e)}
