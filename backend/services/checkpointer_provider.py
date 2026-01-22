"""LangGraph checkpointer 提供方。

说明：
- 承接原 deepagents_cli.sessions 的职责。
- checkpointer 数据落在相对路径 .deepagents/sessions.db，避免绝对路径导致部署问题。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def get_db_path() -> Path:
    """获取 checkpoint 数据库路径。"""

    db_path = Path(".deepagents") / "sessions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


@asynccontextmanager
async def get_checkpointer():
    """异步获取 SQLite checkpointer。"""

    db_path = get_db_path()
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver
