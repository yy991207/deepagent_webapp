from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.database.mongo_manager import get_mongo_manager
from backend.services.chat_stream_service import ChatStreamService
from backend.utils.snowflake import generate_snowflake_id
from backend.services.checkpoint_service import CheckpointService


router = APIRouter()


# 项目根目录：deepagents-webapp/
BASE_DIR = Path(__file__).resolve().parent.parent.parent


@router.get("/api/chat/threads")
def chat_threads(assistant_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        threads = mongo.list_chat_threads(assistant_id=assistant_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"results": threads}


@router.get("/api/chat/sessions")
def chat_sessions(assistant_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """查询会话列表。

    说明：
    - 当前后端历史落库字段仍为 thread_id，这里将其语义视为 session_id。
    - title 默认取首条 user 消息的缩略；若通过 PATCH 设置了自定义标题，则优先返回自定义标题。
    """
    mongo = get_mongo_manager()
    try:
        sessions = mongo.list_chat_sessions(assistant_id=assistant_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"sessions": sessions, "total": len(sessions)}


@router.post("/api/chat/session")
def create_chat_session(payload: dict[str, Any]) -> dict[str, Any]:
    """创建会话。

    说明：
    - session_id 前端可传入；不传则后端生成雪花 id。
    - 这里仅创建会话元信息（标题可为空），实际消息仍在 /api/chat/stream 时写入。
    """
    mongo = get_mongo_manager()
    assistant_id = str(payload.get("assistant_id") or "agent")
    session_id = str(payload.get("session_id") or generate_snowflake_id())
    title = str(payload.get("title") or "").strip()

    try:
        if title:
            mongo.upsert_chat_session_title(session_id=session_id, assistant_id=assistant_id, title=title)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to create session") from exc

    return {
        "session_id": session_id,
        "assistant_id": assistant_id,
        "title": title,
        "created_at": datetime.utcnow().isoformat(),
    }


@router.patch("/api/chat/session/{session_id}")
def update_chat_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新会话标题。"""
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    mongo = get_mongo_manager()
    assistant_id = str(payload.get("assistant_id") or "agent")
    try:
        mongo.upsert_chat_session_title(session_id=session_id, assistant_id=assistant_id, title=title)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to update session") from exc

    return {"success": True, "session_id": session_id, "title": title}


@router.delete("/api/chat/session/{session_id}")
async def delete_chat_session(session_id: str, assistant_id: str = "agent") -> dict[str, Any]:
    """删除会话及其所有数据。

    删除范围：
    - Mongo: chat_messages(含 tool 消息)、agent_chat_memories、chat_sessions
    - SQLite: checkpoints / writes
    """
    mongo = get_mongo_manager()
    try:
        mongo_deleted = mongo.delete_chat_session(session_id=session_id, assistant_id=assistant_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to delete mongo session") from exc

    try:
        checkpoint_service = CheckpointService()
        ck = await checkpoint_service.delete_session(session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to delete checkpoints") from exc

    return {
        "success": True,
        "session_id": session_id,
        "deleted_counts": {
            **mongo_deleted,
            "checkpoints": ck.deleted_checkpoints,
            "checkpoint_writes": ck.deleted_writes,
        },
    }


@router.get("/api/chat/history")
def chat_history(session_id: str | None = None, thread_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    mongo = get_mongo_manager()
    effective_id = str(session_id or thread_id or "").strip()
    if not effective_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    try:
        items = mongo.get_chat_history(thread_id=effective_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"session_id": effective_id, "messages": items}


@router.get("/api/chat/memory")
def chat_memory(thread_id: str, assistant_id: str = "agent") -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"thread_id": thread_id, "assistant_id": assistant_id, "memory_text": memory_text}


@router.post("/api/chat/stream")
async def chat_stream_sse(payload: dict[str, Any]) -> StreamingResponse:
    text = str(payload.get("text") or "").strip()
    session_id = str(payload.get("session_id") or payload.get("thread_id") or generate_snowflake_id())
    assistant_id = str(payload.get("assistant_id") or "agent")
    file_refs = payload.get("files") or []

    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    service = ChatStreamService(base_dir=BASE_DIR)

    async def event_generator():
        try:
            async for event in service.stream_chat(
                text=text,
                thread_id=session_id,
                assistant_id=assistant_id,
                file_refs=file_refs,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


