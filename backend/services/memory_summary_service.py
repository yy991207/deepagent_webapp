from __future__ import annotations

import os
import uuid

from langchain_core.messages import HumanMessage

from backend.config.deepagents_settings import create_model, build_langchain_run_config

from backend.database.mongo_manager import get_mongo_manager
from backend.prompts.memory_summary_prompts import memory_summary_prompt


class MemorySummaryService:
    def __init__(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        max_memory_chars: int = 0,
        summary_max_chars: int = 0,
        lock_ttl_seconds: int = 0,
    ) -> None:
        self._thread_id = str(thread_id)
        self._assistant_id = str(assistant_id)

        # 配置统一从 env 读取，避免硬编码
        self._max_memory_chars = int(max_memory_chars) if int(max_memory_chars) > 0 else int(
            os.getenv("DEEPAGENTS_CHAT_MEMORY_MAX_CHARS") or "5000"
        )
        self._summary_max_chars = int(summary_max_chars) if int(summary_max_chars) > 0 else int(
            os.getenv("DEEPAGENTS_CHAT_MEMORY_SUMMARY_MAX_CHARS") or "500"
        )
        self._lock_ttl_seconds = int(lock_ttl_seconds) if int(lock_ttl_seconds) > 0 else int(
            os.getenv("DEEPAGENTS_CHAT_MEMORY_SUMMARY_LOCK_TTL_SECONDS") or "120"
        )
        self._mongo = get_mongo_manager()

    def _lock_key(self) -> str:
        return f"chat_memory_summary:{self._thread_id}:{self._assistant_id}"

    async def summarize_if_needed(self, *, force: bool = False) -> dict[str, object]:
        """当记忆超过阈值时，触发 LLM 总结，并覆盖写回 memory_text。

        返回结构：
        - status: ok/skipped/locked/error
        - memory_text_chars: int
        - memory_limit: int
        - ratio: float
        - summarized: bool
        """
        # 读取当前 memory_text
        memory_text = self._mongo.get_chat_memory(thread_id=self._thread_id, assistant_id=self._assistant_id)
        memory_chars = len(memory_text or "")

        if not force and memory_chars < self._max_memory_chars:
            return {
                "status": "skipped",
                "summarized": False,
                "memory_text_chars": memory_chars,
                "memory_limit": self._max_memory_chars,
                "ratio": min(memory_chars / float(self._max_memory_chars), 1.0) if self._max_memory_chars > 0 else 0.0,
            }

        owner_id = uuid.uuid4().hex
        # 并发安全：用分布式锁防止多请求同时触发总结
        locked = self._mongo.acquire_distributed_lock(
            lock_key=self._lock_key(),
            owner_id=owner_id,
            ttl_seconds=self._lock_ttl_seconds,
        )
        if not locked:
            # 并发场景：另一个请求正在总结，这里直接返回当前进度
            return {
                "status": "locked",
                "summarized": False,
                "memory_text_chars": memory_chars,
                "memory_limit": self._max_memory_chars,
                "ratio": min(memory_chars / float(self._max_memory_chars), 1.0) if self._max_memory_chars > 0 else 0.0,
            }

        try:
            # 二次读取：避免锁等待期间 memory_text 已更新
            memory_text = self._mongo.get_chat_memory(thread_id=self._thread_id, assistant_id=self._assistant_id)
            memory_chars = len(memory_text or "")
            if not force and memory_chars < self._max_memory_chars:
                return {
                    "status": "skipped",
                    "summarized": False,
                    "memory_text_chars": memory_chars,
                    "memory_limit": self._max_memory_chars,
                    "ratio": min(memory_chars / float(self._max_memory_chars), 1.0) if self._max_memory_chars > 0 else 0.0,
                }

            # 关键逻辑：总结框架提示词（中文口语化，方便业务同学维护）
            prompt = memory_summary_prompt(memory_text)

            model = create_model()
            msg = await model.ainvoke(
                [HumanMessage(content=prompt)],
                config=build_langchain_run_config(
                    thread_id=self._thread_id,
                    run_name="chat_memory_summary",
                    tags=["deepagents-webapp", "memory-summary"],
                    metadata={"assistant_id": self._assistant_id},
                ),
            )
            summary_text = str(getattr(msg, "content", "") or "").strip()
            if self._summary_max_chars > 0 and len(summary_text) > self._summary_max_chars:
                summary_text = summary_text[: self._summary_max_chars].strip()

            # 覆盖写回数据库（避免写完立刻再查一次再返回，直接用 summary_text 计算字数）
            self._mongo.set_chat_memory(
                thread_id=self._thread_id,
                assistant_id=self._assistant_id,
                memory_text=summary_text,
            )

            new_chars = len(summary_text)
            return {
                "status": "ok",
                "summarized": True,
                "memory_text_chars": new_chars,
                "memory_limit": self._max_memory_chars,
                "ratio": min(new_chars / float(self._max_memory_chars), 1.0) if self._max_memory_chars > 0 else 0.0,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "error",
                "summarized": False,
                "error": str(exc),
                "memory_text_chars": memory_chars,
                "memory_limit": self._max_memory_chars,
                "ratio": min(memory_chars / float(self._max_memory_chars), 1.0) if self._max_memory_chars > 0 else 0.0,
            }
        finally:
            self._mongo.release_distributed_lock(lock_key=self._lock_key(), owner_id=owner_id)
