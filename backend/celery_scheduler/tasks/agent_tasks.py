"""
通用 Agent 任务 - 基于注册表的投递和回调处理

此模块提供通用的 Celery 任务，支持：
1. 根据 agent_id 从注册表获取 Agent 配置
2. 投递任务到对应的 Agent Service
3. 处理 Agent Service 的回调结果

使用方式：
    from backend.celery_scheduler.tasks.agent_tasks import deliver_task
    
    # 投递任务到指定 Agent
    result = deliver_task.delay(
        agent_id="podcast_agent",
        run_id="run_123",
        task_type="podcast_generation",
        payload={"source_ids": ["doc1", "doc2"]}
    )
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

import requests

from backend.celery_scheduler.celery_app import celery_app
from backend.celery_scheduler.registry import AgentConfig, get_agent_registry
from backend.celery_scheduler.storage.task_storage import TaskStorage

logger = logging.getLogger(__name__)

# 默认回调 URL
CALLBACK_BASE_URL = os.environ.get("CALLBACK_BASE_URL", "http://localhost:7777")


def get_task_storage() -> TaskStorage:
    """获取任务存储实例。"""
    return TaskStorage()


@celery_app.task(
    bind=True,
    name="deliver_agent_task",
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(requests.RequestException,),
)
def deliver_agent_task(
    self,
    agent_id: str,
    run_id: str,
    task_type: str = "generic",
    payload: dict[str, Any] | None = None,
    callback_path: str = "/api/agent/callback",
) -> dict[str, Any]:
    """通用任务投递 - 根据 agent_id 从注册表获取配置并投递。
    
    Args:
        agent_id: Agent 标识符（在注册表中注册的 ID）
        run_id: 业务运行 ID
        task_type: 任务类型
        payload: 附加参数
        callback_path: 回调路径
        
    Returns:
        投递结果
    """
    celery_task_id = self.request.id
    storage = get_task_storage()
    registry = get_agent_registry()
    
    logger.info(
        f"[Celery] 开始投递任务 | agent_id={agent_id} | "
        f"run_id={run_id} | task_id={celery_task_id}"
    )
    
    # 1. 从注册表获取 Agent 配置
    agent = registry.get(agent_id)
    if not agent:
        error_msg = f"Agent 未注册: {agent_id}"
        logger.error(f"[Celery] {error_msg}")
        storage.create_task(
            task_id=celery_task_id,
            run_id=run_id,
            task_type=task_type,
            metadata={"agent_id": agent_id, "error": error_msg},
        )
        storage.update_task_status(
            task_id=celery_task_id,
            status="AGENT_NOT_FOUND",
            message=error_msg,
        )
        return {
            "success": False,
            "run_id": run_id,
            "task_id": celery_task_id,
            "error": error_msg,
        }
    
    if not agent.enabled:
        error_msg = f"Agent 已禁用: {agent_id}"
        logger.error(f"[Celery] {error_msg}")
        return {
            "success": False,
            "run_id": run_id,
            "task_id": celery_task_id,
            "error": error_msg,
        }
    
    # 2. 在 MongoDB 创建任务记录
    storage.create_task(
        task_id=celery_task_id,
        run_id=run_id,
        task_type=task_type,
        metadata={
            "agent_id": agent_id,
            "agent_url": agent.url,
            "celery_task_id": celery_task_id,
        },
    )
    
    # 3. 更新状态为 STARTED
    storage.update_task_status(
        task_id=celery_task_id,
        status="STARTED",
        message=f"任务开始投递到 {agent.name}",
    )
    
    # 4. 构建回调 URL
    callback_url = f"{CALLBACK_BASE_URL}{callback_path}"
    
    # 5. 构建投递请求
    delivery_payload = {
        "task_id": celery_task_id,
        "run_id": run_id,
        "callback_url": callback_url,
        "task_type": task_type,
        "agent_id": agent_id,
        **(payload or {}),
    }
    
    # 6. 投递到 Agent Service
    try:
        agent_endpoint = agent.get_run_url()
        logger.info(f"[Celery] 投递请求 | url={agent_endpoint}")
        
        response = requests.post(
            agent_endpoint,
            json=delivery_payload,
            timeout=agent.timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"[Celery] 投递成功 | agent_id={agent_id} | run_id={run_id}")
        
        # 更新投递成功状态
        storage.update_task_status(
            task_id=celery_task_id,
            status="DELIVERED",
            message=f"任务已成功投递到 {agent.name}",
        )
        
        return {
            "success": True,
            "run_id": run_id,
            "task_id": celery_task_id,
            "agent_id": agent_id,
            "status": "DELIVERED",
            "agent_response": result,
        }
        
    except requests.RequestException as e:
        logger.error(f"[Celery] 投递失败 | agent_id={agent_id} | error={e}")
        
        # 更新投递失败状态
        storage.update_task_status(
            task_id=celery_task_id,
            status="DELIVERY_FAILED",
            message=f"投递到 {agent.name} 失败: {str(e)}",
        )
        
        # 检查是否需要重试
        if self.request.retries < self.max_retries:
            raise  # 触发重试
        
        return {
            "success": False,
            "run_id": run_id,
            "task_id": celery_task_id,
            "agent_id": agent_id,
            "status": "DELIVERY_FAILED",
            "error": str(e),
        }


@celery_app.task(name="process_agent_callback")
def process_agent_callback(
    task_id: str,
    run_id: str,
    agent_id: str,
    status: str,
    result_data: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """处理 Agent Service 的回调结果。
    
    Args:
        task_id: Celery 任务 ID
        run_id: 业务运行 ID
        agent_id: Agent 标识符
        status: 任务状态（SUCCESS/FAILURE/CANCELLED）
        result_data: 成功时的结果数据
        error_message: 失败时的错误信息
        
    Returns:
        处理结果
    """
    logger.info(
        f"[Celery] 处理回调 | task_id={task_id} | "
        f"agent_id={agent_id} | status={status}"
    )
    
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
        elif status == "CANCELLED":
            storage.update_task_status(
                task_id=task_id,
                status="REVOKED",
                message="任务被取消",
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
            "agent_id": agent_id,
            "status": status,
        }
        
    except Exception as e:
        logger.error(f"[Celery] 回调处理失败 | task_id={task_id} | error={e}")
        return {"success": False, "error": str(e)}


@celery_app.task(name="cancel_agent_task")
def cancel_agent_task(
    task_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """取消 Agent 任务。
    
    Args:
        task_id: 任务 ID
        agent_id: Agent 标识符
        
    Returns:
        取消结果
    """
    logger.info(f"[Celery] 取消任务 | task_id={task_id} | agent_id={agent_id}")
    
    registry = get_agent_registry()
    storage = get_task_storage()
    
    agent = registry.get(agent_id)
    if not agent:
        return {"success": False, "error": f"Agent 未注册: {agent_id}"}
    
    try:
        # 向 Agent Service 发送取消请求
        response = requests.post(
            agent.get_cancel_url(),
            json={"task_id": task_id},
            timeout=agent.timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        
        # 更新任务状态
        storage.update_task_status(
            task_id=task_id,
            status="REVOKED",
            message="任务已取消",
        )
        
        return {"success": True, "task_id": task_id, "status": "REVOKED"}
        
    except requests.RequestException as e:
        logger.error(f"[Celery] 取消任务失败 | task_id={task_id} | error={e}")
        return {"success": False, "error": str(e)}


@celery_app.task(name="check_timeout_tasks")
def check_timeout_tasks() -> dict[str, Any]:
    """检查超时任务并标记为失败。
    
    由 Celery Beat 定时调用。
    """
    logger.info("[Celery Beat] 开始检查超时任务")
    
    try:
        storage = get_task_storage()
        
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


@celery_app.task(name="check_agents_health")
def check_agents_health() -> dict[str, Any]:
    """检查所有注册 Agent 的健康状态。
    
    由 Celery Beat 定时调用。
    """
    logger.info("[Celery Beat] 开始检查 Agent 健康状态")
    
    try:
        registry = get_agent_registry()
        results = registry.check_all_health(timeout=5)
        
        healthy_count = sum(1 for r in results.values() if r.get("healthy"))
        total_count = len(results)
        
        logger.info(
            f"[Celery Beat] 健康检查完成 | "
            f"healthy={healthy_count}/{total_count}"
        )
        
        return {
            "results": results,
            "healthy_count": healthy_count,
            "total_count": total_count,
        }
        
    except Exception as e:
        logger.error(f"[Celery Beat] 健康检查失败 | error={e}")
        return {"error": str(e)}
