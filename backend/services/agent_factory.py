"""Agent 创建工厂。

说明：
- 承接原 deepagents_cli.agent 的职责，但归档到 backend/services。
- 基于 pip 安装的 deepagents SDK 创建 agent，不依赖外部 deepagents-cli 源码。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import BackendProtocol
from deepagents.backends.sandbox import SandboxBackendProtocol
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver


def _build_backend(
    *,
    workspace_root: Path | None,
    sandbox: SandboxBackendProtocol | None,
) -> BackendProtocol | None:
    if sandbox is not None:
        return sandbox
    if workspace_root is None:
        return None
    return FilesystemBackend(root_dir=str(workspace_root))


def create_agent(
    model: str | BaseChatModel,
    assistant_id: str,
    *,
    tools: list[Any] | None = None,
    workspace_root: Path | None = None,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    rag_source_files: list[str] | None = None,
    extra_system_prompt: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    enable_rag: bool = False,
    enable_shell: bool = False,
    checkpointer: BaseCheckpointSaver | None = None,
) -> tuple[Any, BackendProtocol | None]:
    """创建 webapp 运行时的 agent 实例。

    说明：
    - 当前先满足 webapp 运行所需的最小能力集合
    - skills/记忆等能力后续按业务再扩展
    """

    _ = assistant_id
    _ = sandbox_type
    _ = rag_source_files
    _ = enable_rag
    _ = enable_shell

    effective_prompt = extra_system_prompt or system_prompt
    backend = _build_backend(workspace_root=workspace_root, sandbox=sandbox)

    effective_tools: list[Any] = list(tools or [])

    research_subagent: SubAgent = {
        "name": "research-analyst",
        "description": "用于深度调研类任务：把问题拆分成多个子问题，基于工具搜索/抓取信息并输出结构化结论。",
        "system_prompt": (
            "你是一个研究分析子智能体。你的任务是独立完成一个明确的调研子问题，并输出可直接被主智能体引用的结论。\n"
            "要求：\n"
            "1. 优先使用 web_search 获取最新信息；必要时再用 fetch_url 抓取页面详细内容。\n"
            "2. 输出要包含：关键结论、要点列表、以及来源 URL（尽量精确到页面）。\n"
            "3. 只回答被分配的子问题，不要扩展到其它方向。"
        ),
        "tools": effective_tools,
    }

    # 关键逻辑：统一使用 deepagents.create_deep_agent 构建 agent
    create_kwargs: dict[str, Any] = {
        "model": model,
        "tools": effective_tools,
        "system_prompt": effective_prompt,
        "checkpointer": checkpointer,
        "backend": backend,
        "interrupt_on": {} if auto_approve else None,
        "subagents": [research_subagent],
    }

    # 关键逻辑：启用 deepagents 原生 skills 参数。
    # 说明：
    # - FilesystemBackend 会把 /skills/skills 映射到 root_dir/skills/skills
    # - OpenSandboxBackend(BaseSandbox) 直接操作沙箱文件系统绝对路径，因此需要传入沙箱内真实路径
    if backend is not None:
        if sandbox is not None:
            create_kwargs["skills"] = ["/workspace/skills/skills"]
        else:
            create_kwargs["skills"] = ["/skills/skills"]

    agent = create_deep_agent(**create_kwargs)
    return agent, backend
