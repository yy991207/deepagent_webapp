"""
Agent 注册表（Agent Registry）

提供统一的 Agent 管理机制，支持：
1. Agent 注册与发现
2. 动态加载 Agent 配置
3. 健康检查
4. 按类型/名称查找 Agent

架构：
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Registry                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐       │
│  │ podcast_agent │  │ summary_agent │  │ xxx_agent     │  ...  │
│  │ :8888         │  │ :8889         │  │ :8890         │       │
│  └───────────────┘  └───────────────┘  └───────────────┘       │
└─────────────────────────────────────────────────────────────────┘

Agent 配置格式：
{
    "agent_id": "podcast_agent",
    "name": "Podcast Generation Agent",
    "type": "podcast",
    "url": "http://localhost:8888",
    "endpoints": {
        "run": "/api/agent/run",
        "cancel": "/api/agent/cancel",
        "health": "/health"
    },
    "timeout": 30,
    "retries": 3,
    "enabled": true
}
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class AgentEndpoints:
    """Agent 端点配置"""
    run: str = "/api/agent/run"
    cancel: str = "/api/agent/cancel"
    health: str = "/health"
    status: str = "/api/agent/status"


@dataclass
class AgentConfig:
    """Agent 配置"""
    agent_id: str
    name: str
    agent_type: str
    url: str
    endpoints: AgentEndpoints = field(default_factory=AgentEndpoints)
    timeout: int = 30
    retries: int = 3
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentConfig":
        """从字典创建 AgentConfig"""
        endpoints_data = data.get("endpoints", {})
        endpoints = AgentEndpoints(
            run=endpoints_data.get("run", "/api/agent/run"),
            cancel=endpoints_data.get("cancel", "/api/agent/cancel"),
            health=endpoints_data.get("health", "/health"),
            status=endpoints_data.get("status", "/api/agent/status"),
        )
        return cls(
            agent_id=data["agent_id"],
            name=data.get("name", data["agent_id"]),
            agent_type=data.get("type", data.get("agent_type", "generic")),
            url=data["url"],
            endpoints=endpoints,
            timeout=data.get("timeout", 30),
            retries=data.get("retries", 3),
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": self.agent_type,
            "url": self.url,
            "endpoints": {
                "run": self.endpoints.run,
                "cancel": self.endpoints.cancel,
                "health": self.endpoints.health,
                "status": self.endpoints.status,
            },
            "timeout": self.timeout,
            "retries": self.retries,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }
    
    def get_run_url(self) -> str:
        """获取任务执行 URL"""
        return f"{self.url.rstrip('/')}{self.endpoints.run}"
    
    def get_cancel_url(self) -> str:
        """获取任务取消 URL"""
        return f"{self.url.rstrip('/')}{self.endpoints.cancel}"
    
    def get_health_url(self) -> str:
        """获取健康检查 URL"""
        return f"{self.url.rstrip('/')}{self.endpoints.health}"


class AgentRegistry:
    """Agent 注册表
    
    单例模式，提供全局 Agent 管理。
    支持从配置文件、环境变量或代码动态注册 Agent。
    """
    
    _instance: "AgentRegistry | None" = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "AgentRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        self._agents: dict[str, AgentConfig] = {}
        self._agents_lock = threading.RLock()
        self._config_file: str | None = None
        self._last_reload: datetime | None = None
        self._initialized = True
        
        # 自动加载配置
        self._auto_load_config()
    
    def _auto_load_config(self) -> None:
        """自动加载配置"""
        # 1. 尝试从环境变量加载配置文件路径
        config_path = os.environ.get("AGENT_REGISTRY_CONFIG")
        if config_path and Path(config_path).exists():
            self.load_from_file(config_path)
            return
        
        # 2. 尝试从默认路径加载
        default_paths = [
            Path(__file__).parent / "agents.json",
            Path(__file__).parent.parent.parent / "config" / "agents.json",
            Path.cwd() / "config" / "agents.json",
        ]
        for path in default_paths:
            if path.exists():
                self.load_from_file(str(path))
                return
        
        # 3. 从环境变量注册默认 Agent
        self._register_from_env()
    
    def _register_from_env(self) -> None:
        """从环境变量注册 Agent"""
        # Podcast Agent
        podcast_url = os.environ.get("PODCAST_AGENT_URL", "http://localhost:8888")
        self.register(AgentConfig(
            agent_id="podcast_agent",
            name="Podcast Generation Agent",
            agent_type="podcast",
            url=podcast_url,
            endpoints=AgentEndpoints(),
            timeout=30,
            retries=3,
            enabled=True,
        ))
        
        # 可以从环境变量注册更多 Agent
        # 格式: AGENT_<ID>_URL, AGENT_<ID>_TYPE
        for key, value in os.environ.items():
            if key.startswith("AGENT_") and key.endswith("_URL"):
                agent_id = key[6:-4].lower()  # 移除 AGENT_ 前缀和 _URL 后缀
                if agent_id == "podcast":
                    continue  # 已注册
                
                agent_type = os.environ.get(f"AGENT_{agent_id.upper()}_TYPE", "generic")
                agent_name = os.environ.get(f"AGENT_{agent_id.upper()}_NAME", agent_id)
                
                self.register(AgentConfig(
                    agent_id=f"{agent_id}_agent",
                    name=agent_name,
                    agent_type=agent_type,
                    url=value,
                ))
    
    def load_from_file(self, config_path: str) -> None:
        """从配置文件加载 Agent 注册表"""
        logger.info(f"[Registry] 从文件加载 Agent 配置: {config_path}")
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            agents_data = data.get("agents", [])
            if isinstance(data, list):
                agents_data = data
            
            with self._agents_lock:
                for agent_data in agents_data:
                    try:
                        config = AgentConfig.from_dict(agent_data)
                        self._agents[config.agent_id] = config
                        logger.info(f"[Registry] 注册 Agent: {config.agent_id} ({config.url})")
                    except Exception as e:
                        logger.error(f"[Registry] 加载 Agent 失败: {agent_data} | error={e}")
            
            self._config_file = config_path
            self._last_reload = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"[Registry] 加载配置文件失败: {config_path} | error={e}")
    
    def reload(self) -> None:
        """重新加载配置文件"""
        if self._config_file:
            self.load_from_file(self._config_file)
    
    def register(self, config: AgentConfig) -> None:
        """注册 Agent"""
        with self._agents_lock:
            self._agents[config.agent_id] = config
            logger.info(f"[Registry] 注册 Agent: {config.agent_id} ({config.url})")
    
    def unregister(self, agent_id: str) -> bool:
        """注销 Agent"""
        with self._agents_lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                logger.info(f"[Registry] 注销 Agent: {agent_id}")
                return True
            return False
    
    def get(self, agent_id: str) -> AgentConfig | None:
        """获取 Agent 配置"""
        with self._agents_lock:
            return self._agents.get(agent_id)
    
    def get_by_type(self, agent_type: str) -> list[AgentConfig]:
        """按类型获取 Agent 列表"""
        with self._agents_lock:
            return [
                agent for agent in self._agents.values()
                if agent.agent_type == agent_type and agent.enabled
            ]
    
    def list_all(self) -> list[AgentConfig]:
        """列出所有 Agent"""
        with self._agents_lock:
            return list(self._agents.values())
    
    def list_enabled(self) -> list[AgentConfig]:
        """列出所有启用的 Agent"""
        with self._agents_lock:
            return [agent for agent in self._agents.values() if agent.enabled]
    
    def check_health(self, agent_id: str, timeout: int = 5) -> dict[str, Any]:
        """检查 Agent 健康状态"""
        agent = self.get(agent_id)
        if not agent:
            return {"agent_id": agent_id, "healthy": False, "error": "Agent not found"}
        
        try:
            response = requests.get(agent.get_health_url(), timeout=timeout)
            response.raise_for_status()
            return {
                "agent_id": agent_id,
                "healthy": True,
                "status_code": response.status_code,
                "response": response.json() if response.text else None,
            }
        except requests.RequestException as e:
            return {
                "agent_id": agent_id,
                "healthy": False,
                "error": str(e),
            }
    
    def check_all_health(self, timeout: int = 5) -> dict[str, dict[str, Any]]:
        """检查所有 Agent 健康状态"""
        results = {}
        for agent in self.list_enabled():
            results[agent.agent_id] = self.check_health(agent.agent_id, timeout)
        return results
    
    def to_dict(self) -> dict[str, Any]:
        """导出注册表为字典"""
        with self._agents_lock:
            return {
                "agents": [agent.to_dict() for agent in self._agents.values()],
                "last_reload": self._last_reload.isoformat() if self._last_reload else None,
                "config_file": self._config_file,
            }


# 全局注册表实例
def get_agent_registry() -> AgentRegistry:
    """获取全局 Agent 注册表实例"""
    return AgentRegistry()
