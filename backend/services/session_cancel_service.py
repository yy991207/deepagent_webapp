"""
会话取消服务

提供按 session_id 取消正在进行的流式请求的能力。
当前采用内存集合实现，适用于单进程部署。
如需多进程/多实例支持，可改用 Redis。
"""
from __future__ import annotations

import threading
from typing import Set


class SessionCancelService:
    """会话取消服务（单例模式）"""
    
    _instance: "SessionCancelService | None" = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "SessionCancelService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cancelled_sessions: Set[str] = set()
                    cls._instance._sessions_lock = threading.Lock()
        return cls._instance
    
    def cancel(self, session_id: str) -> None:
        """标记会话为已取消"""
        with self._sessions_lock:
            self._cancelled_sessions.add(session_id)
    
    def is_cancelled(self, session_id: str) -> bool:
        """检查会话是否已被取消"""
        with self._sessions_lock:
            return session_id in self._cancelled_sessions
    
    def clear(self, session_id: str) -> None:
        """清除会话的取消标记"""
        with self._sessions_lock:
            self._cancelled_sessions.discard(session_id)
    
    def clear_all(self) -> None:
        """清除所有取消标记"""
        with self._sessions_lock:
            self._cancelled_sessions.clear()


def get_session_cancel_service() -> SessionCancelService:
    """获取会话取消服务实例"""
    return SessionCancelService()
