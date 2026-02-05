"""
会话取消服务

提供按 session_id 取消正在进行的流式请求的能力。
当前采用内存集合实现，适用于单进程部署。
如需多进程/多实例支持，可改用 Redis。
"""
from __future__ import annotations

import threading
from typing import Dict


class SessionCancelService:
    """会话取消服务（单例模式）"""
    
    _instance: "SessionCancelService | None" = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "SessionCancelService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cancel_versions: Dict[str, int] = {}
                    cls._instance._sessions_lock = threading.Lock()
        return cls._instance
    
    def cancel(self, session_id: str) -> None:
        """标记会话为已取消（递增取消版本号）"""
        with self._sessions_lock:
            current = self._cancel_versions.get(session_id, 0)
            self._cancel_versions[session_id] = current + 1

    def get_version(self, session_id: str) -> int:
        """获取会话当前的取消版本号"""
        with self._sessions_lock:
            return int(self._cancel_versions.get(session_id, 0))
    
    def is_cancelled(self, session_id: str, since_version: int) -> bool:
        """检查会话在指定版本之后是否发生过取消"""
        with self._sessions_lock:
            current = int(self._cancel_versions.get(session_id, 0))
            return current > int(since_version)
    
    def clear(self, session_id: str) -> None:
        """清除会话的取消标记"""
        with self._sessions_lock:
            self._cancel_versions.pop(session_id, None)
    
    def clear_all(self) -> None:
        """清除所有取消标记"""
        with self._sessions_lock:
            self._cancel_versions.clear()


def get_session_cancel_service() -> SessionCancelService:
    """获取会话取消服务实例"""
    return SessionCancelService()
