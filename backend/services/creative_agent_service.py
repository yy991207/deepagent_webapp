"""创作模式 Agent 服务。

说明：
- 复刻多智能体文本创作链路：Pre-Agent + Agent A/B/C
- 所有调用统一走同步 invoke/stream，避免异步对象跨线程/跨事件循环复用
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest
from langgraph.checkpoint.sqlite import SqliteSaver

from backend.config.deepagents_settings import create_model


@dataclass(slots=True)
class PromptPlan:
    """Pre-Agent 生成的角色方案。"""

    content_goal: str
    agent_a_prompt: str
    agent_b_prompt: str
    agent_c_prompt: str
    output_requirements: str

    def to_markdown(self) -> str:
        return (
            "# 创作模式 Prompt 方案\n"
            f"## 目标内容\n{self.content_goal}\n\n"
            f"## Agent A Prompt\n{self.agent_a_prompt}\n\n"
            f"## Agent B Prompt\n{self.agent_b_prompt}\n\n"
            f"## Agent C Prompt\n{self.agent_c_prompt}\n\n"
            f"## 输出要求\n{self.output_requirements}\n"
        )


def default_prompt_plan(user_prompt: str) -> PromptPlan:
    return PromptPlan(
        content_goal=user_prompt,
        agent_a_prompt="先理解并澄清用户需求，再基于确认后的需求编写文档初稿与修订版；只产出文档内容，不直接写代码文件。",
        agent_b_prompt="只负责挑刺，围绕 Agent A 的内容提出问题清单，不写新文档。",
        agent_c_prompt="只负责判断 Agent B 的问题是否合理，并给出理由，不改写文档。",
        output_requirements="输出 Markdown 文档成品，不输出无关实现过程。",
    )


class CreativeAppError(Exception):
    """创作模式统一业务异常。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class ToolPermissionPolicy:
    """工具白名单策略。"""

    def __init__(self, allowed_tools: set[str]) -> None:
        self.allowed_tools = allowed_tools

    def filter_tools(self, tools: list[Any]) -> list[Any]:
        filtered: list[Any] = []
        for tool in tools:
            name = getattr(tool, "name", None)
            if name is None and callable(tool):
                name = getattr(tool, "__name__", None)
            if isinstance(name, str) and name in self.allowed_tools:
                filtered.append(tool)
        return filtered


class ToolPermissionMiddleware(AgentMiddleware):
    """模型调用前过滤工具，避免角色越权。"""

    def __init__(self, policy: ToolPermissionPolicy) -> None:
        self._policy = policy

    def wrap_model_call(self, request: ModelRequest, handler):  # type: ignore[override]
        filtered_tools = self._policy.filter_tools(list(request.tools or []))
        return handler(request.override(tools=filtered_tools))


AGENT_A_ALLOWED_TOOLS = {
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "execute",
    "write_todos",
    "task",
}

AGENT_BC_ALLOWED_TOOLS = {"ls", "read_file", "glob", "grep"}


class LlmPreAgentPlanner:
    """Pre-Agent 方案生成器。"""

    def __init__(self) -> None:
        self._llm = create_model()

    def _extract_json(self, raw_text: str) -> dict[str, Any]:
        raw = str(raw_text or "").strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    return {}
            return {}

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text:
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return str(content or "")

    def plan(
        self,
        *,
        user_prompt: str,
        feedback: str = "",
        on_chunk: Callable[[str], None] | None = None,
    ) -> PromptPlan:
        prompt = (
            "你是 Pre-Agent，需要为 A/B/C 三个 Agent 生成角色 Prompt。\n"
            "目标：支持任意文本内容生成（例如开发文档、文案、脚本）。\n"
            "角色边界必须固定：\n"
            "1) Agent A: 先理解需求，再编写文档初稿并持续修订；\n"
            "2) Agent B: 只挑刺，指出内容问题；\n"
            "3) Agent C: 只判断 B 的问题是否合理。\n"
            "严禁把 B/C 写成创作角色，严禁让 A 直接去写代码文件。\n"
            "请结合用户需求和反馈输出 JSON，字段必须包含：\n"
            "content_goal, agent_a_prompt, agent_b_prompt, agent_c_prompt, output_requirements。\n"
            "不要输出多余字段。\n"
            f"用户需求: {user_prompt}\n"
            f"用户反馈: {feedback or '无'}\n"
        )

        chunks: list[str] = []
        try:
            for chunk in self._llm.stream(prompt):
                text = self._content_to_text(getattr(chunk, "content", ""))
                if text:
                    chunks.append(text)
                    if on_chunk:
                        on_chunk(text)
        except Exception:
            chunks = []

        text = "".join(chunks).strip()
        if not text:
            result = self._llm.invoke(prompt)
            text = self._content_to_text(getattr(result, "content", ""))

        parsed = self._extract_json(text)
        fallback = default_prompt_plan(user_prompt)
        if not parsed:
            return fallback

        return PromptPlan(
            content_goal=str(parsed.get("content_goal", fallback.content_goal)),
            agent_a_prompt=str(parsed.get("agent_a_prompt", fallback.agent_a_prompt)),
            agent_b_prompt=str(parsed.get("agent_b_prompt", fallback.agent_b_prompt)),
            agent_c_prompt=str(parsed.get("agent_c_prompt", fallback.agent_c_prompt)),
            output_requirements=str(parsed.get("output_requirements", fallback.output_requirements)),
        )


class DeepCreativeAgentClient:
    """创作模式 A/B/C 客户端。"""

    def __init__(
        self,
        *,
        run_id: str,
        prompt_plan: PromptPlan,
        workspace_root: Path,
    ) -> None:
        self._run_id = str(run_id)
        self._prompt_plan = prompt_plan
        self._workspace_root = workspace_root

        backend = FilesystemBackend(root_dir=self._workspace_root, virtual_mode=False)
        llm = create_model()

        checkpoint_dir = Path(".deepagents") / "creative" / "checkpoint"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        db_path = checkpoint_dir / "agent_memory.sqlite"
        self._checkpoint_conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(self._checkpoint_conn)

        self._thread_id_a = f"creative:{self._run_id}:agent_a"
        self._thread_id_b = f"creative:{self._run_id}:agent_b"
        self._thread_id_c = f"creative:{self._run_id}:agent_c"

        self._agent_a = create_deep_agent(
            model=llm,
            system_prompt=self._agent_a_system_prompt(),
            backend=backend,
            checkpointer=checkpointer,
            middleware=[ToolPermissionMiddleware(ToolPermissionPolicy(AGENT_A_ALLOWED_TOOLS))],
        )
        self._agent_b = create_deep_agent(
            model=llm,
            system_prompt=self._agent_b_system_prompt(),
            backend=backend,
            checkpointer=checkpointer,
            middleware=[ToolPermissionMiddleware(ToolPermissionPolicy(AGENT_BC_ALLOWED_TOOLS))],
        )
        self._agent_c = create_deep_agent(
            model=llm,
            system_prompt=self._agent_c_system_prompt(),
            backend=backend,
            checkpointer=checkpointer,
            middleware=[ToolPermissionMiddleware(ToolPermissionPolicy(AGENT_BC_ALLOWED_TOOLS))],
        )

    def close(self) -> None:
        try:
            self._checkpoint_conn.close()
        except Exception:
            pass

    def _agent_a_system_prompt(self) -> str:
        return (
            "你是 Agent A。"
            f"你的角色定位: {self._prompt_plan.agent_a_prompt}。"
            "请根据用户目标生成首版与迭代版文本成品。"
        )

    def _agent_b_system_prompt(self) -> str:
        return (
            "你是 Agent B，禁止写文件。"
            f"你的角色定位: {self._prompt_plan.agent_b_prompt}。"
            "你必须按 checklist 挑刺。"
            "请只输出 JSON: {\"issues\": [\"...\"]}。"
        )

    def _agent_c_system_prompt(self) -> str:
        return (
            "你是 Agent C，禁止写文件。"
            f"你的角色定位: {self._prompt_plan.agent_c_prompt}。"
            "你负责评估 Agent B 的问题是否合理。"
            "请只输出 JSON: {\"judgement\": \"reasonable|unreasonable\", \"reason\": \"...\"}。"
        )

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return str(content or "")

    def _extract_last_text(self, result: dict[str, Any]) -> str:
        messages = result.get("messages", [])
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", "")
            if msg_type in {"ai", "assistant"}:
                return self._content_to_text(getattr(msg, "content", ""))
            if isinstance(msg, dict) and msg.get("role") in {"ai", "assistant"}:
                return self._content_to_text(msg.get("content", ""))
        return ""

    def _safe_json(self, raw_text: str) -> dict[str, Any]:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw_text[start : end + 1])
                except json.JSONDecodeError:
                    return {}
            return {}

    def _thread_id_for(self, agent_name: str) -> str:
        if agent_name == "agent_a":
            return self._thread_id_a
        if agent_name == "agent_b":
            return self._thread_id_b
        return self._thread_id_c

    def _invoke_text(
        self,
        *,
        agent: Any,
        prompt: str,
        agent_name: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        chunks: list[str] = []
        invoke_payload = {"messages": [{"role": "user", "content": prompt}]}
        invoke_config = {"configurable": {"thread_id": self._thread_id_for(agent_name)}}

        try:
            try:
                for stream_item in agent.stream(
                    invoke_payload,
                    stream_mode="messages",
                    config=invoke_config,
                ):
                    if not isinstance(stream_item, tuple) or len(stream_item) != 2:
                        continue
                    message_chunk, _metadata = stream_item
                    if isinstance(message_chunk, dict):
                        chunk_text = self._content_to_text(message_chunk.get("content", ""))
                    else:
                        chunk_text = self._content_to_text(getattr(message_chunk, "content", ""))
                    if chunk_text:
                        chunks.append(chunk_text)
                        if on_chunk:
                            on_chunk(chunk_text)
            except Exception:
                chunks = []

            text = "".join(chunks).strip()
            if not text:
                result = agent.invoke(invoke_payload, config=invoke_config)
                text = self._extract_last_text(result)
                if text and on_chunk:
                    on_chunk(text)
            return text
        except Exception as exc:
            raise CreativeAppError("LLM_CALL_FAILED", str(exc)) from exc

    def clarify_requirement(
        self,
        *,
        user_prompt: str,
        feedback: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        prompt = (
            "请做需求理解与澄清。"
            f"\n目标内容类型: {self._prompt_plan.content_goal}"
            f"\n输出要求: {self._prompt_plan.output_requirements}"
            "\n输出格式: 1) 需求摘要 2) 关键要点 3) 边界与异常 4) 待确认问题。"
            f"\n用户需求: {user_prompt}"
            f"\n用户反馈: {feedback or '无'}"
        )
        return self._invoke_text(agent=self._agent_a, prompt=prompt, agent_name="agent_a", on_chunk=on_chunk)

    def draft_doc(
        self,
        *,
        user_prompt: str,
        clarified_requirement: str,
        issues: list[str],
        c_reason: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        prompt = (
            f"请输出目标内容成品，目标类型: {self._prompt_plan.content_goal}。"
            f"\n输出要求: {self._prompt_plan.output_requirements}"
            "\n请使用 Markdown 输出，并保证结构清晰、可审阅。"
            f"\n用户需求: {user_prompt}"
            f"\n需求确认: {clarified_requirement}"
            f"\n待修复问题: {issues if issues else '无'}"
            f"\nAgent C 判定意见: {c_reason or '无'}"
        )
        return self._invoke_text(agent=self._agent_a, prompt=prompt, agent_name="agent_a", on_chunk=on_chunk)

    def review_doc(
        self,
        *,
        user_prompt: str,
        clarified_requirement: str,
        demo_doc: str,
        checklist: list[str],
        c_reason: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> list[str]:
        prompt = (
            "请从校验视角审查当前内容并返回问题列表。"
            f"\n目标内容类型: {self._prompt_plan.content_goal}"
            f"\n校验角色: {self._prompt_plan.agent_b_prompt}"
            "\n请只输出 JSON: {\"issues\": [\"...\"]}。"
            f"\n用户需求: {user_prompt}"
            f"\nA 的需求理解: {clarified_requirement}"
            f"\n当前内容:\n{demo_doc}"
            f"\n校验清单: {checklist}"
            f"\nAgent C 反馈(若有): {c_reason or '无'}"
        )
        parsed = self._safe_json(
            self._invoke_text(agent=self._agent_b, prompt=prompt, agent_name="agent_b", on_chunk=on_chunk)
        )
        issues = parsed.get("issues", [])
        if isinstance(issues, list):
            return [str(item) for item in issues if str(item).strip()]
        return ["Agent B 输出格式不合法"]

    def judge_issues(
        self,
        *,
        user_prompt: str,
        clarified_requirement: str,
        demo_doc: str,
        issues: list[str],
        on_chunk: Callable[[str], None] | None = None,
    ) -> tuple[str, str]:
        prompt = (
            "请评估 Agent B 提出的问题是否合理并返回 JSON。"
            f"\n目标内容类型: {self._prompt_plan.content_goal}"
            f"\n判定角色: {self._prompt_plan.agent_c_prompt}"
            "\n请只输出 JSON: {\"judgement\": \"reasonable|unreasonable\", \"reason\": \"...\"}。"
            f"\n用户需求: {user_prompt}"
            f"\nA 的需求理解: {clarified_requirement}"
            f"\n当前内容:\n{demo_doc}"
            f"\n问题清单: {issues}"
        )
        parsed = self._safe_json(
            self._invoke_text(agent=self._agent_c, prompt=prompt, agent_name="agent_c", on_chunk=on_chunk)
        )
        judgement = str(parsed.get("judgement", "unreasonable")).lower()
        reason = str(parsed.get("reason", "未给出理由"))
        if judgement not in {"reasonable", "unreasonable"}:
            return "unreasonable", "Agent C judgement 字段不合法"
        return judgement, reason
