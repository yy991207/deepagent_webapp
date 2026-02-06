"""
流式会话管理器

将 stream_chat() 的执行从 SSE 连接中解耦：
- 后台 asyncio.Task 运行 stream_chat()，事件缓存到内存 buffer
- SSE 连接只负责从 buffer 消费（subscribe）
- 客户端断连不影响后台任务，重连后续读 buffer 即可恢复

适用于单进程部署。如需多进程支持，可将 buffer 替换为 Redis Stream。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# 完成后保留 buffer 的时间（秒），供断线重连
_BUFFER_TTL_SECONDS = 300  # 5 分钟


@dataclass
class StreamSession:
    """单个流式会话的运行时状态。"""

    session_id: str
    event_buffer: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"  # running | done | error
    task: asyncio.Task | None = None
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    # 用于通知 subscriber 有新事件
    _notify: asyncio.Event = field(default_factory=asyncio.Event)

    def append_event(self, event: dict[str, Any]) -> None:
        self.event_buffer.append(event)
        self._notify.set()

    def mark_done(self, status: str = "done") -> None:
        self.status = status
        self.finished_at = time.monotonic()
        # 最后通知一次，让所有 subscriber 退出
        self._notify.set()

    @property
    def event_count(self) -> int:
        return len(self.event_buffer)

    @property
    def is_active(self) -> bool:
        return self.status == "running"


class StreamSessionManager:
    """流式会话管理器（单例）。"""

    _instance: StreamSessionManager | None = None

    def __new__(cls) -> StreamSessionManager:
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._sessions: dict[str, StreamSession] = {}
            inst._cleanup_task: asyncio.Task | None = None
            cls._instance = inst
        return cls._instance

    # ------------------------------------------------------------------
    # 核心 API
    # ------------------------------------------------------------------

    def start(
        self,
        session_id: str,
        async_gen: AsyncGenerator[dict[str, Any], None],
    ) -> StreamSession:
        """启动后台任务消费 async_gen，事件写入 buffer。

        如果该 session 已有正在运行的任务，先取消旧任务。
        """
        old = self._sessions.get(session_id)
        if old and old.is_active and old.task and not old.task.done():
            old.task.cancel()
            logger.info("cancelled existing stream task | session_id=%s", session_id)

        session = StreamSession(session_id=session_id)
        session.task = asyncio.get_event_loop().create_task(
            self._run(session, async_gen),
            name=f"stream-{session_id}",
        )
        self._sessions[session_id] = session
        self._ensure_cleanup_loop()
        logger.info("stream session started | session_id=%s", session_id)
        return session

    def get(self, session_id: str) -> StreamSession | None:
        return self._sessions.get(session_id)

    async def subscribe(
        self,
        session_id: str,
        from_index: int = 0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """从 buffer[from_index:] 开始消费，实时等待新事件。

        当 session 完成 / 不存在时，yield 完已有事件后退出。
        """
        session = self._sessions.get(session_id)
        if session is None:
            return

        idx = max(from_index, 0)
        while True:
            # replay 已有但尚未消费的事件
            while idx < session.event_count:
                yield session.event_buffer[idx]
                idx += 1

            # 如果已完成，退出
            if not session.is_active:
                break

            # 等待新事件通知
            session._notify.clear()
            # 双重检查：clear 之后可能已有新事件
            if idx < session.event_count:
                continue
            if not session.is_active:
                # 在 clear 和检查之间可能已经 mark_done
                while idx < session.event_count:
                    yield session.event_buffer[idx]
                    idx += 1
                break
            try:
                await asyncio.wait_for(session._notify.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                # 超时只是心跳检查，继续循环
                if not session.is_active:
                    while idx < session.event_count:
                        yield session.event_buffer[idx]
                        idx += 1
                    break

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _run(
        self,
        session: StreamSession,
        gen: AsyncGenerator[dict[str, Any], None],
    ) -> None:
        """后台任务：消费 stream_chat() generator，写入 buffer。"""
        try:
            async for event in gen:
                session.append_event(event)
            session.mark_done("done")
        except asyncio.CancelledError:
            session.mark_done("cancelled")
            logger.info("stream task cancelled | session_id=%s", session.session_id)
        except Exception as exc:
            logger.exception("stream task error | session_id=%s", session.session_id)
            session.append_event({"type": "error", "message": str(exc)})
            session.mark_done("error")

    def _ensure_cleanup_loop(self) -> None:
        """确保有一个后台清理循环在运行。"""
        if self._cleanup_task and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_event_loop()
            self._cleanup_task = loop.create_task(self._cleanup_loop(), name="stream-cleanup")
        except RuntimeError:
            pass

    async def _cleanup_loop(self) -> None:
        """定期清理已完成且过期的 session。"""
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            expired = [
                sid
                for sid, s in self._sessions.items()
                if not s.is_active
                and s.finished_at is not None
                and (now - s.finished_at) > _BUFFER_TTL_SECONDS
            ]
            for sid in expired:
                del self._sessions[sid]
                logger.debug("cleaned up expired stream session | session_id=%s", sid)


def get_stream_session_manager() -> StreamSessionManager:
    """获取流式会话管理器实例。"""
    return StreamSessionManager()
