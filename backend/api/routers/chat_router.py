from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.database.mongo_manager import get_mongo_manager
from backend.services.chat_stream_service import ChatStreamService


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


@router.get("/api/chat/history")
def chat_history(thread_id: str, limit: int = 200) -> dict[str, Any]:
    mongo = get_mongo_manager()
    try:
        items = mongo.get_chat_history(thread_id=thread_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query mongo") from exc
    return {"thread_id": thread_id, "messages": items}


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
    thread_id = str(payload.get("thread_id") or f"web-{uuid.uuid4().hex[:8]}")
    assistant_id = str(payload.get("assistant_id") or "agent")
    file_refs = payload.get("files") or []

    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    service = ChatStreamService(base_dir=BASE_DIR)

    async def event_generator():
        try:
            async for event in service.stream_chat(
                text=text,
                thread_id=thread_id,
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


