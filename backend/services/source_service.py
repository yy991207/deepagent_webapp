from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from backend.database.mongo_manager import MongoDbManager, get_mongo_manager

logger = logging.getLogger(__name__)


class SourceService:
    """来源文件服务：负责上传文件的路径清洗与入库"""

    def __init__(self, mongo: MongoDbManager | None = None) -> None:
        self._mongo = mongo or get_mongo_manager()

    async def upload_sources(
        self,
        files: list[UploadFile],
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """上传文件到指定位置
        
        Args:
            files: 要上传的文件列表
            parent_id: 可选的父文件夹 ID，None 表示根目录
        
        Returns:
            包含上传结果的字典
        """
        # 关键逻辑：这里只做"清洗文件名 + 读文件内容 + 入库"，路由层只负责参数接收
        saved: list[dict[str, Any]] = []

        for f in files:
            raw_name = (f.filename or "").strip() or "upload.bin"
            content = await f.read()

            # 关键逻辑：把前端传来的路径做一次安全清洗，避免出现 .. / 绝对路径等风险
            rel_path = raw_name.replace("\\", "/").lstrip("/")
            rel_path = "_".join([p for p in rel_path.split("/") if p not in ("", ".", "..")])
            if not rel_path:
                rel_path = "upload.bin"

            stored = self._mongo.store_file(
                filename=Path(rel_path).name,
                rel_path=rel_path,
                content_bytes=content,
                parent_id=parent_id,
            )

            saved.append(
                {
                    "id": stored.id,
                    "sha256": stored.sha256,
                    "rel_path": stored.rel_path,
                    "filename": stored.filename,
                    "size": stored.size,
                    "parent_id": parent_id,
                    "item_type": "file",
                }
            )

        return {"count": len(saved), "files": saved}
