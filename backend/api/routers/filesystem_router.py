from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.database.mongo_manager import get_mongo_manager, get_beijing_time
from backend.utils.snowflake import generate_snowflake_id


router = APIRouter()


@router.post("/api/filesystem/write")
def create_filesystem_write(payload: dict[str, Any]) -> dict[str, Any]:
    """写入文件到 MongoDB。

    说明：
    - Agent 调用 write_file 工具时，拦截写入逻辑，改为写入 MongoDB
    - 生成 write_id (雪花ID)，绑定 session_id
    - 不再直接写入文件系统，避免在回复中暴露文件路径
    """
    mongo = get_mongo_manager()

    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    file_path = str(payload.get("file_path") or "").strip()
    content = str(payload.get("content") or "")
    metadata = payload.get("metadata") or {}

    if not file_path:
        raise HTTPException(status_code=400, detail="file_path is required")

    write_id = generate_snowflake_id()
    now = get_beijing_time()

    try:
        mongo.create_filesystem_write(
            write_id=write_id,
            session_id=session_id,
            file_path=file_path,
            content=content,
            metadata=metadata,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed to create write") from exc

    return {
        "write_id": write_id,
        "session_id": session_id,
        "file_path": file_path,
        "status": "success",
        "created_at": now.isoformat(),
    }


@router.get("/api/filesystem/write/{write_id}")
def get_filesystem_write(write_id: str, session_id: str) -> dict[str, Any]:
    """查询单条写入记录。

    说明：
    - 前端点击文档卡片时调用
    - 右侧弹窗显示文档内容
    """
    mongo = get_mongo_manager()

    if not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")

    try:
        write = mongo.get_filesystem_write(write_id=write_id, session_id=session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query write") from exc

    if not write:
        raise HTTPException(status_code=404, detail="write not found")

    return write


@router.get("/api/filesystem/writes")
def list_filesystem_writes(session_id: str, limit: int = 100) -> dict[str, Any]:
    """查询会话的所有写入记录。

    说明：
    - 前端加载聊天历史时一并调用
    - 用于在聊天消息中显示文档卡片
    """
    mongo = get_mongo_manager()

    if not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")

    try:
        writes = mongo.list_filesystem_writes(session_id=session_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed to list writes") from exc

    return {"writes": writes, "total": len(writes)}
