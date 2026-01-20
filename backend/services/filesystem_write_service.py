from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.database.mongo_manager import get_mongo_manager
from backend.utils.snowflake import generate_snowflake_id


logger = logging.getLogger(__name__)


class FilesystemWriteService:
    """文件系统写入服务。
    
    说明：
    - 拦截 Agent 的 write_file 工具调用
    - 改为写入 MongoDB，不直接写文件系统
    - 返回 write_id 而不是文件路径
    """

    def __init__(self, *, session_id: str) -> None:
        self._session_id = session_id
        self._mongo = get_mongo_manager()

    def create_write_file_tool(self):
        """创建自定义的 write_file 工具函数。"""

        def write_file(file_path: str, content: str, description: str = "") -> dict[str, Any]:
            """将内容写入文件（实际写入 MongoDB）。

            说明：
            - 这个工具会拦截原有的文件写入逻辑
            - 内容写入 MongoDB 而不是文件系统
            - 返回 write_id 供前端查询和展示

            参数：
            - file_path: 文件路径（用于标识，不实际写入）
            - content: 文件内容
            - description: 文件描述（可选）

            返回：
            - write_id: 写入记录的唯一标识
            - status: 写入状态
            """
            try:
                write_id = generate_snowflake_id()
                
                filename = Path(file_path).name
                file_type = Path(file_path).suffix.lstrip(".") or "txt"
                
                metadata = {
                    "title": description or filename,
                    "type": file_type,
                    "description": description,
                }

                self._mongo.create_filesystem_write(
                    write_id=write_id,
                    session_id=self._session_id,
                    file_path=file_path,
                    content=content,
                    metadata=metadata,
                )

                logger.info(f"文件已写入 MongoDB | write_id={write_id} | session_id={self._session_id} | path={file_path}")

                return {
                    "write_id": write_id,
                    "file_path": file_path,
                    "title": metadata["title"],
                    "type": file_type,
                    "size": len(content),
                    "status": "success",
                    "message": f"文档已保存（{filename}）",
                }

            except Exception as e:
                logger.error(f"写入文件失败 | session_id={self._session_id} | error={e}")
                return {
                    "status": "error",
                    "message": f"写入失败: {str(e)}",
                }

        return write_file
