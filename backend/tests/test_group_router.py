import asyncio
import json
from types import SimpleNamespace

from backend.api.routers import group_router


async def _collect_sse_text(resp) -> str:
    parts: list[str] = []
    async for part in resp.body_iterator:
        if isinstance(part, bytes):
            parts.append(part.decode("utf-8"))
        else:
            parts.append(str(part))
    return "".join(parts)


def _parse_sse_events(payload_text: str) -> list[dict]:
    events: list[dict] = []
    for line in payload_text.splitlines():
        if not line.startswith("data: "):
            continue
        events.append(json.loads(line[6:]))
    return events


def test_group_stream_route_should_emit_character_event_and_clean_delta(monkeypatch):
    req1 = SimpleNamespace(
        speaker={
            "speaker_type": "agent",
            "speaker_id": "agent_2",
            "speaker_name": "周老师",
            "speaker_title": "教师",
            "speaker_personality": "耐心严谨",
        },
        style_hint="自然接话",
    )
    req2 = SimpleNamespace(
        speaker={
            "speaker_type": "agent",
            "speaker_id": "agent_4",
            "speaker_name": "小顾",
            "speaker_title": "产品经理",
            "speaker_personality": "沟通导向",
        },
        style_hint="简短直接",
    )

    class FakeGroupService:
        def __init__(self) -> None:
            self.enqueue_payload: dict[str, str] | None = None

        def enqueue_user_message(self, *, session_id: str, user_text: str):
            self.enqueue_payload = {
                "session_id": session_id,
                "user_text": user_text,
            }
            return [req1, req2]

        def drain_requests(self, *, session_id: str):
            assert session_id == "s-100"
            return [req1, req2]

        def build_group_prompt(self, **kwargs):
            speaker = kwargs["speaker"]
            queue_index = kwargs["queue_index"]
            return f"[GROUP-{queue_index}]{speaker['speaker_name']}"

    fake_group = FakeGroupService()
    captured_calls: list[dict[str, object]] = []

    class FakeChatStreamService:
        async def stream_chat(self, **kwargs):
            captured_calls.append(kwargs)
            speaker = kwargs["assistant_speaker"]
            yield {
                "type": "message.start",
                "message_id": f"m-{speaker['speaker_id']}",
                "speaker_type": "agent",
                "speaker_id": speaker["speaker_id"],
                "speaker_name": speaker["speaker_name"],
            }
            yield {
                "type": "chat.delta",
                "text": f"[群聊模式][角色={speaker['speaker_name']}] 在批改学生作文",
            }
            yield {"type": "session.status", "status": "done"}

    monkeypatch.setattr(group_router, "_group_service", lambda: fake_group)
    monkeypatch.setattr(group_router, "_chat_service", lambda: FakeChatStreamService())

    resp = asyncio.run(
        group_router.group_chat_stream_sse(
            {
                "text": "聊聊课程设计",
                "session_id": "s-100",
                "assistant_id": "agent",
                "files": ["f1"],
                "preferred_agent_id": "agent_2",
            }
        )
    )

    merged = asyncio.run(_collect_sse_text(resp))
    events = _parse_sse_events(merged)

    character_events = [event for event in events if event.get("type") == "character"]
    assert len(character_events) == 2
    assert character_events[0]["character"]["speaker_id"] == "agent_2"
    assert character_events[1]["character"]["speaker_id"] == "agent_4"

    delta_events = [event for event in events if event.get("type") == "chat.delta"]
    assert delta_events
    assert "[群聊模式]" not in delta_events[0]["text"]
    assert "[角色=" not in delta_events[0]["text"]
    assert delta_events[0]["speaker_id"] == "agent_2"

    assert fake_group.enqueue_payload == {
        "session_id": "s-100",
        "user_text": "聊聊课程设计",
    }

    assert len(captured_calls) == 2
    assert captured_calls[0]["text"] == "[GROUP-1]周老师"
    assert captured_calls[1]["text"] == "[GROUP-2]小顾"
    assert captured_calls[0]["persist_user_message"] is True
    assert captured_calls[1]["persist_user_message"] is False
    assert captured_calls[0]["emit_suggested_questions"] is False
    assert captured_calls[1]["emit_suggested_questions"] is True
