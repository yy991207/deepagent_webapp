"""聊天流服务 - 负责处理 SSE 流式对话、工具调用、沙箱管理、RAG 检索等核心链路。

本模块职责：
- 接收用户输入，组装系统提示词（沙箱环境、引用规则、文件写入规则等）
- 处理附件元数据，进行强制 RAG 检索并生成引用上下文
- 初始化并管理 OpenSandbox 远程沙箱，同步本地 skills 到沙箱
- 加载 MCP 工具（可选）、内置工具、自定义工具，创建 deepagents agent
- 流式处理 agent 输出，解析工具调用事件，持久化工具执行记录
- 生成推荐问题，保存聊天记录与记忆
- 支持会话取消、checkpoint 清理等运行时管理
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.messages import HumanMessage

from backend.services.agent_factory import create_agent
from backend.services.agent_stream_event_service import AgentStreamEventService
from backend.config.deepagents_settings import create_model, settings
from backend.services.checkpointer_provider import get_checkpointer
from backend.services.rag_service import RagService
from backend.services.skills_sync_service import SkillsSyncService
from backend.utils.tools import fetch_url, http_request, web_search
from backend.prompts.chat_prompts import (
    sandbox_environment_prompt,
    reference_rules_prompt,
    file_write_rules_prompt,
    research_task_rules_prompt,
    suggested_questions_prompt,
)

from backend.database.mongo_manager import get_mongo_manager
from backend.services.chat_service import ChatService
from backend.services.checkpoint_service import CheckpointService
from backend.services.filesystem_write_service import FilesystemWriteService
from backend.services.mcp_tool_service import get_mcp_tool_service
from backend.services.session_cancel_service import get_session_cancel_service


logger = logging.getLogger(__name__)


class ChatStreamService:
    """聊天流服务类。
    
    说明：
    - 统一管理 SSE 流式对话的完整生命周期
    - 负责沙箱、工具、RAG、checkpoint 等运行时资源的初始化与清理
    """
    def __init__(self, *, base_dir: Path) -> None:
        """初始化聊天流服务。
        
        Args:
            base_dir: 项目根目录，用于定位本地 skills 目录和文件系统 backend
        """
        self._base_dir = base_dir
        # OpenSandbox 远程沙箱的默认工作目录（固定为 /workspace）
        self._sandbox_root = Path("/workspace")
        logger.info("OpenSandbox mode enabled")

    async def stream_chat(
        self,
        *,
        text: str,
        thread_id: str,
        assistant_id: str = "agent",
        file_refs: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式处理聊天对话。
        
        说明：
        - 本方法是 SSE 流式对话的核心入口，负责从用户输入到 AI 流式输出的完整链路
        - 包括 checkpoint 清理、记忆加载、系统提示词组装、沙箱创建、agent 初始化、流式解析等
        - 所有异常都会被捕获并转为 SSE 事件，保证前端不会因为服务异常而断流
        
        Args:
            text: 用户输入的对话文本
            thread_id: 会话唯一标识符（用于 checkpoint、记忆、沙箱等资源的会话级隔离）
            assistant_id: 助手标识符（用于多租户/多角色场景）
            file_refs: 附件的 MongoDB 文档 ID 列表（用于 RAG 检索）
            
        Yields:
            SSE 事件字典，包含 type、session_id 等字段，具体类型包括：
            - session.status: 会话状态（thinking/done/cancelled/error）
            - tool.start/tool.end: 工具调用开始/结束
            - rag.references: RAG 检索结果引用
            - chat.delta: AI 回复文本增量
            - suggested.questions: 推荐问题
            - error: 错误信息
        """
        start_ts = time.monotonic()
        logger.debug(
            f"stream_chat start | thread_id={thread_id} | assistant_id={assistant_id} | text_len={len(str(text or ''))}"
        )
        if file_refs is None:
            file_refs = []

        # 清理旧 checkpoint，防止接口首包延迟过高
        try:
            checkpoint_service = CheckpointService()
            await checkpoint_service.cleanup_keep_last(session_id=thread_id)
        except Exception:
            pass

        # 加载会话记忆（用于上下文延续）
        mongo = get_mongo_manager()
        memory_text = ""
        try:
            memory_text = mongo.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
        except Exception:
            memory_text = ""

        # 组装系统提示词：沙箱环境指南 + 引用规则 + 文件写入规则
        extra_system_prompt = ""
        attachments_meta: list[dict[str, Any]] = []

        # 从 prompts 模块统一管理大段提示词，避免硬编码在业务逻辑里
        parts = [
            sandbox_environment_prompt(),
            reference_rules_prompt(),
            file_write_rules_prompt(),
            research_task_rules_prompt(),
        ]
        extra_system_prompt = "\n\n".join(parts).strip()

        # 处理附件元数据：将 MongoDB 文档 ID 转为文件名，并生成附件上下文提示词
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

        # 如果有附件，在系统提示词中加入附件来源说明和使用规则
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
            # 无附件时，如果有会话记忆，则加入记忆上下文
            if memory_text.strip():
                extra_system_prompt = (
                    (extra_system_prompt + "\n\n" + "<chat_memory>\n" + memory_text.strip() + "\n</chat_memory>")
                    .strip()
                )

        # 保存用户消息到 MongoDB（包含附件元数据）
        chat_service = ChatService()
        chat_service.save_user_message(
            thread_id=thread_id,
            assistant_id=assistant_id,
            content=str(text),
            attachments=attachments_meta,
        )

        # 初始化 RAG 相关变量：用于引用管理（给前端展示 & 最终落库）
        rag_references: list[dict[str, Any]] = []

        rag_service = RagService(mongo=mongo, base_dir=self._base_dir)
        rag_prep = await rag_service.force_rag_if_needed(
            user_text=str(text),
            thread_id=thread_id,
            assistant_id=assistant_id,
            file_refs=[str(x) for x in file_refs] if isinstance(file_refs, list) else [],
            system_prompt=extra_system_prompt,
        )
        extra_system_prompt = rag_prep.extra_system_prompt
        rag_references = rag_prep.rag_references
        for ev in rag_prep.events:
            yield ev

        # 使用 LangGraph checkpointer 进行会话状态持久化
        async with get_checkpointer() as checkpointer:
            # 初始化模型（如果失败则推送错误事件并结束流）
            try:
                model = create_model()
            except Exception as e:
                err_msg = f"模型初始化失败：{type(e).__name__}: {e}"
                logger.exception(err_msg)
                yield {"type": "error", "message": err_msg}
                yield {"type": "session.status", "status": "done"}
                return

            logger.debug(f"模型初始化成功 | thread_id={thread_id} | elapsed_ms={int((time.monotonic()-start_ts)*1000)}")
            
            # 初始化基础工具列表：HTTP 请求、网页抓取
            tools = [http_request, fetch_url]
            # 如果配置了 Tavily API，则加入网络搜索工具
            if settings.has_tavily:
                tools.append(web_search)

            # MCP 工具接入（可选）：从 .deepagents/mcp.json 加载并合并到工具列表
            # 说明：
            # - deepagents 官方推荐通过 langchain-mcp-adapters 把 MCP tools 转为 LangChain tools
            # - MCP tools 是异步工具，因此只能在 async 链路里 await 拉取
            # - 如果未安装依赖/配置不存在/加载失败，这里会自动降级为不启用 MCP
            try:
                mcp_tools = await get_mcp_tool_service().get_tools()
                if mcp_tools:
                    tools.extend(mcp_tools)
                    logger.info(
                        "MCP tools loaded | thread_id=%s | tools_count=%s",
                        thread_id,
                        len(mcp_tools),
                    )
            except Exception as _mcp_exc:
                logger.info(
                    "MCP tools load skipped | thread_id=%s | err=%s",
                    thread_id,
                    str(_mcp_exc),
                )

            # 创建自定义文件写入工具（用于将文件内容写入 MongoDB）
            fs_write_service = FilesystemWriteService(session_id=thread_id)
            custom_write_file = fs_write_service.create_write_file_tool()

            # 创建 OpenSandbox 远程沙箱（如果配置可用）
            # 说明：沙箱用于执行代码、操作文件系统、运行技能等，提供安全的隔离环境
            sandbox_backend = None
            sandbox_type = None
            try:
                from backend.services.opensandbox_backend import get_sandbox_manager

                sandbox_manager = get_sandbox_manager()
                sandbox_backend = await sandbox_manager.get_or_create_sandbox(
                    session_id=thread_id,
                    timeout_seconds=600,  # 10 分钟超时
                )
                sandbox_type = "opensandbox"
                logger.info(f"OpenSandbox backend created for session: {thread_id}, sandbox_id: {sandbox_backend.id}")

                # 关键逻辑：按 deepagents 官方约定，将本地 skills/skills 下的 SKILL.md 同步到沙箱
                skills_sync_service = SkillsSyncService(base_dir=self._base_dir)
                skills_sync_result = await skills_sync_service.sync_skills_to_sandbox(
                    sandbox_backend=sandbox_backend,
                    session_id=thread_id,
                )
                for ev in skills_sync_result.events:
                    yield ev
            except Exception as e:
                # 沙箱创建失败时自动降级为无沙箱模式，保证主链路可用
                err_msg = f"OpenSandbox 创建失败，将自动降级为无沙箱模式：{type(e).__name__}: {e}"
                logger.exception(err_msg)
                yield {"type": "sandbox.status", "status": "error", "message": err_msg}
                sandbox_backend = None
                sandbox_type = None

            logger.debug(
                f"sandbox ready | thread_id={thread_id} | has_sandbox={sandbox_backend is not None} | elapsed_ms={int((time.monotonic()-start_ts)*1000)}"
            )

            # 关键逻辑：如果没有拿到沙箱，则用项目目录作为工作区根目录
            effective_workspace_root = self._sandbox_root if sandbox_backend is not None else self._base_dir

            # 创建 deepagents agent（通过工厂方法统一处理 backend、skills、工具等）
            agent, _backend = create_agent(
                model=model,
                assistant_id=assistant_id,
                tools=[*tools, rag_prep.rag_tool, custom_write_file],
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

            # 构建有效的用户文本（如果有强制 RAG 引用，则加入引用上下文）
            effective_user_text = text
            if rag_references:
                ctx_lines = [
                    "请只基于下面的附件检索片段完成总结，禁止引入其它记忆/常识内容，且必须用 [1][2] 标注引用：",
                ]
                for ref in rag_references[:8]:
                    src = ref.get("source") or "unknown"
                    snippet = ref.get("text") or ""
                    idx = ref.get("index")
                    ctx_lines.append(f"[{idx}] source={src}\n{snippet}")
                effective_user_text = (str(text or "").strip() + "\n\n" + "\n\n".join(ctx_lines)).strip()

            # 准备流式输入和状态变量
            stream_input = {"messages": [HumanMessage(content=effective_user_text)]}
            assistant_accum: list[str] = []
            stream_event_service = AgentStreamEventService(mongo=mongo)
            stream_state = stream_event_service.init_state()

            # 获取会话取消服务，用于支持中断流式生成
            cancel_service = get_session_cancel_service()
            
            # 开始流式处理 agent 输出
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
                    
                    parsed = stream_event_service.parse_chunk(
                        chunk=chunk,
                        state=stream_state,
                        thread_id=thread_id,
                        assistant_id=assistant_id,
                        current_message_id=current_message_id,
                        rag_references_out=rag_references,
                    )
                    for ev in parsed.events:
                        yield ev
                    for delta in parsed.assistant_deltas:
                        assistant_accum.append(str(delta))

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
                            question_prompt = suggested_questions_prompt(text, assistant_text)

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
