from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage

from backend.database.mongo_manager import get_beijing_time


logger = logging.getLogger(__name__)


@dataclass
class StreamParseState:
    """流式解析状态。

    说明：
    - 该状态在单次 stream_chat 调用生命周期内使用
    - 用于处理 tool call 期间的文本增量暂存、工具开始/结束事件等
    """

    started_tools: set[str]
    active_tool_ids: set[str]
    pending_text_deltas: list[str]
    saw_tool_call: bool
    pending_tool_args: dict[str, list[str]]
    tool_id_to_name: dict[str, str]
    last_tool_id: str | None


@dataclass(frozen=True)
class StreamParseOutput:
    """单次 chunk 解析输出。"""

    events: list[dict[str, Any]]
    assistant_deltas: list[str]


class AgentStreamEventService:
    """Agent 流式事件解析服务（尽量薄）。

    职责：
    - 将 agent.astream 的 chunk 解析成统一的 SSE 事件
    - 负责 tool.start/tool.end 的事件生成
    - 负责 tool message 落库（upsert_tool_message）

    注意：
    - 这里不负责调用 agent.astream（上层负责循环）
    - 这里不负责保存最终 assistant message（交给 ChatService）
    """

    def __init__(self, *, mongo: Any) -> None:
        self._mongo = mongo

    def init_state(self) -> StreamParseState:
        return StreamParseState(
            started_tools=set(),
            active_tool_ids=set(),
            pending_text_deltas=[],
            saw_tool_call=False,
            pending_tool_args={},
            tool_id_to_name={},
            last_tool_id=None,
        )

    def _parse_tool_args(self, raw: Any) -> Any:
        if isinstance(raw, str):
            try:
                if not raw.strip():
                    return {}
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"value": raw}
        return raw

    def _append_tool_args_chunk(self, *, state: StreamParseState, tool_id: str, chunk_args: Any) -> Any | None:
        """追加 tool_call 参数分片并尝试解析完整 JSON。"""
        if chunk_args is None:
            return None
        if isinstance(chunk_args, (dict, list)):
            return chunk_args

        text = chunk_args if isinstance(chunk_args, str) else self._safe_preview(chunk_args, max_len=10_000)
        if not text:
            return None

        buffer = state.pending_tool_args.setdefault(tool_id, [])
        buffer.append(text)
        combined = "".join(buffer)

        try:
            return json.loads(combined)
        except Exception:
            return None

    def _emit_tool_start(
        self,
        *,
        events: list[dict[str, Any]],
        state: StreamParseState,
        thread_id: str,
        assistant_id: str,
        current_message_id: str,
        tool_id: str,
        tool_name: str,
        args_value: Any,
    ) -> None:
        """发送/更新 tool.start 事件，并同步 upsert tool message。"""
        try:
            self._mongo.upsert_tool_message(
                thread_id=thread_id,
                assistant_id=assistant_id,
                tool_call_id=tool_id,
                tool_name=tool_name,
                tool_args=args_value,
                tool_status="running",
                started_at=get_beijing_time(),
            )
        except Exception:
            pass

        events.append({"type": "tool.start", "id": tool_id, "name": tool_name, "args": args_value, "message_id": current_message_id})

    def _safe_preview(self, raw: Any, max_len: int = 400) -> str:
        """生成安全的日志预览文本，避免超长或不可序列化。"""
        try:
            text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        except Exception:
            text = str(raw)
        if len(text) > max_len:
            return text[:max_len] + "...(truncated)"
        return text

    def parse_chunk(
        self,
        *,
        chunk: Any,
        state: StreamParseState,
        thread_id: str,
        assistant_id: str,
        current_message_id: str,
        rag_references_out: list[dict[str, Any]] | None = None,
    ) -> StreamParseOutput:
        events: list[dict[str, Any]] = []
        assistant_deltas: list[str] = []

        # deepagents 的 chunk 一般是 (namespace, mode, data)
        if not isinstance(chunk, tuple) or len(chunk) != 3:
            return StreamParseOutput(events=events, assistant_deltas=assistant_deltas)

        _namespace, mode, data = chunk
        if mode != "messages":
            return StreamParseOutput(events=events, assistant_deltas=assistant_deltas)

        messages: list[Any] = []
        if isinstance(data, list) and data:
            messages = data
        elif isinstance(data, tuple) and len(data) == 2:
            message, _metadata = data
            messages = [message]
        else:
            return StreamParseOutput(events=events, assistant_deltas=assistant_deltas)

        def handle_message(message: Any) -> None:
            # ToolMessage：代表工具调用结果返回
            if isinstance(message, ToolMessage):
                tool_id = getattr(message, "tool_call_id", None)
                tool_name = getattr(message, "name", "")

                # 特殊处理：rag_query 的输出用于更新 rag.references
                if tool_name == "rag_query" and rag_references_out is not None:
                    try:
                        raw_content = message.content
                        parsed = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                        if isinstance(parsed, list):
                            rag_references = [x for x in parsed if isinstance(x, dict)]
                            rag_references_out[:] = rag_references
                            events.append({"type": "rag.references", "references": rag_references})
                    except Exception:
                        pass

                if tool_id:
                    tool_id_str = str(tool_id)
                    if tool_id_str in state.active_tool_ids:
                        state.active_tool_ids.discard(tool_id_str)

                    try:
                        self._mongo.upsert_tool_message(
                            thread_id=thread_id,
                            assistant_id=assistant_id,
                            tool_call_id=tool_id_str,
                            tool_name=tool_name,
                            tool_status=str(getattr(message, "status", "success")),
                            tool_output=message.content,
                            ended_at=get_beijing_time(),
                        )
                    except Exception:
                        pass

                    events.append(
                        {
                            "type": "tool.end",
                            "id": tool_id,
                            "name": tool_name,
                            "status": getattr(message, "status", "success"),
                            "output": message.content,
                            "message_id": current_message_id,
                        }
                    )

                    # 如果工具期间暂存了文本，且当前已经没有 active tool，则把暂存文本刷出去
                    if state.saw_tool_call and not state.active_tool_ids and state.pending_text_deltas:
                        for delta in state.pending_text_deltas:
                            assistant_deltas.append(str(delta))
                            events.append({"type": "chat.delta", "text": str(delta)})
                        state.pending_text_deltas = []

                return

            # 文本消息：可能来自 content_blocks 或 content
            if hasattr(message, "content_blocks") and getattr(message, "content_blocks"):
                for block in message.content_blocks:
                    block_type = block.get("type")

                    if block_type == "text":
                        text_delta = block.get("text", "")
                        if text_delta:
                            if state.saw_tool_call and state.active_tool_ids:
                                state.pending_text_deltas.append(str(text_delta))
                            else:
                                assistant_deltas.append(str(text_delta))
                                events.append({"type": "chat.delta", "text": str(text_delta)})

                    elif block_type in ("tool_call_chunk", "tool_call"):
                        chunk_name = block.get("name")
                        chunk_id = block.get("id")
                        chunk_args = block.get("args")
                        # 记录 LLM 原始 tool_call 参数，便于排查空参数问题
                        logger.debug(
                            "llm tool_call raw | name=%s | id=%s | args=%s",
                            str(chunk_name),
                            str(chunk_id),
                            self._safe_preview(chunk_args),
                        )

                        # 记录工具名与最近的 tool_id，便于后续拼接 args 分片
                        if chunk_id:
                            tool_id_str = str(chunk_id)
                            state.last_tool_id = tool_id_str
                            if chunk_name:
                                state.tool_id_to_name[tool_id_str] = str(chunk_name)

                        # 尝试把 args 分片拼起来，解析出完整 JSON
                        buffer_id = None
                        if chunk_id:
                            buffer_id = str(chunk_id)
                        elif state.last_tool_id and state.last_tool_id in state.active_tool_ids:
                            buffer_id = state.last_tool_id
                        elif len(state.active_tool_ids) == 1:
                            buffer_id = next(iter(state.active_tool_ids))

                        parsed_args = None
                        if buffer_id:
                            parsed_args = self._append_tool_args_chunk(
                                state=state,
                                tool_id=buffer_id,
                                chunk_args=chunk_args,
                            )
                            if parsed_args is not None:
                                # 解析成功后清空缓存，避免重复解析
                                state.pending_tool_args.pop(buffer_id, None)

                        if chunk_id and chunk_id not in state.started_tools and chunk_name:
                            args_value = self._parse_tool_args(chunk_args)
                            state.saw_tool_call = True

                            try:
                                tool_id_str = str(chunk_id)
                                state.active_tool_ids.add(tool_id_str)
                                # 工具启动时先用已有参数占位，后续如果解析到完整参数会再次更新
                                self._emit_tool_start(
                                    events=events,
                                    state=state,
                                    thread_id=thread_id,
                                    assistant_id=assistant_id,
                                    current_message_id=current_message_id,
                                    tool_id=tool_id_str,
                                    tool_name=str(chunk_name),
                                    args_value=args_value,
                                )
                            except Exception:
                                pass

                            state.started_tools.add(str(chunk_id))

                        # 如果已解析出完整参数，更新 tool.start（用相同 id 覆盖 args）
                        if parsed_args is not None and buffer_id:
                            tool_name = state.tool_id_to_name.get(buffer_id) or (str(chunk_name) if chunk_name else "")
                            if tool_name:
                                state.active_tool_ids.add(buffer_id)
                                self._emit_tool_start(
                                    events=events,
                                    state=state,
                                    thread_id=thread_id,
                                    assistant_id=assistant_id,
                                    current_message_id=current_message_id,
                                    tool_id=buffer_id,
                                    tool_name=tool_name,
                                    args_value=parsed_args,
                                )
                                state.started_tools.add(buffer_id)

            elif hasattr(message, "content"):
                content = getattr(message, "content", None)
                if isinstance(content, str) and content:
                    if state.saw_tool_call and state.active_tool_ids:
                        state.pending_text_deltas.append(str(content))
                    else:
                        assistant_deltas.append(str(content))
                        events.append({"type": "chat.delta", "text": str(content)})

                tool_calls = getattr(message, "tool_calls", None)
                if isinstance(tool_calls, list) and tool_calls:
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        tc_id = tc.get("id")
                        tc_name = tc.get("name")
                        tc_args = tc.get("args")

                        if tc_id:
                            tool_id_str = str(tc_id)
                            state.last_tool_id = tool_id_str
                            if tc_name:
                                state.tool_id_to_name[tool_id_str] = str(tc_name)

                        # 记录 LLM 原始 tool_call 参数，便于排查空参数问题
                        if tc_id and str(tc_id) not in state.started_tools and tc_name:
                            logger.debug(
                                "llm tool_call raw | name=%s | id=%s | args=%s",
                                str(tc_name),
                                str(tc_id),
                                self._safe_preview(tc_args),
                            )
                            args_value = self._parse_tool_args(tc_args)
                            state.saw_tool_call = True

                            try:
                                tool_id_str = str(tc_id)
                                state.active_tool_ids.add(tool_id_str)
                                self._emit_tool_start(
                                    events=events,
                                    state=state,
                                    thread_id=thread_id,
                                    assistant_id=assistant_id,
                                    current_message_id=current_message_id,
                                    tool_id=tool_id_str,
                                    tool_name=str(tc_name),
                                    args_value=args_value,
                                )
                            except Exception:
                                pass

                            state.started_tools.add(str(tc_id))

        for message in messages:
            handle_message(message)

        return StreamParseOutput(events=events, assistant_deltas=assistant_deltas)
