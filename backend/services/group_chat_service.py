from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class GroupMember:
    speaker_id: str
    speaker_name: str
    speaker_title: str
    speaker_personality: str


@dataclass(frozen=True)
class GroupSpeakRequest:
    request_id: str
    session_id: str
    enqueue_ts_ns: int
    enqueue_seq: int
    speaker: dict[str, str]
    style_hint: str


class GroupChatService:
    """群聊模式服务（最小侵入版）。

    说明：
    - 固定 5 个预设角色
    - 支持“自由发言”的动态选人
    - 通过会话队列按 FIFO 顺序消费发言请求
    """

    _STYLE_HINTS = (
        "先共情再给建议，语气自然，有一点生活化表达",
        "先说结论再补一两句理由，简短有力，不要官腔",
        "像真实群聊里接话，先回应上一位观点，再补充新信息",
        "可以带轻微口语停顿词（比如“我觉得”“其实”），但不要重复模板",
        "像熟人聊天，语气温和，句子长短有变化，不要机械平铺",
    )

    def __init__(self) -> None:
        self._members: tuple[GroupMember, ...] = (
            GroupMember("agent_1", "林医生", "医生", "理性温和"),
            GroupMember("agent_2", "周老师", "教师", "耐心严谨"),
            GroupMember("agent_3", "阿程", "程序员", "直接务实"),
            GroupMember("agent_4", "小顾", "产品经理", "沟通导向"),
            GroupMember("agent_5", "阿青", "设计师", "审美敏锐"),
        )
        self._cursor_by_session: dict[str, int] = {}
        self._queue_by_session: dict[str, deque[GroupSpeakRequest]] = {}
        self._global_seq = 0
        self._lock = Lock()

    def members(self) -> tuple[GroupMember, ...]:
        return self._members

    def pick_speaker(self, *, session_id: str) -> dict[str, str]:
        """返回当前轮第一个发言人（兼容旧调用）。"""
        speakers = self._plan_speakers(
            session_id=session_id,
            user_text="",
            min_count=1,
            max_count=1,
        )
        return speakers[0]

    def enqueue_user_message(
        self,
        *,
        session_id: str,
        user_text: str,
    ) -> list[GroupSpeakRequest]:
        """根据用户输入生成一轮发言请求并入队。"""
        speakers = self._plan_speakers(
            session_id=session_id,
            user_text=user_text,
            min_count=2,
            max_count=5,
        )

        sid = str(session_id or "").strip() or "default"
        created: list[GroupSpeakRequest] = []

        with self._lock:
            q = self._queue_by_session.setdefault(sid, deque())
            base_ts = time.monotonic_ns()
            for idx, speaker in enumerate(speakers):
                self._global_seq += 1
                seq = self._global_seq
                request = GroupSpeakRequest(
                    request_id=f"{sid}-{seq}",
                    session_id=sid,
                    enqueue_ts_ns=base_ts + idx,
                    enqueue_seq=seq,
                    speaker=speaker,
                    style_hint=self._style_hint_for(session_id=sid, speaker_id=speaker["speaker_id"], order=idx),
                )
                q.append(request)
                created.append(request)

        return created

    def drain_requests(self, *, session_id: str) -> list[GroupSpeakRequest]:
        """按 FIFO 顺序取出当前会话待处理发言请求。"""
        sid = str(session_id or "").strip() or "default"
        with self._lock:
            q = self._queue_by_session.get(sid)
            if not q:
                return []
            out: list[GroupSpeakRequest] = []
            while q:
                out.append(q.popleft())
            return out

    def build_group_prompt(
        self,
        *,
        user_text: str,
        speaker: dict[str, str],
        style_hint: str,
        queue_index: int,
        queue_total: int,
        prior_replies: list[dict[str, str]] | None = None,
    ) -> str:
        """构建群聊模式输入提示词。"""

        members_text = "；".join(
            f"{x.speaker_name}({x.speaker_title},{x.speaker_personality})" for x in self._members
        )

        lines = [
            "你正在处理一个群聊模式请求。",
            "规则：仅回复 user 消息；不要代替 user 说话；不要输出 JSON。",
            "规则：每次只输出当前角色的发言，不要替其他角色发言。",
            "规则：发言口吻要像真人群聊，避免固定模板和重复句式。",
            "规则：角色信息由系统结构化字段提供，不要在正文中输出任何角色标签（例如[角色=xx]）。",
            f"当前群成员：{members_text}",
            f"本轮发言队列：第 {queue_index}/{queue_total} 位",
            f"当前角色：{speaker.get('speaker_name')}（{speaker.get('speaker_title')}，{speaker.get('speaker_personality')}）",
            f"风格提示：{style_hint}",
        ]

        if prior_replies:
            lines.append("前序发言摘要（可接话，可补充，不要重复）：")
            for item in prior_replies[-2:]:
                lines.append(f"- {item.get('speaker_name')}: {item.get('text')}")

        lines.extend(
            [
                "输出要求：1~3 段，优先短句自然表达，可有轻微口语停顿，但不要流水账。",
                f"用户消息：{str(user_text or '').strip()}",
            ]
        )

        return "\n".join(lines).strip()

    def _style_hint_for(self, *, session_id: str, speaker_id: str, order: int) -> str:
        mix = abs(hash(f"{session_id}:{speaker_id}:{order}"))
        idx = mix % len(self._STYLE_HINTS)
        return self._STYLE_HINTS[idx]

    def _plan_speakers(
        self,
        *,
        session_id: str,
        user_text: str,
        min_count: int,
        max_count: int,
    ) -> list[dict[str, str]]:
        sid = str(session_id or "").strip() or "default"
        text = str(user_text or "").strip().lower()

        ranked = sorted(
            self._members,
            key=lambda m: self._score_member(member=m, text=text),
            reverse=True,
        )

        with self._lock:
            turn_cursor = self._cursor_by_session.get(sid, 0)
            self._cursor_by_session[sid] = turn_cursor + 1

        # 关键逻辑：通过轮转候选顺序实现“自由发言”，避免固定“优先 + 紧邻下一个”。
        rotate = turn_cursor % len(ranked)
        rotated = [*ranked[rotate:], *ranked[:rotate]]

        speaker_count = self._choose_speaker_count(
            text=text,
            turn_cursor=turn_cursor,
            min_count=min_count,
            max_count=max_count,
        )

        out: list[GroupMember] = []
        for member in rotated:
            if len(out) >= speaker_count:
                break
            out.append(member)

        if not out:
            out = [self._members[0]]

        return [
            {
                "speaker_type": "agent",
                "speaker_id": m.speaker_id,
                "speaker_name": m.speaker_name,
                "speaker_title": m.speaker_title,
                "speaker_personality": m.speaker_personality,
            }
            for m in out
        ]

    def _choose_speaker_count(self, *, text: str, turn_cursor: int, min_count: int, max_count: int) -> int:
        """根据语义和会话轮次动态决定发言人数，避免长期固定两人。"""
        member_limit = len(self._members)
        low = max(1, min(min_count, member_limit))
        high = max(low, min(max_count, member_limit))

        count = 2 + (turn_cursor % 2)
        if len(text) >= 24:
            count += 1
        if len(text) >= 64:
            count += 1
        if any(x in text for x in ("大家", "你们", "都", "一起", "各自", "分别", "每个人", "群里")):
            count += 1
        if any(x in text for x in ("?", "？", "怎么看", "建议", "方案", "想法", "意见")):
            count += 1

        return max(low, min(high, count))

    def _score_member(self, *, member: GroupMember, text: str) -> float:
        score = 1.0
        if not text:
            return score

        role_keywords = {
            "医生": ("健康", "医院", "体检", "症状", "焦虑"),
            "教师": ("学习", "考试", "课堂", "教育", "作业"),
            "程序员": ("系统", "接口", "性能", "代码", "bug"),
            "产品经理": ("需求", "用户", "上线", "反馈", "版本"),
            "设计师": ("配色", "排版", "风格", "视觉", "交互"),
        }

        if member.speaker_title in text:
            score += 2.0

        for kw in role_keywords.get(member.speaker_title, ()):
            if kw in text:
                score += 0.8

        if member.speaker_personality[:2] in text:
            score += 0.4

        return score
