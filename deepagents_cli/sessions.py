"""webapp 内置的会话与 checkpoint 管理。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def get_db_path() -> Path:
    """获取 checkpoint 数据库路径，统一落在用户目录。"""
    db_path = Path(".deepagents") / "sessions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@asynccontextmanager
async def get_checkpointer():
    """异步获取 SQLite checkpointer。"""
    db_path = get_db_path()
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver
