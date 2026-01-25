from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

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


@router.get("/api/filesystem/write/{write_id}/download")
def download_filesystem_write(write_id: str, session_id: str) -> Response:
    """下载文档。

    说明：
    - 前端点击下载按钮时调用
    - 返回文件流，浏览器自动下载
    - 支持文本文件（md, txt, json 等）和二进制文件（pdf, docx, pptx, xlsx 等）
    - 二进制文件内容以 Base64 编码存储，下载时自动解码
    """
    import base64
    import os
    from urllib.parse import quote

    mongo = get_mongo_manager()

    if not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")

    try:
        write = mongo.get_filesystem_write(write_id=write_id, session_id=session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc) or "failed to query write") from exc

    if not write:
        raise HTTPException(status_code=404, detail="write not found")

    content = write.get("content", "")
    binary_content = write.get("binary_content")  # 新增：获取二进制内容
    file_path = write.get("file_path", "")
    metadata = write.get("metadata", {})
    file_type = metadata.get("type", "").lower()

    # 从 file_path 提取文件名
    filename = os.path.basename(file_path) if file_path else "document"

    # 关键逻辑：HTTP Header 默认按 latin-1 编码，中文文件名会触发 UnicodeEncodeError。
    # 这里同时提供 ASCII fallback 的 filename 和 RFC5987 的 filename*，兼容中文。
    ascii_filename = filename.encode("ascii", "ignore").decode("ascii")
    if not ascii_filename:
        ascii_filename = "document"
    encoded_filename = quote(filename, safe="")
    content_disposition = f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"

    # 二进制文件类型映射
    BINARY_TYPES = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "zip": "application/zip",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
    }

    # 文本文件类型映射
    TEXT_TYPES = {
        "md": "text/markdown",
        "txt": "text/plain",
        "json": "application/json",
        "html": "text/html",
        "css": "text/css",
        "js": "application/javascript",
        "py": "text/x-python",
        "xml": "application/xml",
        "csv": "text/csv",
    }

    # 确定 media_type 和是否需要 Base64 解码
    if file_type in BINARY_TYPES:
        media_type = BINARY_TYPES[file_type]
        # 优先使用 binary_content 字段（新的存储方式）
        if binary_content:
            try:
                content_bytes = base64.b64decode(binary_content)
            except Exception:
                content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        else:
            # 兼容旧数据：尝试从 content 字段解码
            try:
                content_bytes = base64.b64decode(content)
            except Exception:
                content_bytes = content.encode("utf-8") if isinstance(content, str) else content
    elif file_type in TEXT_TYPES:
        media_type = TEXT_TYPES[file_type]
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
    else:
        # 默认按文本处理
        media_type = "application/octet-stream"
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content

    # 确保文件名有正确的扩展名
    if file_type and not filename.endswith(f".{file_type}"):
        filename = f"{filename}.{file_type}"
        ascii_filename = filename.encode("ascii", "ignore").decode("ascii") or "document"
        encoded_filename = quote(filename, safe="")
        content_disposition = f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"

    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition,
            "Content-Type": media_type,
        }
    )
