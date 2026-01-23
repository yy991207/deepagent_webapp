from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from backend.database.mongo_manager import get_beijing_time


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RagPreparationResult:
    """RAG 预处理结果。

    说明：
    - extra_system_prompt：用于拼接到上层系统提示词里
    - rag_references：用于最终落库到 assistant message（给前端展示引用）
    - events：用于上层 SSE 透传（rag.references / tool.start / tool.end）
    - rag_tool：返回一个可注入 agent 的 rag_query 工具函数
    """

    extra_system_prompt: str
    rag_references: list[dict[str, Any]]
    events: list[dict[str, Any]]
    rag_tool: Callable[[str], list[dict[str, Any]]]


class RagService:
    """RAG 相关服务（尽量薄）。

    职责：
    - 支持“强制 RAG”：有附件时先做一次检索，推送 tool.start/tool.end + rag.references
    - 构造 rag_query 工具函数（注入到 agent，供对话过程随时调用）

    注意：
    - 这里不负责“附件元数据解析”，只接收 file_refs
    - 这里不负责写 chat message，只负责 tool message 的 upsert（用于工具可观测）
    """

    def __init__(self, *, mongo: Any, base_dir: Any) -> None:
        self._mongo = mongo
        self._base_dir = base_dir

    def build_rag_tool(
        self,
        *,
        assistant_id: str,
        file_refs: list[str],
    ) -> Callable[[str], list[dict[str, Any]]]:
        def rag_query(query: str) -> list[dict[str, Any]]:
            """RAG 检索工具函数（注入到 agent 中）。

            参数：
            - query：检索问题

            返回：
            - 列表，每个元素包含 index/source/score/text/mongo_id，用于前端引用展示。
            """
            try:
                from backend.middleware.rag_middleware import LlamaIndexRagMiddleware

                rag = LlamaIndexRagMiddleware(
                    assistant_id=assistant_id,
                    workspace_root=self._base_dir,
                    source_files=[str(x) for x in file_refs] if isinstance(file_refs, list) else None,
                )
                hits = rag.query(query)
                out: list[dict[str, Any]] = []
                for i, r in enumerate(hits, start=1):
                    if not isinstance(r, dict):
                        continue
                    out.append(
                        {
                            "index": i,
                            "source": r.get("source"),
                            "score": r.get("score"),
                            "text": r.get("text"),
                            "mongo_id": r.get("mongo_id"),
                        }
                    )
                return out
            except Exception:
                return []

        return rag_query

    async def force_rag_if_needed(
        self,
        *,
        user_text: str,
        thread_id: str,
        assistant_id: str,
        file_refs: list[str],
        system_prompt: str,
    ) -> RagPreparationResult:
        events: list[dict[str, Any]] = []
        rag_references: list[dict[str, Any]] = []
        extra_system_prompt = system_prompt

        rag_tool = self.build_rag_tool(assistant_id=assistant_id, file_refs=file_refs)

        # 无附件时，直接返回（rag_tool 仍可用，但上层一般不会注入）
        if not file_refs:
            return RagPreparationResult(
                extra_system_prompt=extra_system_prompt,
                rag_references=rag_references,
                events=events,
                rag_tool=rag_tool,
            )

        q = str(user_text or "").strip()
        if not q:
            return RagPreparationResult(
                extra_system_prompt=extra_system_prompt,
                rag_references=rag_references,
                events=events,
                rag_tool=rag_tool,
            )

        tool_call_id = f"rag-{uuid.uuid4().hex[:8]}"

        try:
            self._mongo.upsert_tool_message(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                tool_name="rag_query",
                tool_args={"query": q, "files": [str(x) for x in file_refs]},
                tool_status="running",
                started_at=get_beijing_time(),
            )
        except Exception:
            pass

        events.append({"type": "tool.start", "id": tool_call_id, "name": "rag_query", "args": {"query": q}})

        # 执行一次强制检索，用于构造 <rag_context>
        forced_hits = rag_tool(q)
        rag_references = [x for x in forced_hits if isinstance(x, dict)]

        if rag_references:
            events.append({"type": "rag.references", "references": rag_references})

            ctx_lines = [
                "<rag_context>",
                "你必须基于以下检索片段回答，并用 [1][2] 形式标注引用：",
            ]
            for ref in rag_references[:8]:
                src = ref.get("source") or "unknown"
                snippet = ref.get("text") or ""
                idx = ref.get("index")
                ctx_lines.append(f"[{idx}] source={src}\n{snippet}")
            ctx_lines.append("</rag_context>")
            extra_system_prompt = (extra_system_prompt + "\n\n" + "\n\n".join(ctx_lines)).strip()

        try:
            self._mongo.upsert_tool_message(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_call_id,
                tool_name="rag_query",
                tool_status="done" if rag_references else "error",
                tool_output=rag_references if rag_references else {"error": "no hits"},
                ended_at=get_beijing_time(),
            )
        except Exception:
            pass

        events.append(
            {
                "type": "tool.end",
                "id": tool_call_id,
                "name": "rag_query",
                "status": "success" if rag_references else "error",
                "output": rag_references if rag_references else {"error": "no hits"},
            }
        )

        return RagPreparationResult(
            extra_system_prompt=extra_system_prompt,
            rag_references=rag_references,
            events=events,
            rag_tool=rag_tool,
        )
