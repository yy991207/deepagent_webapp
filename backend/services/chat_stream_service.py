from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage, ToolMessage

from backend.config.deepagents_settings import settings, create_model
from backend.services.checkpointer_provider import get_checkpointer
from backend.utils.tools import fetch_url, http_request, web_search
from backend.services.agent_factory import create_agent

from backend.database.mongo_manager import get_beijing_time, get_mongo_manager
from backend.services.chat_service import ChatService
from backend.services.checkpoint_service import CheckpointService
from backend.services.filesystem_write_service import FilesystemWriteService
from backend.services.session_cancel_service import get_session_cancel_service


logger = logging.getLogger(__name__)


class ChatStreamService:
    def __init__(self, *, base_dir: Path) -> None:
        self._base_dir = base_dir
        # 使用 OpenSandbox 远程沙箱
        self._sandbox_root = Path("/workspace")  # OpenSandbox 默认工作目录
        logger.info("OpenSandbox mode enabled")

    async def stream_chat(
        self,
        *,
        text: str,
        thread_id: str,
        assistant_id: str = "agent",
        file_refs: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        start_ts = time.monotonic()
        logger.debug(
            f"stream_chat start | thread_id={thread_id} | assistant_id={assistant_id} | text_len={len(str(text or ''))}"
        )
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
            "<reference_rules>\n"
            "引用标记使用规则：\n"
            "1. 只有在当前消息中存在 <rag_context> 检索片段时，才能使用 [1]、[2] 等引用标记\n"
            "2. 如果当前消息没有 <rag_context>，绝对禁止在回复中使用任何 [n] 格式的引用标记\n"
            "3. 不要模仿历史对话中的引用格式，每轮对话独立判断是否有检索上下文\n"
            "</reference_rules>\n\n"
            "<file_write_rules>\n"
            "重要：文件写入规则\n\n"
            "当用户要求整理、总结、归纳、汇总内容时，或明确要求保存文档时：\n"
            "1. 必须先调用 write_file 工具将内容保存成文档，不要只在回复里展示内容\n"
            "2. write_file 工具会将内容写入数据库，不是本地文件系统\n"
            "3. 禁止使用 read_file 工具读取刚写入的文档（文档不在本地文件系统）\n"
            "4. 工具调用成功后，再在回复中说明文档已保存\n"
            "5. 禁止在回复中提及任何文件路径或文件名\n"
            "6. 禁止使用引号或代码块包裹路径或文件名\n"
            "7. 用户会在聊天界面看到文档卡片，可以点击查看\n\n"
            "触发场景示例：\n"
            "- 用户说：帮我整理一份XXX总结\n"
            "- 用户说：归纳一下XXX要点\n"
            "- 用户说：把这些内容汇总成文档\n"
            "以上场景都必须调用 write_file 工具保存文档\n\n"
            "正确流程：\n"
            "- 先调用 write_file('/workspace/summary.md', '内容...', '总结文档')\n"
            "- 工具返回成功后，直接回复：我已将内容整理成文档，你可以点击下方的文档卡片查看。\n"
            "- 不要再调用 read_file 读取刚写的文档\n\n"
            "错误做法：\n"
            "- 不调用工具，直接在回复里展示整理好的内容\n"
            "- 不调用工具，直接说文档已保存\n"
            "- 调用 write_file 后又调用 read_file 读取刚写的文档\n"
            "- 在回复里提路径或文件名\n"
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
                    from backend.middleware.rag_middleware import LlamaIndexRagMiddleware

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
                from backend.middleware.rag_middleware import LlamaIndexRagMiddleware

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
            try:
                model = create_model()
            except Exception as e:
                err_msg = f"模型初始化失败：{type(e).__name__}: {e}"
                logger.exception(err_msg)
                yield {"type": "error", "message": err_msg}
                yield {"type": "session.status", "status": "done"}
                return

            logger.debug(f"模型初始化成功 | thread_id={thread_id} | elapsed_ms={int((time.monotonic()-start_ts)*1000)}")
            tools = [http_request, fetch_url]
            if settings.has_tavily:
                tools.append(web_search)

            fs_write_service = FilesystemWriteService(session_id=thread_id)
            custom_write_file = fs_write_service.create_write_file_tool()

            # 使用 OpenSandbox 远程沙箱
            try:
                from backend.services.opensandbox_backend import get_sandbox_manager

                sandbox_manager = get_sandbox_manager()
                sandbox_backend = await sandbox_manager.get_or_create_sandbox(
                    session_id=thread_id,
                    timeout_seconds=600,  # 10 分钟超时
                )
                sandbox_type = "opensandbox"
                logger.info(f"OpenSandbox backend created for session: {thread_id}, sandbox_id: {sandbox_backend.id}")
            except Exception as e:
                err_msg = f"OpenSandbox 创建失败，将自动降级为无沙箱模式：{type(e).__name__}: {e}"
                logger.exception(err_msg)
                yield {"type": "sandbox.status", "status": "error", "message": err_msg}
                sandbox_backend = None
                sandbox_type = None

            logger.debug(
                f"sandbox ready | thread_id={thread_id} | has_sandbox={sandbox_backend is not None} | elapsed_ms={int((time.monotonic()-start_ts)*1000)}"
            )

            # 关键逻辑：如果没有拿到 sandbox，则用项目目录作为工作区根目录
            effective_workspace_root = self._sandbox_root if sandbox_backend is not None else self._base_dir

            agent, _backend = create_agent(
                model=model,
                assistant_id=assistant_id,
                tools=[*tools, rag_query, custom_write_file],
                workspace_root=effective_workspace_root,
                sandbox=sandbox_backend,
                sandbox_type=sandbox_type,
                rag_source_files=[str(x) for x in file_refs] if isinstance(file_refs, list) else None,
                extra_system_prompt=extra_system_prompt,
                checkpointer=checkpointer,
                auto_approve=True,
                enable_rag=False,
                enable_shell=False,  # OpenSandbox 模式下禁用本地 shell
            )

            from backend.utils.snowflake import generate_snowflake_id
            current_message_id = str(generate_snowflake_id())
            
            yield {"type": "session.status", "status": "thinking"}
            yield {"type": "message.start", "message_id": current_message_id}

            logger.debug(
                f"agent astream begin | thread_id={thread_id} | message_id={current_message_id} | elapsed_ms={int((time.monotonic()-start_ts)*1000)}"
            )

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

                            tool_end_event = {
                                "type": "tool.end",
                                "id": tool_id,
                                "name": tool_name,
                                "status": getattr(message, "status", "success"),
                                "output": message.content,
                                "message_id": current_message_id,
                            }
                            yield tool_end_event

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
                err_msg = f"模型调用失败：{type(exc).__name__}: {exc}"
                logger.exception(err_msg)
                yield {"type": "error", "message": err_msg}

            finally:
                logger.debug(
                    f"stream_chat finalize | thread_id={thread_id} | elapsed_ms={int((time.monotonic()-start_ts)*1000)} | assistant_chars={len(''.join(assistant_accum))}"
                )
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
