"""创作模式状态机服务。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.database.mongo_manager import get_beijing_time, get_mongo_manager
from backend.services.chat_service import ChatService
from backend.services.creative_agent_service import (
    CreativeAppError,
    DeepCreativeAgentClient,
    LlmPreAgentPlanner,
    PromptPlan,
    default_prompt_plan,
)
from backend.utils.snowflake import generate_snowflake_id


DEFAULT_CHECKLIST = [
    "功能点描述完整",
    "异常场景覆盖",
    "业务逻辑设计合理",
    "可执行步骤清晰",
]


class CreativeStateMachineService:
    """创作模式状态机。

    状态流转：
    1. pre_agent_generating -> pre_agent_pending_confirm
    2. pre_agent_processing -> requirement_pending_confirm
    3. requirement_processing -> draft_pending_confirm
    4. draft_processing -> bc_review_done
    5. round_processing -> (draft_pending_confirm | completed)
    """

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self._mongo = get_mongo_manager()
        self._chat = ChatService()
        self._workspace_root = workspace_root or Path(".")

    def _serialize_dt(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    def _apply_and_build_run(self, run: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        next_run = dict(run)
        next_run.update(updates)
        next_run["updated_at"] = self._serialize_dt(updates.get("updated_at") or get_beijing_time())
        if "created_at" in next_run:
            next_run["created_at"] = self._serialize_dt(next_run.get("created_at"))
        if "completed_at" in next_run:
            next_run["completed_at"] = self._serialize_dt(next_run.get("completed_at"))
        return next_run

    def _load_run(self, *, run_id: str) -> dict[str, Any]:
        run = self._mongo.get_creative_run(run_id=run_id)
        if not run:
            raise CreativeAppError("CREATIVE_RUN_NOT_FOUND", "创作任务不存在")
        return run

    def _plan_from_run(self, run: dict[str, Any]) -> PromptPlan:
        raw = run.get("prompt_plan") or {}
        if not isinstance(raw, dict):
            raise CreativeAppError("CREATIVE_RUN_INVALID", "prompt_plan 数据不合法")
        return PromptPlan(
            content_goal=str(raw.get("content_goal") or run.get("user_prompt") or ""),
            agent_a_prompt=str(raw.get("agent_a_prompt") or ""),
            agent_b_prompt=str(raw.get("agent_b_prompt") or ""),
            agent_c_prompt=str(raw.get("agent_c_prompt") or ""),
            output_requirements=str(raw.get("output_requirements") or ""),
        )

    def _append_user_action_message(self, *, run: dict[str, Any], stage: str, action: str, feedback: str) -> None:
        content = f"[创作模式][{stage}] 用户操作：{action}"
        if feedback.strip():
            content = f"{content}\n\n补充反馈：\n{feedback.strip()}"
        self._chat.save_user_message(
            thread_id=str(run.get("session_id") or ""),
            assistant_id=str(run.get("assistant_id") or "agent"),
            content=content,
            attachments=[],
        )

    def _append_assistant_message(self, *, run: dict[str, Any], content: str) -> None:
        self._chat.save_assistant_message(
            thread_id=str(run.get("session_id") or ""),
            assistant_id=str(run.get("assistant_id") or "agent"),
            content=content,
            attachments=[],
            references=[],
            suggested_questions=[],
        )

    def _format_pre_agent_message(self, *, run_id: str, plan: PromptPlan) -> str:
        return (
            f"[创作模式][run_id={run_id}] Pre-Agent 方案\n\n"
            f"目标内容：{plan.content_goal}\n\n"
            f"Agent A 角色：{plan.agent_a_prompt}\n\n"
            f"Agent B 角色：{plan.agent_b_prompt}\n\n"
            f"Agent C 角色：{plan.agent_c_prompt}\n\n"
            f"输出要求：{plan.output_requirements}\n\n"
            "请在下方操作面板选择：确认方案，或者填写反馈后重新生成。"
        )

    def _format_requirement_message(self, *, clarified_requirement: str) -> str:
        return (
            "[创作模式] Agent A 需求理解\n\n"
            f"{clarified_requirement}\n\n"
            "请在下方操作面板选择：确认需求理解，或者填写反馈后重新生成。"
        )

    def _format_draft_message(self, *, round_index: int, draft: str) -> str:
        return (
            f"[创作模式] Agent A 文档草稿（第 {round_index} 轮）\n\n"
            f"{draft}\n\n"
            "请在下方操作面板选择：确认草稿进入 B/C 审查，或者填写反馈后继续修稿。"
        )

    def _format_bc_message(self, *, issues: list[str], judgement: str, reason: str) -> str:
        issue_lines = "\n".join(f"{idx}. {item}" for idx, item in enumerate(issues, start=1)) if issues else "无"
        return (
            "[创作模式] B/C 审查结果\n\n"
            f"Agent B 问题列表：\n{issue_lines}\n\n"
            f"Agent C 判定：{judgement}\n"
            f"判定理由：{reason}\n\n"
            "请在下方操作面板选择：直接定稿，或者进入下一轮 ABC。"
        )

    def _format_final_message(self, *, final_doc: str, write_id: str) -> str:
        return (
            "[创作模式] 终稿已完成\n\n"
            f"{final_doc}\n\n"
            f"已同步生成文档卡片，可直接下载（write_id={write_id}）。"
        )

    def _build_attachments_meta(self, *, file_refs: list[str]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for ref in file_refs:
            mongo_id = str(ref)
            filename = mongo_id
            try:
                detail = self._mongo.get_document_detail(doc_id=mongo_id)
                if isinstance(detail, dict) and detail.get("filename"):
                    filename = str(detail.get("filename"))
            except Exception:
                filename = mongo_id
            out.append({"mongo_id": mongo_id, "filename": filename})
        return out

    def start_run(
        self,
        *,
        session_id: str,
        assistant_id: str,
        user_prompt: str,
        file_refs: list[str] | None = None,
        checklist: list[str] | None = None,
    ) -> dict[str, Any]:
        session = str(session_id or "").strip()
        prompt = str(user_prompt or "").strip()
        if not session:
            raise CreativeAppError("CREATIVE_SESSION_REQUIRED", "session_id 不能为空")
        if not prompt:
            raise CreativeAppError("CREATIVE_PROMPT_REQUIRED", "text 不能为空")

        # 关键逻辑：start 接口只做轻量入库，重计算在后台执行，保证请求快速返回。
        plan = default_prompt_plan(prompt)

        run_id = str(generate_snowflake_id())
        now = get_beijing_time()
        chosen_checklist = [str(x) for x in (checklist or DEFAULT_CHECKLIST) if str(x).strip()]

        attachments_meta = self._build_attachments_meta(file_refs=file_refs or [])

        # 关键逻辑：创作模式首条消息也写入聊天表，保证“同一会话混排展示”。
        self._chat.save_user_message(
            thread_id=session,
            assistant_id=assistant_id,
            content=prompt,
            attachments=attachments_meta,
        )

        run_doc: dict[str, Any] = {
            "run_id": run_id,
            "session_id": session,
            "assistant_id": assistant_id,
            "status": "pre_agent_generating",
            "user_prompt": prompt,
            "file_refs": [str(x) for x in (file_refs or [])],
            "prompt_plan": {
                "content_goal": plan.content_goal,
                "agent_a_prompt": plan.agent_a_prompt,
                "agent_b_prompt": plan.agent_b_prompt,
                "agent_c_prompt": plan.agent_c_prompt,
                "output_requirements": plan.output_requirements,
            },
            "clarified_requirement": "",
            "checklist": chosen_checklist,
            "demo_doc": "",
            "issues": [],
            "c_judgement": "unreasonable",
            "c_reason": "",
            "final_doc": "",
            "round_index": 1,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        self._mongo.create_creative_run(run_doc=run_doc)

        self._append_assistant_message(
            run=run_doc,
            content="[创作模式] 已收到需求，Pre-Agent 正在生成方案，请稍候。",
        )

        return self._apply_and_build_run(run_doc, {"created_at": now, "updated_at": now})

    def process_start_run(
        self,
        *,
        run_id: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        if str(run.get("status")) not in {"pre_agent_generating", "pre_agent_pending_confirm"}:
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许生成 Pre-Agent 方案")

        planner = LlmPreAgentPlanner()
        plan = planner.plan(user_prompt=str(run.get("user_prompt") or ""), feedback="", on_chunk=on_chunk)
        now = get_beijing_time()
        updates = {
            "status": "pre_agent_pending_confirm",
            "prompt_plan": {
                "content_goal": plan.content_goal,
                "agent_a_prompt": plan.agent_a_prompt,
                "agent_b_prompt": plan.agent_b_prompt,
                "agent_c_prompt": plan.agent_c_prompt,
                "output_requirements": plan.output_requirements,
            },
            "updated_at": now,
        }
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        next_run = self._apply_and_build_run(run, updates)
        self._append_assistant_message(
            run=next_run,
            content=self._format_pre_agent_message(run_id=run_id, plan=plan),
        )
        return next_run

    def submit_pre_agent_decision(self, *, run_id: str, action: str, feedback: str) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        status = str(run.get("status") or "")
        if status == "pre_agent_processing":
            raise CreativeAppError("CREATIVE_RUN_BUSY", "当前任务正在处理中，请稍候")
        if status != "pre_agent_pending_confirm":
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理 Pre-Agent 决策")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"confirm", "regenerate"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 confirm/regenerate")

        now = get_beijing_time()
        updates = {"status": "pre_agent_processing", "updated_at": now}
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        return self._apply_and_build_run(run, updates)

    def submit_requirement_decision(self, *, run_id: str, action: str, feedback: str) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        status = str(run.get("status") or "")
        if status == "requirement_processing":
            raise CreativeAppError("CREATIVE_RUN_BUSY", "当前任务正在处理中，请稍候")
        if status != "requirement_pending_confirm":
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理需求确认")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"confirm", "revise"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 confirm/revise")
        if normalized_action == "revise" and not str(feedback or "").strip():
            raise CreativeAppError("CREATIVE_FEEDBACK_REQUIRED", "需要填写反馈后再重新生成需求理解")

        now = get_beijing_time()
        updates = {"status": "requirement_processing", "updated_at": now}
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        return self._apply_and_build_run(run, updates)

    def submit_draft_decision(self, *, run_id: str, action: str, feedback: str) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        status = str(run.get("status") or "")
        if status == "draft_processing":
            raise CreativeAppError("CREATIVE_RUN_BUSY", "当前任务正在处理中，请稍候")
        if status != "draft_pending_confirm":
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理草稿决策")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"confirm", "revise"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 confirm/revise")
        if normalized_action == "revise" and not str(feedback or "").strip():
            raise CreativeAppError("CREATIVE_FEEDBACK_REQUIRED", "需要填写反馈后再修订草稿")

        now = get_beijing_time()
        updates = {"status": "draft_processing", "updated_at": now}
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        return self._apply_and_build_run(run, updates)

    def submit_round_decision(self, *, run_id: str, action: str) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        status = str(run.get("status") or "")
        if status == "round_processing":
            raise CreativeAppError("CREATIVE_RUN_BUSY", "当前任务正在处理中，请稍候")
        if status != "bc_review_done":
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理轮次决策")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"finalize", "next_round"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 finalize/next_round")

        now = get_beijing_time()
        updates = {"status": "round_processing", "updated_at": now}
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        return self._apply_and_build_run(run, updates)

    def mark_async_failure(self, *, run_id: str, stage: str, error_message: str) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        current_status = str(run.get("status") or "")
        if current_status in {"completed", "cancelled", "error"}:
            return run

        stage_key = str(stage or "").strip().lower()
        fallback_status = {
            "start": "pre_agent_pending_confirm",
            "pre_agent": "pre_agent_pending_confirm",
            "requirement": "requirement_pending_confirm",
            "draft": "draft_pending_confirm",
            "round": "bc_review_done",
        }.get(stage_key, "error")

        now = get_beijing_time()
        updates: dict[str, Any] = {"status": fallback_status, "updated_at": now}
        if fallback_status == "error":
            updates["completed_at"] = now
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        next_run = self._apply_and_build_run(run, updates)
        self._append_assistant_message(
            run=next_run,
            content=f"[创作模式] 阶段处理失败：{str(error_message or '未知错误')}。\n请稍后重试。",
        )
        return next_run

    def pre_agent_decision(
        self,
        *,
        run_id: str,
        action: str,
        feedback: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        if str(run.get("status")) not in {"pre_agent_pending_confirm", "pre_agent_processing"}:
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理 Pre-Agent 决策")

        planner = LlmPreAgentPlanner()
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"confirm", "regenerate"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 confirm/regenerate")

        if normalized_action == "regenerate":
            self._append_user_action_message(
                run=run,
                stage="pre_agent",
                action="重新生成方案",
                feedback=feedback,
            )
            plan = planner.plan(
                user_prompt=str(run.get("user_prompt") or ""),
                feedback=str(feedback or ""),
                on_chunk=on_chunk,
            )
            now = get_beijing_time()
            updates = {
                "status": "pre_agent_pending_confirm",
                "prompt_plan": {
                    "content_goal": plan.content_goal,
                    "agent_a_prompt": plan.agent_a_prompt,
                    "agent_b_prompt": plan.agent_b_prompt,
                    "agent_c_prompt": plan.agent_c_prompt,
                    "output_requirements": plan.output_requirements,
                },
                "updated_at": now,
            }
            self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
            next_run = self._apply_and_build_run(run, updates)
            self._append_assistant_message(
                run=next_run,
                content=self._format_pre_agent_message(run_id=run_id, plan=plan),
            )
            return next_run

        self._append_user_action_message(run=run, stage="pre_agent", action="确认方案", feedback="")
        plan = self._plan_from_run(run)
        client = DeepCreativeAgentClient(
            run_id=run_id,
            prompt_plan=plan,
            workspace_root=self._workspace_root,
        )
        try:
            clarified = client.clarify_requirement(
                user_prompt=str(run.get("user_prompt") or ""),
                feedback="",
                on_chunk=on_chunk,
            )
        finally:
            client.close()

        now = get_beijing_time()
        updates = {
            "status": "requirement_pending_confirm",
            "clarified_requirement": clarified,
            "updated_at": now,
        }
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        next_run = self._apply_and_build_run(run, updates)
        self._append_assistant_message(
            run=next_run,
            content=self._format_requirement_message(clarified_requirement=clarified),
        )
        return next_run

    def requirement_decision(
        self,
        *,
        run_id: str,
        action: str,
        feedback: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        if str(run.get("status")) not in {"requirement_pending_confirm", "requirement_processing"}:
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理需求确认")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"confirm", "revise"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 confirm/revise")

        plan = self._plan_from_run(run)
        client = DeepCreativeAgentClient(
            run_id=run_id,
            prompt_plan=plan,
            workspace_root=self._workspace_root,
        )
        try:
            if normalized_action == "revise":
                if not str(feedback or "").strip():
                    raise CreativeAppError("CREATIVE_FEEDBACK_REQUIRED", "需要填写反馈后再重新生成需求理解")
                self._append_user_action_message(
                    run=run,
                    stage="requirement",
                    action="重新生成需求理解",
                    feedback=feedback,
                )
                clarified = client.clarify_requirement(
                    user_prompt=str(run.get("user_prompt") or ""),
                    feedback=str(feedback or ""),
                    on_chunk=on_chunk,
                )
                now = get_beijing_time()
                updates = {
                    "status": "requirement_pending_confirm",
                    "clarified_requirement": clarified,
                    "updated_at": now,
                }
                self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
                next_run = self._apply_and_build_run(run, updates)
                self._append_assistant_message(
                    run=next_run,
                    content=self._format_requirement_message(clarified_requirement=clarified),
                )
                return next_run

            self._append_user_action_message(run=run, stage="requirement", action="确认需求理解", feedback="")
            draft = client.draft_doc(
                user_prompt=str(run.get("user_prompt") or ""),
                clarified_requirement=str(run.get("clarified_requirement") or ""),
                issues=[str(x) for x in (run.get("issues") or [])],
                c_reason=str(run.get("c_reason") or ""),
                on_chunk=on_chunk,
            )
            now = get_beijing_time()
            updates = {
                "status": "draft_pending_confirm",
                "demo_doc": draft,
                "updated_at": now,
            }
            self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
            next_run = self._apply_and_build_run(run, updates)
            self._append_assistant_message(
                run=next_run,
                content=self._format_draft_message(round_index=int(next_run.get("round_index") or 1), draft=draft),
            )
            return next_run
        finally:
            client.close()

    def draft_decision(
        self,
        *,
        run_id: str,
        action: str,
        feedback: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        if str(run.get("status")) not in {"draft_pending_confirm", "draft_processing"}:
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理草稿决策")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"confirm", "revise"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 confirm/revise")

        plan = self._plan_from_run(run)
        client = DeepCreativeAgentClient(
            run_id=run_id,
            prompt_plan=plan,
            workspace_root=self._workspace_root,
        )
        try:
            if normalized_action == "revise":
                if not str(feedback or "").strip():
                    raise CreativeAppError("CREATIVE_FEEDBACK_REQUIRED", "需要填写反馈后再修订草稿")
                self._append_user_action_message(
                    run=run,
                    stage="draft",
                    action="继续修稿",
                    feedback=feedback,
                )
                issues = [str(x) for x in (run.get("issues") or [])]
                issues.append(f"用户反馈: {str(feedback).strip()}")
                c_reason = "用户要求先修订初稿后再送审"
                draft = client.draft_doc(
                    user_prompt=str(run.get("user_prompt") or ""),
                    clarified_requirement=str(run.get("clarified_requirement") or ""),
                    issues=issues,
                    c_reason=c_reason,
                    on_chunk=on_chunk,
                )
                now = get_beijing_time()
                updates = {
                    "status": "draft_pending_confirm",
                    "demo_doc": draft,
                    "issues": issues,
                    "c_reason": c_reason,
                    "updated_at": now,
                }
                self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
                next_run = self._apply_and_build_run(run, updates)
                self._append_assistant_message(
                    run=next_run,
                    content=self._format_draft_message(round_index=int(next_run.get("round_index") or 1), draft=draft),
                )
                return next_run

            self._append_user_action_message(run=run, stage="draft", action="确认草稿并进入 B/C 审查", feedback="")
            issues = client.review_doc(
                user_prompt=str(run.get("user_prompt") or ""),
                clarified_requirement=str(run.get("clarified_requirement") or ""),
                demo_doc=str(run.get("demo_doc") or ""),
                checklist=[str(x) for x in (run.get("checklist") or [])],
                c_reason=str(run.get("c_reason") or ""),
                on_chunk=on_chunk,
            )
            judgement, reason = client.judge_issues(
                user_prompt=str(run.get("user_prompt") or ""),
                clarified_requirement=str(run.get("clarified_requirement") or ""),
                demo_doc=str(run.get("demo_doc") or ""),
                issues=issues,
                on_chunk=on_chunk,
            )
            now = get_beijing_time()
            updates = {
                "status": "bc_review_done",
                "issues": issues,
                "c_judgement": judgement,
                "c_reason": reason,
                "updated_at": now,
            }
            self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
            next_run = self._apply_and_build_run(run, updates)
            self._append_assistant_message(
                run=next_run,
                content=self._format_bc_message(issues=issues, judgement=judgement, reason=reason),
            )
            return next_run
        finally:
            client.close()

    def round_decision(
        self,
        *,
        run_id: str,
        action: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        run = self._load_run(run_id=run_id)
        if str(run.get("status")) not in {"bc_review_done", "round_processing"}:
            raise CreativeAppError("CREATIVE_STATE_INVALID", "当前状态不允许处理轮次决策")

        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"finalize", "next_round"}:
            raise CreativeAppError("CREATIVE_ACTION_INVALID", "action 仅支持 finalize/next_round")

        if normalized_action == "finalize":
            self._append_user_action_message(run=run, stage="round", action="直接定稿", feedback="")
            final_doc = str(run.get("demo_doc") or "").strip()
            if not final_doc:
                raise CreativeAppError("CREATIVE_FINAL_EMPTY", "当前草稿为空，无法定稿")

            file_name = f"创作模式终稿-{run_id}.md"
            file_path = f"/workspace/{file_name}"
            file_size = len(final_doc.encode("utf-8"))
            write_id = self._mongo.save_filesystem_write(
                session_id=str(run.get("session_id") or ""),
                file_path=file_path,
                content=final_doc,
                metadata={
                    "title": file_name,
                    "type": "md",
                    "size": file_size,
                },
            )
            self._mongo.save_creative_final_doc(
                run_id=run_id,
                session_id=str(run.get("session_id") or ""),
                assistant_id=str(run.get("assistant_id") or "agent"),
                content=final_doc,
                title=file_name,
                write_id=write_id,
            )

            # 关键逻辑：补一条 tool 消息，复用现有前端“文档卡片绑定”机制。
            tool_time = get_beijing_time()
            self._mongo.append_chat_message(
                thread_id=str(run.get("session_id") or ""),
                assistant_id=str(run.get("assistant_id") or "agent"),
                role="tool",
                content="",
                tool_call_id=f"creative_final_write_{run_id}",
                tool_name="save_filesystem_write",
                tool_args={"file_path": file_path, "title": file_name},
                tool_status="done",
                tool_output={
                    "status": "success",
                    "write_id": write_id,
                    "title": file_name,
                    "type": "md",
                    "size": file_size,
                    "file_path": file_path,
                },
                started_at=tool_time,
                ended_at=tool_time,
            )

            completed_at = get_beijing_time()
            updates = {
                "status": "completed",
                "final_doc": final_doc,
                "completed_at": completed_at,
                "updated_at": completed_at,
                "final_write_id": write_id,
            }
            self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
            next_run = self._apply_and_build_run(run, updates)
            self._append_assistant_message(
                run=next_run,
                content=self._format_final_message(final_doc=final_doc, write_id=write_id),
            )
            return next_run

        self._append_user_action_message(run=run, stage="round", action="进入下一轮 ABC", feedback="")
        plan = self._plan_from_run(run)
        client = DeepCreativeAgentClient(
            run_id=run_id,
            prompt_plan=plan,
            workspace_root=self._workspace_root,
        )
        try:
            next_round_index = int(run.get("round_index") or 1) + 1
            draft = client.draft_doc(
                user_prompt=str(run.get("user_prompt") or ""),
                clarified_requirement=str(run.get("clarified_requirement") or ""),
                issues=[str(x) for x in (run.get("issues") or [])],
                c_reason=str(run.get("c_reason") or ""),
                on_chunk=on_chunk,
            )
        finally:
            client.close()

        now = get_beijing_time()
        updates = {
            "status": "draft_pending_confirm",
            "round_index": next_round_index,
            "demo_doc": draft,
            "updated_at": now,
        }
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        next_run = self._apply_and_build_run(run, updates)
        self._append_assistant_message(
            run=next_run,
            content=self._format_draft_message(round_index=next_round_index, draft=draft),
        )
        return next_run

    def get_run(self, *, run_id: str) -> dict[str, Any]:
        return self._load_run(run_id=run_id)

    def list_runs(
        self,
        *,
        session_id: str,
        assistant_id: str = "agent",
        active_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self._mongo.list_creative_runs(
            session_id=session_id,
            assistant_id=assistant_id,
            active_only=active_only,
            limit=limit,
        )

    def cancel_run(self, *, run_id: str, reason: str = "") -> dict[str, Any]:
        """取消指定创作任务。"""
        run = self._load_run(run_id=run_id)
        status = str(run.get("status") or "")
        if status in {"completed", "cancelled", "error"}:
            return run

        current = self._load_run(run_id=run_id)
        current_status = str(current.get("status") or "")
        if current_status in {"completed", "cancelled", "error"}:
            return current

        self._append_user_action_message(
            run=current,
            stage="run",
            action="取消创作任务",
            feedback=str(reason or "").strip(),
        )

        now = get_beijing_time()
        updates = {
            "status": "cancelled",
            "completed_at": now,
            "updated_at": now,
        }
        self._mongo.update_creative_run(run_id=run_id, set_fields=updates)
        next_run = self._apply_and_build_run(current, updates)
        self._append_assistant_message(
            run=next_run,
            content="[创作模式] 当前任务已取消。你可以继续发送新需求发起下一次创作。",
        )
        return next_run

    def cancel_active_run(
        self,
        *,
        session_id: str,
        assistant_id: str = "agent",
        reason: str = "",
    ) -> dict[str, Any]:
        """取消某会话下最近一个进行中的创作任务。"""
        runs = self._mongo.list_creative_runs(
            session_id=str(session_id),
            assistant_id=str(assistant_id),
            active_only=True,
            limit=1,
        )
        if not runs:
            raise CreativeAppError("CREATIVE_RUN_NOT_FOUND", "当前会话没有进行中的创作任务")
        run_id = str(runs[0].get("run_id") or "").strip()
        if not run_id:
            raise CreativeAppError("CREATIVE_RUN_NOT_FOUND", "当前会话没有可取消的创作任务")
        return self.cancel_run(run_id=run_id, reason=reason)
