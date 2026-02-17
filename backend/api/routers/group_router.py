from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.services.chat_stream_service import ChatStreamService
from backend.services.group_chat_service import GroupChatService
from backend.utils.snowflake import generate_snowflake_id


router = APIRouter()
logger = logging.getLogger(__name__)

# group_router.py 位于 backend/api/routers/，上 4 层到项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

_GROUP_SERVICE: GroupChatService | None = None
_ROLE_TAG_PREFIX_RE = re.compile(r"^\[(?:群聊模式|角色=[^\]]+)\]\s*")


class _DeltaPrefixCleaner:
    """清理模型把角色标签写进正文的前缀。"""

    def __init__(self) -> None:
        self._buffer = ""
        self._done = False

    def consume(self, text: str) -> str:
        chunk = str(text or "")
        if self._done:
            return chunk

        self._buffer += chunk
        matched = False
        while True:
            match = _ROLE_TAG_PREFIX_RE.match(self._buffer)
            if not match:
                break
            matched = True
            self._buffer = self._buffer[match.end() :]

        # 关键逻辑：如果仍是疑似未闭合标签，先继续缓存，避免把残缺标签透传给前端。
        if self._buffer.startswith("[") and "]" not in self._buffer and len(self._buffer) < 64:
            return ""

        if matched and not self._buffer:
            return ""

        out = self._buffer
        self._buffer = ""
        self._done = True
        return out.lstrip() if matched else out


def _chat_service() -> ChatStreamService:
    return ChatStreamService(base_dir=BASE_DIR)


def _group_service() -> GroupChatService:
    global _GROUP_SERVICE
    if _GROUP_SERVICE is None:
        _GROUP_SERVICE = GroupChatService()
    return _GROUP_SERVICE


@router.get("/api/group/members")
def group_members() -> dict[str, Any]:
    svc = _group_service()
    members = [
        {
            "speaker_id": x.speaker_id,
            "speaker_name": x.speaker_name,
            "speaker_title": x.speaker_title,
            "speaker_personality": x.speaker_personality,
        }
        for x in svc.members()
    ]
    return {"members": members, "total": len(members)}


@router.post("/api/group/stream")
async def group_chat_stream_sse(payload: dict[str, Any]) -> StreamingResponse:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    session_id = str(payload.get("session_id") or generate_snowflake_id())
    assistant_id = str(payload.get("assistant_id") or "agent")

    file_refs_raw = payload.get("files")
    file_refs: list[str] = []
    if isinstance(file_refs_raw, list):
        file_refs = [str(x) for x in file_refs_raw if str(x).strip()]

    group_svc = _group_service()
    group_svc.enqueue_user_message(
        session_id=session_id,
        user_text=text,
    )
    queue = group_svc.drain_requests(session_id=session_id)

    # 关键逻辑：群聊采用“先入队后顺序消费”，每个发言请求都严格按 FIFO 执行。
    # 这样既支持自由发言选人，也不会打乱消息顺序。
    chat_svc = _chat_service()

    async def event_generator():
        start_event = {"type": "session.status", "status": "thinking", "session_id": session_id}
        yield f"data: {json.dumps(start_event, ensure_ascii=False)}\n\n"

        if not queue:
            done_event = {"type": "session.status", "status": "done", "session_id": session_id}
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
            return

        prior_replies: list[dict[str, str]] = []
        total = len(queue)

        for idx, req in enumerate(queue, start=1):
            speaker = req.speaker
            style_hint = req.style_hint
            cleaner = _DeltaPrefixCleaner()

            character_event = {
                "type": "character",
                "character": speaker,
                "queue_index": idx,
                "queue_total": total,
                "session_id": session_id,
            }
            yield f"data: {json.dumps(character_event, ensure_ascii=False)}\n\n"

            prompt = group_svc.build_group_prompt(
                user_text=text,
                speaker=speaker,
                style_hint=style_hint,
                queue_index=idx,
                queue_total=total,
                prior_replies=prior_replies,
            )

            assistant_chunks: list[str] = []

            try:
                async for event in chat_svc.stream_chat(
                    text=prompt,
                    thread_id=session_id,
                    assistant_id=assistant_id,
                    file_refs=file_refs,
                    assistant_speaker=speaker,
                    user_speaker={"speaker_type": "user", "speaker_name": "你"},
                    persist_user_message=(idx == 1),
                    persist_chat_memory=(idx == total),
                    memory_user_text=text,
                    emit_suggested_questions=(idx == total),
                ):
                    if not isinstance(event, dict):
                        continue
                    event_type = str(event.get("type") or "")
                    if event_type == "session.status":
                        # 群聊层统一发 session.status，避免子流把状态来回覆盖。
                        continue
                    if event_type == "chat.delta":
                        clean_text = cleaner.consume(str(event.get("text") or ""))
                        if not clean_text:
                            continue
                        event["text"] = clean_text
                        event["speaker_type"] = str(speaker.get("speaker_type") or "agent")
                        event["speaker_id"] = str(speaker.get("speaker_id") or "")
                        event["speaker_name"] = str(speaker.get("speaker_name") or "")
                        event["speaker_title"] = str(speaker.get("speaker_title") or "")
                        event["speaker_personality"] = str(speaker.get("speaker_personality") or "")
                        assistant_chunks.append(clean_text)

                    event["session_id"] = session_id
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:  # noqa: BLE001
                logger.exception("group chat speaker failed | session_id=%s | speaker=%s", session_id, speaker)
                err = {
                    "type": "error",
                    "message": f"{speaker.get('speaker_name') or '角色'} 发言失败：{str(exc) or 'unknown'}",
                    "session_id": session_id,
                }
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

            reply_text = "".join(assistant_chunks).strip()
            if reply_text:
                prior_replies.append(
                    {
                        "speaker_name": str(speaker.get("speaker_name") or "角色"),
                        "text": reply_text,
                    }
                )

        done_event = {"type": "session.status", "status": "done", "session_id": session_id}
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
