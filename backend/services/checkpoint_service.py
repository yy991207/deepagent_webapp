from __future__ import annotations

import os
from dataclasses import dataclass

import aiosqlite

from backend.services.checkpointer_provider import get_db_path


@dataclass(frozen=True)
class CheckpointCleanupResult:
    deleted_checkpoints: int
    deleted_writes: int


class CheckpointService:
    """Checkpoint 管理服务。

    说明：
    - LangGraph 的 checkpoint 落库在用户目录 ~/.deepagents/sessions.db
    - 表结构为 checkpoints / writes，按 thread_id 进行隔离
    - 这里约定：thread_id 字段承载 session_id 的语义
    """

    def __init__(self, *, keep_last: int | None = None) -> None:
        # 关键配置从环境变量读取，避免硬编码
        if keep_last is None:
            keep_last = int(os.getenv("DEEPAGENTS_CHECKPOINT_KEEP_LAST", "20") or "20")
        self._keep_last = max(int(keep_last), 0)

    @property
    def keep_last(self) -> int:
        return self._keep_last

    async def _table_exists(self, db: aiosqlite.Connection, table_name: str) -> bool:
        cursor = await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        )
        row = await cursor.fetchone()
        return bool(row)

    async def cleanup_keep_last(self, *, session_id: str) -> CheckpointCleanupResult:
        """只保留最近 N 条 checkpoint。

        注意：
        - 这里按 checkpoint_id 的字典序倒序保留（LangGraph 的 id 是时间序相关 UUID，通常可满足近似“最近”）
        - 该清理用于控制单会话 checkpoint 无上限增长，避免接口首包延迟严重
        """

        if not session_id or self._keep_last <= 0:
            return CheckpointCleanupResult(deleted_checkpoints=0, deleted_writes=0)

        db_path = get_db_path()
        deleted_checkpoints = 0
        deleted_writes = 0

        async with aiosqlite.connect(str(db_path)) as db:
            # 关键逻辑：有些环境会存在“数据库文件已创建，但 checkpoint 表尚未初始化”的情况。
            # 这里直接返回 0，避免删除会话时抛 no such table。
            has_checkpoints = await self._table_exists(db, "checkpoints")
            if not has_checkpoints:
                return CheckpointCleanupResult(deleted_checkpoints=0, deleted_writes=0)

            # 找到需要删除的旧 checkpoint_id 列表
            cursor = await db.execute(
                """
                SELECT checkpoint_id
                FROM checkpoints
                WHERE thread_id = ?
                ORDER BY checkpoint_id DESC
                LIMIT -1 OFFSET ?
                """,
                (session_id, self._keep_last),
            )
            rows = await cursor.fetchall()
            old_ids = [r[0] for r in rows if r and r[0]]

            if not old_ids:
                return CheckpointCleanupResult(deleted_checkpoints=0, deleted_writes=0)

            placeholders = ",".join(["?"] * len(old_ids))

            # 先删 writes，再删 checkpoints，避免残留
            has_writes = await self._table_exists(db, "writes")
            if has_writes:
                cur_w = await db.execute(
                    f"DELETE FROM writes WHERE thread_id = ? AND checkpoint_id IN ({placeholders})",
                    (session_id, *old_ids),
                )
                deleted_writes = int(cur_w.rowcount or 0)

            cur_c = await db.execute(
                f"DELETE FROM checkpoints WHERE thread_id = ? AND checkpoint_id IN ({placeholders})",
                (session_id, *old_ids),
            )
            deleted_checkpoints = int(cur_c.rowcount or 0)

            await db.commit()

        return CheckpointCleanupResult(deleted_checkpoints=deleted_checkpoints, deleted_writes=deleted_writes)

    async def delete_session(self, *, session_id: str) -> CheckpointCleanupResult:
        """删除某个 session 的所有 checkpoint 数据。"""

        if not session_id:
            return CheckpointCleanupResult(deleted_checkpoints=0, deleted_writes=0)

        db_path = get_db_path()
        async with aiosqlite.connect(str(db_path)) as db:
            # 关键逻辑：兼容尚未初始化 checkpoint 表的数据库文件。
            # 例如新环境首次删除会话时，db 可能存在但表不存在。
            has_writes = await self._table_exists(db, "writes")
            has_checkpoints = await self._table_exists(db, "checkpoints")

            deleted_writes = 0
            deleted_checkpoints = 0

            if has_writes:
                cur_w = await db.execute("DELETE FROM writes WHERE thread_id = ?", (session_id,))
                deleted_writes = int(cur_w.rowcount or 0)
            if has_checkpoints:
                cur_c = await db.execute("DELETE FROM checkpoints WHERE thread_id = ?", (session_id,))
                deleted_checkpoints = int(cur_c.rowcount or 0)
            await db.commit()

        return CheckpointCleanupResult(
            deleted_checkpoints=deleted_checkpoints,
            deleted_writes=deleted_writes,
        )
