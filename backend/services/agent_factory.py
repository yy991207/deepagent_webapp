"""Agent 创建工厂。

说明：
- 承接原 deepagents_cli.agent 的职责，但归档到 backend/services。
- 基于 pip 安装的 deepagents SDK 创建 agent，不依赖外部 deepagents-cli 源码。
"""

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

    # 关键逻辑：统一使用 deepagents.create_deep_agent 构建 agent
    create_kwargs: dict[str, Any] = {
        "model": model,
        "tools": tools or [],
        "system_prompt": effective_prompt,
        "checkpointer": checkpointer,
        "backend": backend,
        "interrupt_on": {} if auto_approve else None,
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
