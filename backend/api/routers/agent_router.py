"""
统一 Agent 回调路由

提供统一的回调接口，接收所有 Agent Service 的回调通知。
支持新的 payload 结构：agent_id, config, meta_info
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.celery_scheduler.registry import get_agent_registry

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger(__name__)


# ==============================================================================
# Pydantic 模型
# ==============================================================================
class AgentCallbackPayload(BaseModel):
    """Agent Service 回调请求体"""
    task_id: str
    run_id: str
    agent_id: str | None = None  # 可选，用于识别回调来源
    status: str  # SUCCESS / FAILURE / CANCELLED
    result_data: dict[str, Any] | None = None
    error_message: str | None = None
    completed_at: str | None = None


class AgentRunConfig(BaseModel):
    """Agent 任务配置对象"""
    # 通用配置
    timeout: int | None = Field(default=None, description="任务超时时间（秒）")
    priority: int | None = Field(default=0, description="任务优先级，数值越大优先级越高")
    retry_count: int | None = Field(default=0, description="重试次数")
    
    # 播客生成专用配置
    episode_profile: str | None = Field(default=None, description="节目配置名称")
    speaker_profile: str | None = Field(default=None, description="发言人配置名称")
    episode_name: str | None = Field(default=None, description="播客标题")
    source_ids: list[str] | None = Field(default=None, description="数据源ID列表")
    briefing_suffix: str | None = Field(default=None, description="补充指令")
    
    # 其他 Agent 配置可扩展
    extra: dict[str, Any] | None = Field(default=None, description="扩展配置")


class AgentRunMetaInfo(BaseModel):
    """Agent 任务元信息"""
    user_id: str | None = Field(default=None, description="用户ID")
    session_id: str | None = Field(default=None, description="会话ID")
    request_id: str | None = Field(default=None, description="请求追踪ID")
    client_ip: str | None = Field(default=None, description="客户端IP")
    user_agent: str | None = Field(default=None, description="客户端User-Agent")
    extra: dict[str, Any] | None = Field(default=None, description="扩展元信息")


class AgentRunRequest(BaseModel):
    """提交 Agent 任务请求（新格式）
    
    包含三个核心字段：
    - agent_id: 目标 Agent 标识
    - config: 任务配置对象
    - meta_info: 任务元信息
    """
    agent_id: str = Field(..., description="目标 Agent 标识")
    config: AgentRunConfig = Field(default_factory=AgentRunConfig, description="任务配置")
    meta_info: AgentRunMetaInfo | None = Field(default=None, description="任务元信息")
    
    # 兼容旧格式
    run_id: str | None = Field(default=None, description="[兼容] 运行ID")
    task_type: str = Field(default="generic", description="[兼容] 任务类型")
    payload: dict[str, Any] | None = Field(default=None, description="[兼容] 旧格式payload")


class AgentCancelRequest(BaseModel):
    """取消 Agent 任务请求"""
    task_id: str
    agent_id: str


class TaskPollResponse(BaseModel):
    """任务轮询响应"""
    task_id: str
    status: str  # PENDING / STARTED / DELIVERED / SUCCESS / FAILURE / CANCELLED
    progress: int | None = Field(default=None, description="进度百分比 0-100")
    message: str | None = Field(default=None, description="状态描述")
    result: dict[str, Any] | None = Field(default=None, description="任务结果（仅终态时返回）")
    error: str | None = Field(default=None, description="错误信息（仅失败时返回）")
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


# ==============================================================================
# 辅助函数
# ==============================================================================
def _use_celery() -> bool:
    """判断是否使用 Celery 调度。"""
    import os
    val = os.environ.get("USE_CELERY", "").lower()
    return val in ("1", "true", "yes", "on")


def _get_deliver_task():
    """延迟导入 Celery 投递任务。"""
    from backend.celery_scheduler.tasks.agent_tasks import deliver_agent_task
    return deliver_agent_task


def _get_callback_task():
    """延迟导入 Celery 回调处理任务。"""
    from backend.celery_scheduler.tasks.agent_tasks import process_agent_callback
    return process_agent_callback


def _get_cancel_task():
    """延迟导入 Celery 取消任务。"""
    from backend.celery_scheduler.tasks.agent_tasks import cancel_agent_task
    return cancel_agent_task


# ==============================================================================
# API 端点
# ==============================================================================
@router.post("/run")
def submit_agent_task(request: AgentRunRequest) -> dict[str, Any]:
    """提交任务到指定 Agent。
    
    新格式支持：
    - agent_id: 目标 Agent 标识
    - config: 任务配置对象（包含 episode_profile, speaker_profile 等）
    - meta_info: 任务元信息（user_id, session_id 等）
    
    返回：
    - task_id: 任务唯一标识，用于后续轮询
    - status: 任务状态
    """
    if not _use_celery():
        raise HTTPException(
            status_code=400,
            detail="Celery mode is not enabled. Set USE_CELERY=1 to enable."
        )
    
    # 生成唯一的 run_id（如果未提供）
    run_id = request.run_id or str(uuid.uuid4())
    
    logger.info(
        f"[API] 提交 Agent 任务 | agent_id={request.agent_id} | "
        f"run_id={run_id}"
    )
    
    # 检查 Agent 是否存在
    registry = get_agent_registry()
    agent = registry.get(request.agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent not found: {request.agent_id}"
        )
    
    if not agent.enabled:
        raise HTTPException(
            status_code=400,
            detail=f"Agent is disabled: {request.agent_id}"
        )
    
    try:
        # 构建统一的 payload
        # 优先使用新格式 config，兼容旧格式 payload
        if request.config:
            payload = {
                "episode_profile": request.config.episode_profile,
                "speaker_profile": request.config.speaker_profile,
                "episode_name": request.config.episode_name,
                "source_ids": request.config.source_ids,
                "briefing_suffix": request.config.briefing_suffix,
                "timeout": request.config.timeout,
                "priority": request.config.priority,
                "retry_count": request.config.retry_count,
                **(request.config.extra or {}),
            }
            # 过滤掉 None 值
            payload = {k: v for k, v in payload.items() if v is not None}
        else:
            payload = request.payload or {}
        
        # 添加 meta_info 到 payload
        if request.meta_info:
            payload["_meta"] = {
                "user_id": request.meta_info.user_id,
                "session_id": request.meta_info.session_id,
                "request_id": request.meta_info.request_id,
                "client_ip": request.meta_info.client_ip,
                "user_agent": request.meta_info.user_agent,
                **(request.meta_info.extra or {}),
            }
            payload["_meta"] = {k: v for k, v in payload["_meta"].items() if v is not None}
        
        deliver_task = _get_deliver_task()
        celery_result = deliver_task.delay(
            agent_id=request.agent_id,
            run_id=run_id,
            task_type=request.task_type,
            payload=payload,
        )
        
        # task_id 使用 run_id（业务ID），而不是 celery_task_id（Celery内部ID）
        return {
            "success": True,
            "task_id": run_id,  # 前端用于轮询的 ID
            "run_id": run_id,
            "agent_id": request.agent_id,
            "celery_task_id": celery_result.id,
            "status": "PENDING",
            "message": "任务已提交，正在排队处理",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as exc:
        logger.error(f"[API] 提交任务失败 | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/callback")
def agent_callback(payload: AgentCallbackPayload) -> dict[str, Any]:
    """接收 Agent Service 的回调通知。
    
    此接口由各个 Agent Service 在任务完成后调用，
    用于通知任务执行结果并更新数据库状态。
    """
    logger.info(
        f"[Callback] 收到回调 | task_id={payload.task_id} | "
        f"agent_id={payload.agent_id} | status={payload.status}"
    )
    
    try:
        if _use_celery():
            # 使用 Celery 任务异步处理回调结果
            process_callback = _get_callback_task()
            process_callback.delay(
                task_id=payload.task_id,
                run_id=payload.run_id,
                agent_id=payload.agent_id or "unknown",
                status=payload.status,
                result_data=payload.result_data,
                error_message=payload.error_message,
            )
            return {
                "success": True,
                "message": "回调已接收，正在异步处理",
                "task_id": payload.task_id,
            }
        else:
            # 非 Celery 模式
            return {
                "success": True,
                "message": "回调已接收（Celery 未启用）",
                "task_id": payload.task_id,
            }
    except Exception as exc:
        logger.error(f"[Callback] 处理失败 | task_id={payload.task_id} | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/cancel")
def cancel_agent_task_api(request: AgentCancelRequest) -> dict[str, Any]:
    """取消 Agent 任务。"""
    if not _use_celery():
        raise HTTPException(
            status_code=400,
            detail="Celery mode is not enabled. Set USE_CELERY=1 to enable."
        )
    
    logger.info(
        f"[API] 取消任务 | task_id={request.task_id} | "
        f"agent_id={request.agent_id}"
    )
    
    try:
        cancel_task = _get_cancel_task()
        celery_result = cancel_task.delay(
            task_id=request.task_id,
            agent_id=request.agent_id,
        )
        
        return {
            "success": True,
            "task_id": request.task_id,
            "celery_task_id": celery_result.id,
            "status": "cancel_requested",
        }
    except Exception as exc:
        logger.error(f"[API] 取消任务失败 | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/task/{task_id}/status")
def get_task_status(task_id: str) -> dict[str, Any]:
    """查询任务状态（从 MongoDB）。"""
    if not _use_celery():
        raise HTTPException(
            status_code=400,
            detail="Celery mode is not enabled. Set USE_CELERY=1 to enable."
        )
    
    try:
        from backend.celery_scheduler.storage.task_storage import TaskStorage
        
        storage = TaskStorage()
        
        # 尝试用 task_id 查询，如果失败则用 run_id 查询
        task_status = storage.get_task_status(run_id=task_id)
        if task_status is None:
            raise HTTPException(status_code=404, detail="Task not found")
        
        return task_status
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/task/{task_id}/poll")
def poll_task_status(task_id: str) -> TaskPollResponse:
    """轮询任务状态（专为前端轮询设计）。
    
    返回标准化的轮询响应，包含：
    - task_id: 任务ID
    - status: 任务状态 (PENDING/STARTED/DELIVERED/SUCCESS/FAILURE/CANCELLED)
    - progress: 进度百分比（如果可用）
    - message: 状态描述
    - result: 任务结果（仅终态时返回）
    - error: 错误信息（仅失败时返回）
    
    终态判断：status in (SUCCESS, FAILURE, CANCELLED) 时停止轮询。
    """
    if not _use_celery():
        raise HTTPException(
            status_code=400,
            detail="Celery mode is not enabled. Set USE_CELERY=1 to enable."
        )
    
    try:
        from backend.celery_scheduler.storage.task_storage import TaskStorage
        
        storage = TaskStorage()
        
        # 用 run_id 查询（task_id 对前端就是 run_id）
        task_status = storage.get_task_status(run_id=task_id)
        
        if task_status is None:
            # 任务不存在，可能还在排队中
            return TaskPollResponse(
                task_id=task_id,
                status="PENDING",
                message="任务正在排队中",
            )
        
        status = task_status.get("status", "PENDING")
        
        # 根据状态构建响应
        response = TaskPollResponse(
            task_id=task_id,
            status=status,
            created_at=task_status.get("created_at"),
            updated_at=task_status.get("updated_at"),
        )
        
        # 状态描述映射
        status_messages = {
            "PENDING": "任务正在排队中",
            "STARTED": "任务正在执行中",
            "DELIVERED": "任务已投递到 Agent",
            "SUCCESS": "任务执行成功",
            "FAILURE": "任务执行失败",
            "CANCELLED": "任务已取消",
        }
        response.message = status_messages.get(status, f"状态: {status}")
        
        # 进度估算（基于状态）
        progress_map = {
            "PENDING": 0,
            "STARTED": 25,
            "DELIVERED": 50,
            "SUCCESS": 100,
            "FAILURE": 100,
            "CANCELLED": 100,
        }
        response.progress = progress_map.get(status, 0)
        
        # 终态时返回结果
        if status == "SUCCESS":
            response.result = task_status.get("result_data")
            response.completed_at = task_status.get("completed_at")
        elif status == "FAILURE":
            response.error = task_status.get("error_message")
            response.completed_at = task_status.get("completed_at")
        elif status == "CANCELLED":
            response.completed_at = task_status.get("completed_at")
        
        return response
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[Poll] 查询任务状态失败 | task_id={task_id} | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/registry")
def list_registered_agents() -> dict[str, Any]:
    """列出所有注册的 Agent。"""
    registry = get_agent_registry()
    agents = registry.list_all()
    
    return {
        "agents": [agent.to_dict() for agent in agents],
        "count": len(agents),
    }


@router.get("/registry/{agent_id}")
def get_agent_info(agent_id: str) -> dict[str, Any]:
    """获取指定 Agent 的信息。"""
    registry = get_agent_registry()
    agent = registry.get(agent_id)
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    return agent.to_dict()


@router.get("/registry/{agent_id}/health")
def check_agent_health(agent_id: str) -> dict[str, Any]:
    """检查指定 Agent 的健康状态。"""
    registry = get_agent_registry()
    result = registry.check_health(agent_id)
    
    if result.get("error") == "Agent not found":
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    
    return result


@router.post("/registry/reload")
def reload_registry() -> dict[str, Any]:
    """重新加载 Agent 注册表配置。"""
    registry = get_agent_registry()
    registry.reload()
    
    return {
        "success": True,
        "message": "Registry reloaded",
        "agents_count": len(registry.list_all()),
    }
