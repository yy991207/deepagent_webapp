"""webapp 内置工具，转发到 backend 实现，避免依赖外部 deepagents-cli。"""

from __future__ import annotations

from typing import Any, Literal

from backend.utils.tools import fetch_url, http_request, web_search

__all__ = ["fetch_url", "http_request", "web_search", "Literal", "Any"]
