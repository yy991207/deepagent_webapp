from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.database.mongo_manager import get_mongo_manager
from backend.services.chat_stream_service import ChatStreamService
from backend.services.memory_summary_service import MemorySummaryService
from backend.utils.snowflake import generate_snowflake_id
from backend.services.checkpoint_service import CheckpointService
from backend.services.session_cancel_service import get_session_cancel_service


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


@router.post("/api/chat/session/{session_id}/cancel")
def cancel_chat_session(session_id: str) -> dict[str, Any]:
    """取消会话的流式请求。
    
    标记会话为已取消，正在进行的 stream_chat 会检测到并中断。
    """
    cancel_service = get_session_cancel_service()
    cancel_service.cancel(session_id)
    return {"success": True, "session_id": session_id, "message": "会话已标记为取消"}


@router.delete("/api/chat/session/{session_id}")
async def delete_chat_session(session_id: str, assistant_id: str = "agent") -> dict[str, Any]:
    """删除会话及其所有数据。

    删除范围：
    - Mongo: chat_messages(含 tool 消息)、agent_chat_memories、chat_sessions
    - SQLite: checkpoints / writes
    
    删除前会先取消正在进行的流式请求。
    """
    # 先取消正在进行的流式请求
    cancel_service = get_session_cancel_service()
    cancel_service.cancel(session_id)
    
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
    
    # 删除完成后清除取消标记
    cancel_service.clear(session_id)

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
        writes = mongo.list_filesystem_writes(session_id=effective_id, limit=100)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"session_id": effective_id, "messages": items, "writes": writes}


@router.get("/api/chat/memory")
def chat_memory(thread_id: str, assistant_id: str = "agent") -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"thread_id": thread_id, "assistant_id": assistant_id, "memory_text": memory_text}


@router.get("/api/chat/memory/stats")
def chat_memory_stats(thread_id: str, assistant_id: str = "agent") -> dict[str, Any]:
    """查询 chat memory 的字数统计。

    返回：
    - memory_text_chars: 当前字数
    - memory_limit: 阈值（默认 5000）
    - ratio: 0~1
    - reached_limit: 是否达到阈值
    """
    mongo = get_mongo_manager()

    # 阈值配置放到 env，避免硬编码
    max_chars = int(os.getenv("DEEPAGENTS_CHAT_MEMORY_MAX_CHARS") or "5000")

    try:
        memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc

    memory_chars = len(str(memory_text or ""))
    ratio = min(memory_chars / float(max_chars), 1.0) if max_chars > 0 else 0.0
    return {
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "memory_text_chars": memory_chars,
        "memory_limit": max_chars,
        "ratio": ratio,
        "reached_limit": bool(max_chars > 0 and memory_chars >= max_chars),
    }


@router.post("/api/chat/memory/summary")
async def chat_memory_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """当 chat memory 达到阈值时，用 LLM 做一次压缩总结并覆盖写回 memory_text。

    说明：
    - 总结完成后会直接覆盖写回 memory_text
    - 同时返回总结后的字数/占比，供前端刷新圆环
    """
    thread_id = str(payload.get("thread_id") or payload.get("session_id") or "").strip()
    assistant_id = str(payload.get("assistant_id") or "agent")
    force = bool(payload.get("force") or False)

    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    max_chars = int(os.getenv("DEEPAGENTS_CHAT_MEMORY_MAX_CHARS") or "5000")
    summary_max_chars = int(os.getenv("DEEPAGENTS_CHAT_MEMORY_SUMMARY_MAX_CHARS") or "500")
    lock_ttl_seconds = int(os.getenv("DEEPAGENTS_CHAT_MEMORY_SUMMARY_LOCK_TTL_SECONDS") or "120")

    service = MemorySummaryService(
        thread_id=thread_id,
        assistant_id=assistant_id,
        max_memory_chars=max_chars,
        summary_max_chars=summary_max_chars,
        lock_ttl_seconds=lock_ttl_seconds,
    )

    result = await service.summarize_if_needed(force=force)
    # 统一补充 thread_id/assistant_id，方便前端处理
    return {"thread_id": thread_id, "assistant_id": assistant_id, **result}


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
                # 每条 SSE 事件都带上 session_id，便于前端过滤旧会话事件
                event["session_id"] = session_id
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc), 'session_id': session_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


