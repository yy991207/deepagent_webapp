"""webapp 内置的 agent 创建逻辑，基于 deepagents SDK。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
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


def create_cli_agent(
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
    - 基于 deepagents SDK 创建，不依赖外部 deepagents-cli 源码
    - 当前以沙箱 backend 为主，后续可按需扩展 skills/记忆等能力
    """
    _ = assistant_id
    _ = sandbox_type
    _ = rag_source_files
    _ = enable_rag
    _ = enable_shell

    effective_prompt = extra_system_prompt or system_prompt
    backend = _build_backend(workspace_root=workspace_root, sandbox=sandbox)
    # 关键逻辑：统一使用 deepagents.create_deep_agent 构建 agent
    agent = create_deep_agent(
        model=model,
        tools=tools or [],
        system_prompt=effective_prompt,
        checkpointer=checkpointer,
        backend=backend,
        interrupt_on={} if auto_approve else None,
    )
    return agent, backend
