from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpConfig:
    """MCP 配置。

    说明：
    - 当前只实现 webapp 侧最小接入：从 .deepagents/mcp.json 读取 mcpServers
    - 由 langchain-mcp-adapters 负责把 MCP server tools 转成 LangChain tools
    """

    servers: dict[str, Any]


class McpToolService:
    """MCP 工具加载服务。

    设计目标：
    - 只在需要时加载 MCP tools
    - 做进程内缓存，避免每次请求都创建/连接 MCP client
    - 兼容未安装依赖场景：不影响主链路运行
    """

    def __init__(self, *, config_path: Path | None = None) -> None:
        self._config_path = config_path or (Path(".deepagents") / "mcp.json")
        self._lock = asyncio.Lock()
        self._cached_tools: list[Any] | None = None
        self._cached_config_mtime: float | None = None

    def _is_enabled(self) -> bool:
        raw = (os.environ.get("DEEPAGENTS_MCP_ENABLED") or "").strip().lower()
        if raw in {"0", "false", "no", "off"}:
            return False
        return True

    def _load_config(self) -> McpConfig | None:
        if not self._config_path.exists():
            return None

        try:
            data = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "MCP config parse failed: %s | path=%s",
                str(exc),
                str(self._config_path),
            )
            return None

        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            return None

        return McpConfig(servers=servers)

    async def get_tools(self) -> list[Any]:
        """获取 MCP tools（异步）。

        说明：
        - MCP tools 是异步工具，因此需要使用 agent.ainvoke()/agent.astream()
        - 这里只负责返回 tools 列表，不做业务逻辑
        """

        if not self._is_enabled():
            return []

        config = self._load_config()
        if config is None:
            return []

        try:
            mtime = self._config_path.stat().st_mtime
        except Exception:
            mtime = None

        async with self._lock:
            # 二次检查：避免并发重复加载
            if self._cached_tools is not None and self._cached_config_mtime == mtime:
                return self._cached_tools

            try:
                # 依赖是可选的：没安装就降级为空
                from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore
            except Exception as exc:
                logger.info(
                    "MCP disabled because langchain-mcp-adapters not installed: %s",
                    str(exc),
                )
                self._cached_tools = []
                self._cached_config_mtime = mtime
                return []

            try:
                client = MultiServerMCPClient(config.servers)
                tools = await client.get_tools()
                tools_list = list(tools) if tools is not None else []
            except Exception as exc:
                logger.warning(
                    "MCP tools load failed: %s | path=%s",
                    str(exc),
                    str(self._config_path),
                )
                tools_list = []

            self._cached_tools = tools_list
            self._cached_config_mtime = mtime
            return tools_list


_mcp_tool_service: McpToolService | None = None


def get_mcp_tool_service() -> McpToolService:
    """获取全局 MCP 工具服务单例。"""

    global _mcp_tool_service
    if _mcp_tool_service is None:
        _mcp_tool_service = McpToolService()
    return _mcp_tool_service
