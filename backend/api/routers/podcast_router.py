from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.middleware.podcast_middleware import build_podcast_middleware


router = APIRouter()
logger = logging.getLogger(__name__)


# 项目根目录：deepagents-webapp/
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# ==============================================================================
# Pydantic 模型
# ==============================================================================
class CallbackPayload(BaseModel):
    """Agent Service 回调请求体"""
    task_id: str
    run_id: str
    status: str  # SUCCESS / FAILURE / CANCELLED
    result_data: dict[str, Any] | None = None
    error_message: str | None = None
    completed_at: str | None = None


# ==============================================================================
# Celery 任务导入（延迟导入避免循环依赖）
# ==============================================================================
def _get_celery_task():
    """延迟导入 Celery 投递任务。"""
    from backend.celery_scheduler.tasks.podcast_tasks import deliver_podcast_task
    return deliver_podcast_task


def _get_callback_task():
    """延迟导入 Celery 回调处理任务。"""
    from backend.celery_scheduler.tasks.podcast_tasks import process_callback_result
    return process_callback_result


def _use_celery() -> bool:
    """判断是否使用 Celery 调度。
    
    通过环境变量 USE_CELERY=1 或 USE_CELERY=true 启用。
    默认不启用，保持向后兼容（使用 threading.Thread）。
    """
    val = os.environ.get("USE_CELERY", "").lower()
    return val in ("1", "true", "yes", "on")


# ==============================================================================
# API 端点
# ==============================================================================
@router.post("/api/podcast/bootstrap")
def podcast_bootstrap_profiles() -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        result = svc.bootstrap_profiles()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "bootstrap failed") from exc
    return result


@router.get("/api/podcast/speaker-profiles")
def podcast_list_speaker_profiles() -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        svc.bootstrap_profiles()
        profiles = svc.list_speaker_profiles()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"results": profiles}


@router.get("/api/podcast/episode-profiles")
def podcast_list_episode_profiles() -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        svc.bootstrap_profiles()
        profiles = svc.list_episode_profiles()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"results": profiles}


@router.post("/api/podcast/generate")
def podcast_generate(payload: dict[str, Any]) -> dict[str, Any]:
    """生成播客。
    
    支持两种执行模式：
    1. Celery 投递模式（推荐）：通过 Celery 投递到 Agent Service，不占用 Worker
    2. 线程模式（默认）：通过 threading.Thread 本地执行，向后兼容
    
    通过环境变量 USE_CELERY=1 启用 Celery 模式。
    
    Celery 模式架构：
    API → Celery Worker（快速投递）→ Agent Service（异步执行）→ Callback
    """
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
        run = svc.create_run(
            episode_profile=episode_profile,
            speaker_profile=speaker_profile,
            source_ids=source_ids,
            episode_name=episode_name,
            briefing_suffix=briefing_suffix,
        )
        
        # 根据配置选择执行模式
        if _use_celery():
            # Celery 投递模式：快速投递到 Agent Service
            deliver_task = _get_celery_task()
            celery_result = deliver_task.delay(run.id)
            return {
                "run_id": run.id,
                "status": run.status,
                "created_at": run.created_at,
                "celery_task_id": celery_result.id,
                "mode": "celery_delivery",
            }
        else:
            # 线程模式：本地 threading.Thread 执行（向后兼容）
            svc.start_generation_async(run_id=run.id)
            return {
                "run_id": run.id,
                "status": run.status,
                "created_at": run.created_at,
                "mode": "thread",
            }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "generate failed") from exc


@router.post("/api/podcast/runs")
def podcast_create_run(payload: dict[str, Any]) -> dict[str, Any]:
    """创建一条播客执行记录（不触发生成）。"""
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
        run = svc.create_run(
            episode_profile=episode_profile,
            speaker_profile=speaker_profile,
            source_ids=source_ids,
            episode_name=episode_name,
            briefing_suffix=briefing_suffix,
        )
        return {"run_id": run.id, "status": run.status, "created_at": run.created_at}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "create run failed") from exc


@router.post("/api/podcast/runs/{run_id}/start")
def podcast_start_run(run_id: str) -> dict[str, Any]:
    """启动已创建的播客生成任务。
    
    此接口用于启动之前通过 POST /api/podcast/runs 创建但未执行的任务。
    支持 Celery 投递和线程两种执行模式。
    """
    svc = build_podcast_middleware()
    try:
        # 验证 run 存在
        detail = svc.get_run_detail(run_id=run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="run not found")
        
        # 检查状态
        status = detail.get("status", "")
        if status in ("running", "done"):
            raise HTTPException(
                status_code=400, 
                detail=f"run is already {status}, cannot restart"
            )
        
        # 根据配置选择执行模式
        if _use_celery():
            deliver_task = _get_celery_task()
            celery_result = deliver_task.delay(run_id)
            return {
                "run_id": run_id,
                "status": "submitted",
                "celery_task_id": celery_result.id,
                "mode": "celery_delivery",
            }
        else:
            svc.start_generation_async(run_id=run_id)
            return {
                "run_id": run_id,
                "status": "submitted",
                "mode": "thread",
            }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "start failed") from exc


@router.get("/api/podcast/runs")
def podcast_list_runs(limit: int = 50, skip: int = 0) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        items = svc.list_runs(limit=limit, skip=skip)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"results": items}


@router.get("/api/podcast/runs/{run_id}")
def podcast_run_detail(run_id: str) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        detail = svc.get_run_detail(run_id=run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="not found")
        result = svc.get_result(run_id=run_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return {"run": detail, "result": result}


@router.delete("/api/podcast/runs/{run_id}")
def podcast_delete_run(run_id: str) -> dict[str, Any]:
    """删除一条播客运行记录。

    说明：
    - 删除 runs 集合中的 run 记录
    - 同时清理 results 集合中对应的结果数据
    - 不主动删除本地音频文件
    """

    svc = build_podcast_middleware()
    try:
        deleted = svc.delete_run(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="not found")

    return {"ok": True}


@router.get("/api/podcast/results/{run_id}")
def podcast_result_detail(run_id: str) -> dict[str, Any]:
    svc = build_podcast_middleware()
    try:
        result = svc.get_result(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="not found")
    return result


@router.get("/api/podcast/runs/{run_id}/audio")
def podcast_run_audio(run_id: str) -> FileResponse:
    svc = build_podcast_middleware()
    try:
        result = svc.get_result(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    if not result:
        raise HTTPException(status_code=404, detail="not found")

    audio_file_path = str(result.get("audio_file_path") or "").strip()
    if not audio_file_path:
        raise HTTPException(status_code=404, detail="audio not ready")

    p = Path(audio_file_path)
    if not p.is_absolute():
        p = BASE_DIR / p

    data_dir = Path(os.environ.get("DEEPAGENTS_DATA_DIR") or (BASE_DIR / "data")).resolve()
    podcasts_dir = (data_dir / "podcasts").resolve()

    try:
        resolved = p.resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid audio path")

    if podcasts_dir not in resolved.parents and resolved != podcasts_dir:
        raise HTTPException(status_code=403, detail="forbidden")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="audio not found")

    return FileResponse(path=str(resolved), media_type="audio/mpeg", filename=resolved.name)


# ==============================================================================
# Callback 接口（Agent Service 回调）
# ==============================================================================
@router.post("/api/podcast/callback")
def podcast_callback(payload: CallbackPayload) -> dict[str, Any]:
    """接收 Agent Service 的回调通知。
    
    此接口由 Podcast Agent Service 在任务完成后调用，
    用于通知任务执行结果并更新数据库状态。
    
    回调流程：
    1. Agent Service 执行完成
    2. Agent Service 调用此接口
    3. 此接口异步处理结果（通过 Celery 任务）
    4. 更新 MongoDB 中的任务状态和结果
    """
    logger.info(
        f"[Callback] 收到回调 | task_id={payload.task_id} | "
        f"run_id={payload.run_id} | status={payload.status}"
    )
    
    try:
        # 使用 Celery 任务异步处理回调结果
        if _use_celery():
            process_callback = _get_callback_task()
            process_callback.delay(
                task_id=payload.task_id,
                run_id=payload.run_id,
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
            # 非 Celery 模式：直接同步处理
            # 这种情况通常不会发生，因为没有 Celery 就不会有 Agent Service 回调
            logger.warning("[Callback] Celery 未启用，直接返回")
            return {
                "success": True,
                "message": "回调已接收（Celery 未启用）",
                "task_id": payload.task_id,
            }
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[Callback] 处理失败 | task_id={payload.task_id} | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc) or "callback failed") from exc


# ==============================================================================
# Celery 任务状态查询接口
# ==============================================================================
@router.get("/api/podcast/celery/task/{celery_task_id}")
def podcast_celery_task_status(celery_task_id: str) -> dict[str, Any]:
    """查询 Celery 任务状态。
    
    此接口用于查询通过 Celery 提交的投递任务的状态。
    注意：这是 Celery 的任务 ID，不是 podcast run_id。
    
    状态说明：
    - PENDING: 任务等待执行
    - STARTED: 任务开始执行
    - DELIVERED: 已成功投递到 Agent Service
    - DELIVERY_FAILED: 投递失败
    - SUCCESS: 任务完成（包括投递和回调处理）
    - FAILURE: 任务失败
    """
    if not _use_celery():
        raise HTTPException(
            status_code=400, 
            detail="Celery mode is not enabled. Set USE_CELERY=1 to enable."
        )
    
    try:
        from backend.celery_scheduler.celery_app import celery_app
        result = celery_app.AsyncResult(celery_task_id)
        
        response = {
            "celery_task_id": celery_task_id,
            "status": result.status,
            "ready": result.ready(),
            "successful": result.successful() if result.ready() else None,
        }
        
        # 如果任务完成，返回结果
        if result.ready():
            if result.successful():
                response["result"] = result.result
            else:
                # 任务失败
                response["error"] = str(result.result) if result.result else "Unknown error"
        
        return response
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc


@router.get("/api/podcast/task/{task_id}/status")
def podcast_task_status_from_mongo(task_id: str) -> dict[str, Any]:
    """从 MongoDB 查询任务状态。
    
    此接口用于查询存储在 MongoDB 中的任务状态，
    适用于需要持久化状态查询的场景。
    """
    if not _use_celery():
        raise HTTPException(
            status_code=400, 
            detail="Celery mode is not enabled. Set USE_CELERY=1 to enable."
        )
    
    try:
        from backend.celery_scheduler.config import CeleryConfig
        from backend.celery_scheduler.storage.task_storage import TaskStorage
        
        config = CeleryConfig()
        storage = TaskStorage(
            mongo_uri=config.mongodb_uri,
            database=config.mongodb_database,
        )
        
        task_status = storage.get_task_status(task_id=task_id)
        if task_status is None:
            raise HTTPException(status_code=404, detail="task not found")

        return task_status
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc


@router.post("/api/podcast/speaker-profiles")
def podcast_create_speaker_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """创建说话人配置"""
    svc = build_podcast_middleware()
    try:
        result = svc.create_speaker_profile(data=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return result


@router.put("/api/podcast/speaker-profiles/{profile_id}")
def podcast_update_speaker_profile(profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新说话人配置"""
    svc = build_podcast_middleware()
    try:
        result = svc.update_speaker_profile(profile_id=profile_id, data=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return result


@router.delete("/api/podcast/speaker-profiles/{profile_id}")
def podcast_delete_speaker_profile(profile_id: str) -> dict[str, Any]:
    """删除说话人配置"""
    svc = build_podcast_middleware()
    try:
        success = svc.delete_speaker_profile(profile_id=profile_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    if not success:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


@router.post("/api/podcast/episode-profiles")
def podcast_create_episode_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """创建节目配置"""
    svc = build_podcast_middleware()
    try:
        result = svc.create_episode_profile(data=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return result


@router.put("/api/podcast/episode-profiles/{profile_id}")
def podcast_update_episode_profile(profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新节目配置"""
    svc = build_podcast_middleware()
    try:
        result = svc.update_episode_profile(profile_id=profile_id, data=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    return result


@router.delete("/api/podcast/episode-profiles/{profile_id}")
def podcast_delete_episode_profile(profile_id: str) -> dict[str, Any]:
    """删除节目配置"""
    svc = build_podcast_middleware()
    try:
        success = svc.delete_episode_profile(profile_id=profile_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed") from exc
    if not success:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}
