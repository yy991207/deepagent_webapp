from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage, ToolMessage

from deepagents_cli.config import settings, create_model
from deepagents_cli.sessions import get_checkpointer
from deepagents_cli.tools import fetch_url, http_request, web_search
from deepagents_cli.agent import create_cli_agent

from backend.database.mongo_manager import get_beijing_time, get_mongo_manager
from backend.services.chat_service import ChatService
from backend.services.checkpoint_service import CheckpointService
from backend.services.filesystem_write_service import FilesystemWriteService
from backend.services.session_cancel_service import get_session_cancel_service


logger = logging.getLogger(__name__)


class ChatStreamService:
    def __init__(self, *, base_dir: Path) -> None:
        self._base_dir = base_dir

    async def stream_chat(
        self,
        *,
        text: str,
        thread_id: str,
        assistant_id: str = "agent",
        file_refs: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if file_refs is None:
            file_refs = []

        try:
            checkpoint_service = CheckpointService()
            await checkpoint_service.cleanup_keep_last(session_id=thread_id)
        except Exception:
            pass

        mongo = get_mongo_manager()
        memory_text = ""
        try:
            memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
        except Exception:
            memory_text = ""

        extra_system_prompt = ""
        attachments_meta: list[dict[str, Any]] = []

        extra_system_prompt = (
            extra_system_prompt + "\n\n" + 
            "<file_write_rules>\n"
            "**重要：文件写入后的回复规则**\n\n"
            "当你使用 write_file 工具保存文件后：\n"
            "1. **绝对禁止**在回复中提及任何文件路径（包括相对路径和绝对路径）\n"
            "2. **绝对禁止**使用引号或代码块包裹路径\n"
            "3. **只能**说：'文档已保存' 或 '内容已整理成文档'\n"
            "4. 用户会在聊天界面看到文档卡片，可以点击查看\n\n"
            "正确示例：\n"
            "- ✅ '我已将内容整理成文档，你可以点击下方的文档卡片查看。'\n"
            "- ✅ '文档已保存，请点击查看。'\n\n"
            "错误示例：\n"
            "- ❌ '已保存到 /Users/yang/...'\n"
            "- ❌ '文件路径为：...'\n"
            "- ❌ '保存在 `agent_framework_summary.md`'\n"
            "</file_write_rules>"
        ).strip()

        if isinstance(file_refs, list):
            for ref in file_refs:
                mongo_id = str(ref)
                filename = mongo_id
                try:
                    detail = mongo.get_document_detail(doc_id=mongo_id)
                    if isinstance(detail, dict) and detail.get("filename"):
                        filename = str(detail.get("filename"))
                except Exception:
                    filename = mongo_id
                attachments_meta.append({"mongo_id": mongo_id, "filename": filename})

        if attachments_meta:
            lines = [
                "<selected_sources>",
                "用户已附带来源如下（请把这些来源视为唯一上下文）：",
            ]
            for a in attachments_meta:
                lines.append(f"- {a.get('filename') or a.get('mongo_id')} (id={a.get('mongo_id')})")
            lines.extend(
                [
                    "使用规则：",
                    "- 回答需要引用附件内容时，必须调用 rag_query 基于上述来源检索。",
                    "- 不要调用 read_file 去读取工作区路径来替代附件内容。",
                    "</selected_sources>",
                ]
            )
            block = "\n".join(lines)
            extra_system_prompt = (extra_system_prompt + "\n\n" + block).strip()
        else:
            if memory_text.strip():
                extra_system_prompt = (
                    (extra_system_prompt + "\n\n" + "<chat_memory>\n" + memory_text.strip() + "\n</chat_memory>")
                    .strip()
                )

        chat_service = ChatService()
        chat_service.save_user_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=str(text),
            attachments=attachments_meta,
        )

        forced_rag_hits: list[dict[str, Any]] = []
        forced_rag_refs: list[dict[str, Any]] = []
        rag_references: list[dict[str, Any]] = []

        if attachments_meta and isinstance(file_refs, list):
            q = str(text or "").strip()
            if q:
                tool_call_id = f"rag-{uuid.uuid4().hex[:8]}"
                try:
                    mongo.upsert_tool_message(
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

                yield {"type": "tool.start", "id": tool_call_id, "name": "rag_query", "args": {"query": q}}

                try:
                    from deepagents_cli.rag_middleware import LlamaIndexRagMiddleware

                    rag = LlamaIndexRagMiddleware(
                        assistant_id=assistant_id,
                        workspace_root=self._base_dir,
                        source_files=[str(x) for x in file_refs],
                    )
                    forced_rag_hits = rag.query(q)
                except Exception:
                    forced_rag_hits = []

                for i, r in enumerate(forced_rag_hits, start=1):
                    if not isinstance(r, dict):
                        continue
                    forced_rag_refs.append(
                        {
                            "index": i,
                            "source": r.get("source"),
                            "score": r.get("score"),
                            "text": r.get("text"),
                            "mongo_id": r.get("mongo_id"),
                        }
                    )

                if forced_rag_refs:
                    rag_references = forced_rag_refs
                    yield {"type": "rag.references", "references": forced_rag_refs}

                    ctx_lines = [
                        "<rag_context>",
                        "你必须基于以下检索片段回答，并用 [1][2] 形式标注引用：",
                    ]
                    for ref in forced_rag_refs[:8]:
                        src = ref.get("source") or "unknown"
                        snippet = ref.get("text") or ""
                        idx = ref.get("index")
                        ctx_lines.append(f"[{idx}] source={src}\n{snippet}")
                    ctx_lines.append("</rag_context>")
                    extra_system_prompt = (extra_system_prompt + "\n\n" + "\n\n".join(ctx_lines)).strip()

                try:
                    mongo.upsert_tool_message(
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        tool_call_id=tool_call_id,
                        tool_name="rag_query",
                        tool_status="done" if forced_rag_refs else "error",
                        tool_output=forced_rag_refs if forced_rag_refs else {"error": "no hits"},
                        ended_at=get_beijing_time(),
                    )
                except Exception:
                    pass

                yield {
                    "type": "tool.end",
                    "id": tool_call_id,
                    "name": "rag_query",
                    "status": "success" if forced_rag_refs else "error",
                    "output": forced_rag_refs if forced_rag_refs else {"error": "no hits"},
                }

        def rag_query(query: str) -> list[dict[str, Any]]:
            """从当前工作区/已选来源里做语义检索。

            说明：
            - 该函数会作为 Tool 注入到 agent 中，因此必须提供 docstring。
            - 返回结构用于前端展示引用：包含 index/source/score/text/mongo_id。
            """
            try:
                from deepagents_cli.rag_middleware import LlamaIndexRagMiddleware

                rag = LlamaIndexRagMiddleware(
                    assistant_id=assistant_id,
                    workspace_root=self._base_dir,
                    source_files=[str(x) for x in file_refs] if isinstance(file_refs, list) else None,
                )
                hits = rag.query(query)
                out: list[dict[str, Any]] = []
                for i, r in enumerate(hits, start=1):
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

        async with get_checkpointer() as checkpointer:
            model = create_model()
            tools = [http_request, fetch_url]
            if settings.has_tavily:
                tools.append(web_search)

            fs_write_service = FilesystemWriteService(session_id=thread_id)
            custom_write_file = fs_write_service.create_write_file_tool()

            agent, _backend = create_cli_agent(
                model=model,
                assistant_id=assistant_id,
                tools=[*tools, rag_query, custom_write_file],
                workspace_root=self._base_dir,
                rag_source_files=[str(x) for x in file_refs] if isinstance(file_refs, list) else None,
                extra_system_prompt=extra_system_prompt,
                checkpointer=checkpointer,
                auto_approve=True,
                enable_rag=False,
                enable_shell=False,
            )

            yield {"type": "session.status", "status": "thinking"}

            effective_user_text = text
            if forced_rag_refs:
                ctx_lines = [
                    "请只基于下面的附件检索片段完成总结，禁止引入其它记忆/常识内容，且必须用 [1][2] 标注引用：",
                ]
                for ref in forced_rag_refs[:8]:
                    src = ref.get("source") or "unknown"
                    snippet = ref.get("text") or ""
                    idx = ref.get("index")
                    ctx_lines.append(f"[{idx}] source={src}\n{snippet}")
                effective_user_text = (str(text or "").strip() + "\n\n" + "\n\n".join(ctx_lines)).strip()

            stream_input = {"messages": [HumanMessage(content=effective_user_text)]}
            assistant_accum: list[str] = []
            started_tools: set[str] = set()
            active_tool_ids: set[str] = set()
            pending_text_deltas: list[str] = []
            saw_tool_call = False

            cancel_service = get_session_cancel_service()
            
            try:
                async for chunk in agent.astream(
                    stream_input,
                    stream_mode=["messages"],
                    subgraphs=True,
                    config={"configurable": {"thread_id": thread_id}},
                ):
                    # 检测会话是否已被取消，如果是则中断流式生成
                    if cancel_service.is_cancelled(thread_id):
                        logger.info(f"会话已取消，中断流式生成: session_id={thread_id}")
                        yield {"type": "session.status", "status": "cancelled"}
                        break
                    
                    if not isinstance(chunk, tuple) or len(chunk) != 3:
                        continue
                    _namespace, mode, data = chunk

                    if mode != "messages":
                        continue

                    if isinstance(data, list) and data:
                        message, _metadata = data[-1], {}
                    elif isinstance(data, tuple) and len(data) == 2:
                        message, _metadata = data
                    else:
                        continue

                    if isinstance(message, ToolMessage):
                        tool_id = getattr(message, "tool_call_id", None)
                        tool_name = getattr(message, "name", "")

                        if tool_name == "rag_query":
                            try:
                                raw_content = message.content
                                if isinstance(raw_content, str):
                                    parsed = json.loads(raw_content)
                                else:
                                    parsed = raw_content
                                if isinstance(parsed, list):
                                    rag_references = [x for x in parsed if isinstance(x, dict)]
                                    yield {"type": "rag.references", "references": rag_references}
                            except Exception:
                                pass

                        if tool_id:
                            try:
                                tool_id_str = str(tool_id)
                                if tool_id_str in active_tool_ids:
                                    active_tool_ids.discard(tool_id_str)

                                mongo.upsert_tool_message(
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

                            yield {
                                "type": "tool.end",
                                "id": tool_id,
                                "name": tool_name,
                                "status": getattr(message, "status", "success"),
                                "output": message.content,
                            }

                            if saw_tool_call and not active_tool_ids and pending_text_deltas:
                                for delta in pending_text_deltas:
                                    assistant_accum.append(str(delta))
                                    yield {"type": "chat.delta", "text": delta}
                                pending_text_deltas = []
                        continue

                    if not hasattr(message, "content_blocks") and not hasattr(message, "content"):
                        continue

                    if hasattr(message, "content_blocks") and message.content_blocks:
                        for block in message.content_blocks:
                            block_type = block.get("type")
                            if block_type == "text":
                                text_delta = block.get("text", "")
                                if text_delta:
                                    if saw_tool_call and active_tool_ids:
                                        pending_text_deltas.append(str(text_delta))
                                    else:
                                        assistant_accum.append(str(text_delta))
                                        yield {"type": "chat.delta", "text": text_delta}
                            elif block_type in ("tool_call_chunk", "tool_call"):
                                chunk_name = block.get("name")
                                chunk_id = block.get("id")
                                chunk_args = block.get("args")

                                if chunk_id and chunk_id not in started_tools and chunk_name:
                                    args_value = chunk_args
                                    if isinstance(args_value, str):
                                        try:
                                            args_value = json.loads(args_value)
                                        except json.JSONDecodeError:
                                            args_value = {"value": args_value}

                                    saw_tool_call = True
                                    try:
                                        tool_id_str = str(chunk_id)
                                        active_tool_ids.add(tool_id_str)
                                        mongo.upsert_tool_message(
                                            thread_id=thread_id,
                                            assistant_id=assistant_id,
                                            tool_call_id=tool_id_str,
                                            tool_name=str(chunk_name),
                                            tool_args=args_value,
                                            tool_status="running",
                                            started_at=get_beijing_time(),
                                        )
                                    except Exception:
                                        pass

                                    yield {"type": "tool.start", "id": chunk_id, "name": chunk_name, "args": args_value}
                                    started_tools.add(chunk_id)

                    elif hasattr(message, "content"):
                        if isinstance(message.content, str) and message.content:
                            text_delta = message.content
                            if saw_tool_call and active_tool_ids:
                                pending_text_deltas.append(str(text_delta))
                            else:
                                assistant_accum.append(str(text_delta))
                                yield {"type": "chat.delta", "text": text_delta}

                        if hasattr(message, "tool_calls") and message.tool_calls:
                            for tc in message.tool_calls:
                                tc_id = tc.get("id")
                                tc_name = tc.get("name")
                                tc_args = tc.get("args")

                                if tc_id and tc_id not in started_tools and tc_name:
                                    args_value = tc_args
                                    if isinstance(args_value, str):
                                        try:
                                            args_value = json.loads(args_value)
                                        except json.JSONDecodeError:
                                            args_value = {"value": args_value}

                                    saw_tool_call = True
                                    try:
                                        active_tool_ids.add(str(tc_id))
                                        mongo.upsert_tool_message(
                                            thread_id=thread_id,
                                            assistant_id=assistant_id,
                                            tool_call_id=str(tc_id),
                                            tool_name=str(tc_name),
                                            tool_args=args_value,
                                            tool_status="running",
                                            started_at=get_beijing_time(),
                                        )
                                    except Exception:
                                        pass

                                    yield {"type": "tool.start", "id": tc_id, "name": tc_name, "args": args_value}
                                    started_tools.add(tc_id)

            except Exception as exc:
                yield {"type": "error", "message": str(exc) or "unknown error"}

            finally:
                try:
                    assistant_text = "".join(assistant_accum).strip()
                    suggested_questions: list[str] = []

                    if assistant_text:
                        try:
                            question_prompt = f"""基于以下对话，生成 3 个简短的延续问题（每个问题不超过 20 字），帮助用户深入了解相关内容。

用户问题：{text}

AI 回答：{assistant_text[:500]}

要求：
1. 问题要具体、可操作
2. 与当前话题紧密相关
3. 每个问题一行，不要编号
4. 只输出 3 个问题，不要其他内容"""

                            question_msg = await model.ainvoke([HumanMessage(content=question_prompt)])
                            questions_text = getattr(question_msg, "content", "") or ""
                            suggested_questions = [
                                q.strip()
                                for q in questions_text.strip().split("\n")
                                if q.strip() and not q.strip().startswith("#")
                            ][:3]

                            if suggested_questions:
                                yield {"type": "suggested.questions", "questions": suggested_questions}
                        except Exception:
                            pass

                        chat_service.save_assistant_message(
                            thread_id=thread_id,
                            assistant_id=assistant_id,
                            content=assistant_text,
                            attachments=attachments_meta,
                            references=rag_references,
                            suggested_questions=suggested_questions,
                        )
                        chat_service.save_chat_memory(
                            thread_id=thread_id,
                            assistant_id=assistant_id,
                            user_text=str(text),
                            assistant_text=assistant_text,
                        )
                except Exception:
                    pass

                yield {"type": "session.status", "status": "done"}
