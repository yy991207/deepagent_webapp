import asyncio

from backend.api.routers import creative_router


async def _collect_sse_text(resp) -> str:
    parts: list[str] = []
    async for part in resp.body_iterator:
        if isinstance(part, bytes):
            parts.append(part.decode("utf-8"))
        else:
            parts.append(str(part))
    return "".join(parts)


def test_start_stream_route_returns_sse_chunks(monkeypatch):
    class FakeService:
        def start_run(self, **kwargs):
            return {"run_id": "r-100", "status": "pre_agent_generating"}

        def process_start_run(self, *, run_id: str, on_chunk=None):
            if on_chunk:
                on_chunk("chunk-a")
                on_chunk("chunk-b")
            return {"run_id": run_id, "status": "pre_agent_pending_confirm"}

        def mark_async_failure(self, *, run_id: str, stage: str, error_message: str):
            return {"run_id": run_id, "status": "error"}

    monkeypatch.setattr(creative_router, "_service", lambda: FakeService())

    resp = creative_router.creative_run_start_stream(
        {"text": "写一个产品介绍", "session_id": "s-100", "assistant_id": "agent"},
    )

    merged = asyncio.run(_collect_sse_text(resp))
    assert '"type": "ack"' in merged
    assert '"type": "chunk"' in merged
    assert '"chunk-a"' in merged
    assert '"type": "done"' in merged


def test_requirement_stream_route_returns_sse_chunks(monkeypatch):
    class FakeService:
        def submit_requirement_decision(self, *, run_id: str, action: str, feedback: str):
            return {"run_id": run_id, "status": "requirement_processing"}

        def requirement_decision(self, *, run_id: str, action: str, feedback: str, on_chunk=None):
            if on_chunk:
                on_chunk("draft-1")
                on_chunk("draft-2")
            return {"run_id": run_id, "status": "draft_pending_confirm"}

        def mark_async_failure(self, *, run_id: str, stage: str, error_message: str):
            return {"run_id": run_id, "status": "error"}

    monkeypatch.setattr(creative_router, "_service", lambda: FakeService())

    resp = creative_router.creative_requirement_decision_stream(
        "r-200",
        {"action": "confirm", "feedback": ""},
    )

    merged = asyncio.run(_collect_sse_text(resp))
    assert '"type": "ack"' in merged
    assert '"type": "chunk"' in merged
    assert '"draft-1"' in merged
    assert '"type": "done"' in merged
