from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket

from backend.database.mongo_manager import get_mongo_manager
from backend.services.chat_ws_handler import ChatWebSocketHandler


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


@router.websocket("/ws/chat")
async def chat_socket(ws: WebSocket) -> None:
    handler = ChatWebSocketHandler(base_dir=BASE_DIR)
    await handler.handle(ws)
