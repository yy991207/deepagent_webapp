"""webapp 内置的 deepagents_cli 配置实现，避免依赖外部仓库。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel


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
