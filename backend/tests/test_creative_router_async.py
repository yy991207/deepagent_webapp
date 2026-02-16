from fastapi import BackgroundTasks

from backend.api.routers import creative_router


def test_start_route_returns_immediately_and_defer_heavy_work(monkeypatch):
    calls: list[str] = []

    class FakeService:
        def start_run(self, **kwargs):
            calls.append("start_run")
            return {"run_id": "r-1", "status": "pre_agent_generating"}

        def process_start_run(self, *, run_id: str):
            calls.append(f"process_start_run:{run_id}")

        def mark_async_failure(self, *, run_id: str, stage: str, error_message: str):
            calls.append(f"mark_async_failure:{run_id}:{stage}")

    fake = FakeService()
    monkeypatch.setattr(creative_router, "_service", lambda: fake)

    background_tasks = BackgroundTasks()
    resp = creative_router.creative_run_start(
        {"text": "写一篇产品说明", "session_id": "s-1", "assistant_id": "agent"},
        background_tasks,
    )

    assert resp["success"] is True
    assert resp["run"]["status"] == "pre_agent_generating"
    assert calls == ["start_run"]

    for task in background_tasks.tasks:
        task.func(*task.args, **task.kwargs)

    assert calls == ["start_run", "process_start_run:r-1"]


def test_requirement_route_returns_processing_then_background_execute(monkeypatch):
    calls: list[str] = []

    class FakeService:
        def submit_requirement_decision(self, *, run_id: str, action: str, feedback: str):
            calls.append(f"submit:{run_id}:{action}:{feedback}")
            return {"run_id": run_id, "status": "requirement_processing"}

        def requirement_decision(self, *, run_id: str, action: str, feedback: str):
            calls.append(f"execute:{run_id}:{action}:{feedback}")
            return {"run_id": run_id, "status": "draft_pending_confirm"}

        def mark_async_failure(self, *, run_id: str, stage: str, error_message: str):
            calls.append(f"mark_async_failure:{run_id}:{stage}")

    fake = FakeService()
    monkeypatch.setattr(creative_router, "_service", lambda: fake)

    background_tasks = BackgroundTasks()
    resp = creative_router.creative_requirement_decision(
        "r-2",
        {"action": "confirm", "feedback": ""},
        background_tasks,
    )

    assert resp["success"] is True
    assert resp["run"]["status"] == "requirement_processing"
    assert calls == ["submit:r-2:confirm:"]

    for task in background_tasks.tasks:
        task.func(*task.args, **task.kwargs)

    assert calls == [
        "submit:r-2:confirm:",
        "execute:r-2:confirm:",
    ]
