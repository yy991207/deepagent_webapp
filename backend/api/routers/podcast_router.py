from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.middleware.podcast_middleware import build_podcast_middleware


router = APIRouter()


# 项目根目录：deepagents-webapp/
BASE_DIR = Path(__file__).resolve().parent.parent.parent


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
        svc.start_generation_async(run_id=run.id)
        return {"run_id": run.id, "status": run.status, "created_at": run.created_at}
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
