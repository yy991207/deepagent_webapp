from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.services.creative_agent_service import CreativeAppError
from backend.services.creative_state_machine_service import CreativeStateMachineService
from backend.utils.snowflake import generate_snowflake_id


router = APIRouter()
logger = logging.getLogger(__name__)


# 项目根目录：deepagents-webapp/
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent


def _service() -> CreativeStateMachineService:
    return CreativeStateMachineService(workspace_root=BASE_DIR)


def _raise_creative_http_error(exc: Exception) -> None:
    if isinstance(exc, CreativeAppError):
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
    raise HTTPException(status_code=500, detail={"code": "CREATIVE_INTERNAL_ERROR", "message": str(exc)}) from exc


def _run_start_background(run_id: str) -> None:
    try:
        _service().process_start_run(run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("creative start background failed | run_id=%s", run_id)
        try:
            _service().mark_async_failure(run_id=run_id, stage="start", error_message=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("creative start failure fallback failed | run_id=%s", run_id)


def _run_pre_agent_background(run_id: str, action: str, feedback: str) -> None:
    try:
        _service().pre_agent_decision(run_id=run_id, action=action, feedback=feedback)
    except Exception as exc:  # noqa: BLE001
        logger.exception("creative pre_agent background failed | run_id=%s", run_id)
        try:
            _service().mark_async_failure(run_id=run_id, stage="pre_agent", error_message=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("creative pre_agent failure fallback failed | run_id=%s", run_id)


def _run_requirement_background(run_id: str, action: str, feedback: str) -> None:
    try:
        _service().requirement_decision(run_id=run_id, action=action, feedback=feedback)
    except Exception as exc:  # noqa: BLE001
        logger.exception("creative requirement background failed | run_id=%s", run_id)
        try:
            _service().mark_async_failure(run_id=run_id, stage="requirement", error_message=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("creative requirement failure fallback failed | run_id=%s", run_id)


def _run_draft_background(run_id: str, action: str, feedback: str) -> None:
    try:
        _service().draft_decision(run_id=run_id, action=action, feedback=feedback)
    except Exception as exc:  # noqa: BLE001
        logger.exception("creative draft background failed | run_id=%s", run_id)
        try:
            _service().mark_async_failure(run_id=run_id, stage="draft", error_message=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("creative draft failure fallback failed | run_id=%s", run_id)


def _run_round_background(run_id: str, action: str) -> None:
    try:
        _service().round_decision(run_id=run_id, action=action)
    except Exception as exc:  # noqa: BLE001
        logger.exception("creative round background failed | run_id=%s", run_id)
        try:
            _service().mark_async_failure(run_id=run_id, stage="round", error_message=str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("creative round failure fallback failed | run_id=%s", run_id)


@router.post("/api/creative/run/start")
def creative_run_start(payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    session_id = str(payload.get("session_id") or payload.get("thread_id") or generate_snowflake_id())
    assistant_id = str(payload.get("assistant_id") or "agent")
    files = payload.get("files") or []
    checklist = payload.get("checklist") or []

    try:
        run = _service().start_run(
            session_id=session_id,
            assistant_id=assistant_id,
            user_prompt=text,
            file_refs=[str(x) for x in files] if isinstance(files, list) else [],
            checklist=[str(x) for x in checklist] if isinstance(checklist, list) else None,
        )
        # 关键链路改为异步后台执行，先立即返回 run，避免接口长时间 Pending。
        background_tasks.add_task(_run_start_background, str(run.get("run_id") or ""))
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.post("/api/creative/run/{run_id}/pre-agent/decision")
def creative_pre_agent_decision(run_id: str, payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    feedback = str(payload.get("feedback") or "")
    try:
        run = _service().submit_pre_agent_decision(run_id=run_id, action=action, feedback=feedback)
        # 先返回 processing 状态，再由后台线程推进到下一状态。
        background_tasks.add_task(_run_pre_agent_background, run_id, action, feedback)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.post("/api/creative/run/{run_id}/requirement/decision")
def creative_requirement_decision(run_id: str, payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    feedback = str(payload.get("feedback") or "")
    try:
        run = _service().submit_requirement_decision(run_id=run_id, action=action, feedback=feedback)
        # 先返回 processing 状态，再由后台线程推进到下一状态。
        background_tasks.add_task(_run_requirement_background, run_id, action, feedback)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.post("/api/creative/run/{run_id}/draft/decision")
def creative_draft_decision(run_id: str, payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    feedback = str(payload.get("feedback") or "")
    try:
        run = _service().submit_draft_decision(run_id=run_id, action=action, feedback=feedback)
        # 先返回 processing 状态，再由后台线程推进到下一状态。
        background_tasks.add_task(_run_draft_background, run_id, action, feedback)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.post("/api/creative/run/{run_id}/round/decision")
def creative_round_decision(run_id: str, payload: dict[str, Any], background_tasks: BackgroundTasks) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().lower()
    try:
        run = _service().submit_round_decision(run_id=run_id, action=action)
        # 先返回 processing 状态，再由后台线程推进到下一状态。
        background_tasks.add_task(_run_round_background, run_id, action)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.post("/api/creative/run/{run_id}/cancel")
def creative_cancel_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    reason = str(payload.get("reason") or "").strip()
    try:
        run = _service().cancel_run(run_id=run_id, reason=reason)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.post("/api/creative/run/cancel-active")
def creative_cancel_active_run(payload: dict[str, Any]) -> dict[str, Any]:
    session_id = str(payload.get("session_id") or payload.get("thread_id") or "").strip()
    assistant_id = str(payload.get("assistant_id") or "agent")
    reason = str(payload.get("reason") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail={"code": "CREATIVE_SESSION_REQUIRED", "message": "session_id 不能为空"})
    try:
        run = _service().cancel_active_run(session_id=session_id, assistant_id=assistant_id, reason=reason)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.get("/api/creative/run/{run_id}")
def creative_get_run(run_id: str) -> dict[str, Any]:
    try:
        run = _service().get_run(run_id=run_id)
        return {"success": True, "run": run}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)


@router.get("/api/creative/runs")
def creative_list_runs(
    session_id: str,
    assistant_id: str = "agent",
    active_only: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    try:
        runs = _service().list_runs(
            session_id=str(session_id),
            assistant_id=str(assistant_id),
            active_only=bool(active_only),
            limit=int(limit),
        )
        return {"success": True, "results": runs, "total": len(runs)}
    except Exception as exc:  # noqa: BLE001
        _raise_creative_http_error(exc)
