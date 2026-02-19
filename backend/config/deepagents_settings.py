"""DeepAgents 运行时配置（webapp 内置）。

说明：
- 这里承接原 deepagents_cli.config 的职责，但归档到 backend/config，避免单独 cli 目录。
- 路径统一使用相对路径（.deepagents/），避免部署时绝对路径找不到。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


def _is_truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def bootstrap_langsmith_env() -> dict[str, str]:
    """兼容旧变量命名：把 LANGCHAIN_* 自动补齐到 LANGSMITH_*。

    说明：
    - 历史上很多项目使用 LANGCHAIN_API_KEY/LANGCHAIN_PROJECT 等变量。
    - 新版文档主推 LANGSMITH_* 命名。
    - 这里在进程启动阶段做一次映射，减少迁移成本。
    """

    changed: dict[str, str] = {}
    aliases = (
        ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"),
        ("LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"),
        ("LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT"),
    )
    for legacy_key, new_key in aliases:
        legacy_value = str(os.environ.get(legacy_key) or "").strip()
        new_value = str(os.environ.get(new_key) or "").strip()
        if legacy_value and not new_value:
            os.environ[new_key] = legacy_value
            changed[new_key] = legacy_key

    if _is_truthy(os.environ.get("LANGCHAIN_TRACING_V2")) and not str(os.environ.get("LANGSMITH_TRACING") or "").strip():
        os.environ["LANGSMITH_TRACING"] = "true"
        changed["LANGSMITH_TRACING"] = "LANGCHAIN_TRACING_V2"

    if changed:
        logger.info(
            "LangSmith env bootstrap applied | mappings=%s",
            {new: old for new, old in changed.items()},
        )
    return changed


def build_langchain_run_config(
    *,
    thread_id: str | None = None,
    run_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 LangChain/LangGraph 运行配置，统一注入 run 元数据。"""

    config: dict[str, Any] = {}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
    if run_name:
        config["run_name"] = str(run_name)
    if tags:
        config["tags"] = [str(tag) for tag in tags]
    if metadata:
        config["metadata"] = dict(metadata)
    return config


# 模块加载时先做一次变量兼容映射，确保后续模型实例统一生效。
bootstrap_langsmith_env()


def _find_project_root(start_path: Optional[Path] = None) -> Optional[Path]:
    """向上查找 git 根目录，用于识别项目根路径。"""

    current = Path(start_path or Path.cwd()).resolve()
    for parent in [current, *list(current.parents)]:
        if (parent / ".git").exists():
            return parent
    return None


@dataclass(frozen=True)
class Settings:
    """简化版配置，用于 webapp 运行时依赖。"""

    openai_api_key: str | None
    tavily_api_key: str | None
    project_root: Path | None

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key)

    def ensure_agent_dir(self, assistant_id: str) -> Path:
        """确保 agent 目录存在，用于 RAG 索引等落地。"""

        base = Path(".deepagents") / str(assistant_id)
        base.mkdir(parents=True, exist_ok=True)
        return base


settings = Settings(
    openai_api_key=os.environ.get("OPENAI_API_KEY"),
    tavily_api_key=os.environ.get("TAVILY_API_KEY"),
    project_root=_find_project_root(),
)


def create_model(model_name: str | None = None) -> BaseChatModel:
    """创建 LLM 实例，统一从环境变量读取配置。"""

    resolved_model = model_name or os.environ.get("OPENAI_MODEL") or "qwen-turbo"
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    temperature_raw = os.environ.get("OPENAI_TEMPERATURE")
    temperature = float(temperature_raw) if temperature_raw else 0.7

    # 关键逻辑：统一通过 OpenAI 兼容接口创建模型
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        base_url=base_url,
        model=resolved_model,
        temperature=temperature,
    )


def create_router_model(model_name: str | None = None) -> BaseChatModel:
    """创建路由 LLM 实例（默认低温度，保证稳定分流）。"""

    resolved_model = model_name or os.environ.get("ROUTER_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "qwen-flash"
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
    temperature_raw = os.environ.get("ROUTER_LLM_TEMPERATURE")
    temperature = float(temperature_raw) if temperature_raw else 0.1

    return ChatOpenAI(
        api_key=settings.openai_api_key,
        base_url=base_url,
        model=resolved_model,
        temperature=temperature,
    )
