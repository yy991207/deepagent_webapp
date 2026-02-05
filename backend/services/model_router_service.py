"""
模型分流服务

说明：
- 使用轻量模型做路由判断，决定主模型走 flash / plus / max
- 路由失败时自动回退到默认模型，避免影响主流程
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage

from backend.config.deepagents_settings import create_router_model


_DEFAULT_ROUTER_PROMPT = """你是一个“分流LLM”，负责根据用户需求选择合适的主模型等级。
只能在以下三档中选择：flash、plus、max。

判断规则（尽量简洁、保守）：
1) flash：简单问答、短文本改写、翻译、轻度总结、无需复杂推理或长输出。
2) plus：需要一定推理/结构化输出/多步分析，但规模中等、不会持续很久。
3) max：复杂规划、代码/系统设计、长篇输出、需要严谨推理或高风险结论。

输出要求：
- 只输出 JSON，不要额外文字或代码块
- 字段：route（flash|plus|max），reason（简短中文理由）
"""


@dataclass(frozen=True)
class RouterDecision:
    model_name: str
    route: str
    reason: str
    raw_text: str


class ModelRouterService:
    """模型分流服务（只做路由，不参与业务生成）"""

    def __init__(self) -> None:
        self._enabled = str(os.environ.get("ROUTER_LLM_ENABLED") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._router_model_name = str(os.environ.get("ROUTER_LLM_MODEL") or "qwen-flash").strip()
        self._flash_model = str(os.environ.get("ROUTER_LLM_FLASH_MODEL") or "qwen-flash").strip()
        self._plus_model = str(os.environ.get("ROUTER_LLM_PLUS_MODEL") or "qwen-plus").strip()
        self._max_model = str(os.environ.get("ROUTER_LLM_MAX_MODEL") or "qwen3-max-2026-01-23").strip()

    def _get_prompt(self) -> str:
        raw = str(os.environ.get("ROUTER_LLM_PROMPT") or "").strip()
        if raw:
            # 允许在 env 中用 \n 表示换行
            return raw.replace("\\n", "\n")
        return _DEFAULT_ROUTER_PROMPT

    def _route_to_model(self, route: str) -> str:
        route_key = str(route or "").strip().lower()
        if route_key == "max":
            return self._max_model
        if route_key == "plus":
            return self._plus_model
        return self._flash_model

    def _parse_json(self, text: str) -> dict | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        # 兼容偶发的非纯 JSON 输出，尽量提取第一个 {...}
        match = re.search(r"\{.*\}", raw, flags=re.S)
        candidate = match.group(0) if match else raw
        try:
            return json.loads(candidate)
        except Exception:
            return None

    async def route_model(
        self,
        *,
        user_text: str,
        has_attachments: bool,
        has_rag: bool,
        files_count: int,
    ) -> RouterDecision:
        """根据用户输入做模型分流判断。"""
        if not self._enabled:
            model_name = str(os.environ.get("OPENAI_MODEL") or "").strip() or self._flash_model
            return RouterDecision(
                model_name=model_name,
                route="flash",
                reason="路由未启用，走默认模型",
                raw_text="",
            )

        prompt = self._get_prompt()
        # 关键逻辑：路由调用是异步模型请求，必须在当前事件循环内 await
        router_llm = create_router_model(model_name=self._router_model_name)
        input_text = (
            f"{prompt}\n\n"
            f"用户需求：{user_text}\n"
            f"是否有附件：{str(has_attachments)}\n"
            f"是否触发RAG：{str(has_rag)}\n"
            f"附件数量：{files_count}\n"
        )
        msg = await router_llm.ainvoke([HumanMessage(content=input_text)])
        raw_text = str(getattr(msg, "content", "") or "").strip()

        data = self._parse_json(raw_text) or {}
        route = str(data.get("route") or "").strip().lower()
        reason = str(data.get("reason") or "").strip()
        if route not in {"flash", "plus", "max"}:
            route = "flash"
        model_name = self._route_to_model(route)
        return RouterDecision(model_name=model_name, route=route, reason=reason or "未提供理由", raw_text=raw_text)
