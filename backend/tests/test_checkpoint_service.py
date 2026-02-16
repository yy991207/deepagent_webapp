from pathlib import Path
import asyncio

from backend.services import checkpoint_service
from backend.services.checkpoint_service import CheckpointService


def test_delete_session_should_not_fail_when_checkpoint_tables_missing(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "empty_sessions.db"
    db_path.touch()

    monkeypatch.setattr(checkpoint_service, "get_db_path", lambda: db_path)

    service = CheckpointService()

    result = asyncio.run(service.delete_session(session_id="sse-check-001"))

    assert result.deleted_checkpoints == 0
    assert result.deleted_writes == 0


def test_cleanup_keep_last_should_not_fail_when_checkpoint_tables_missing(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "empty_sessions.db"
    db_path.touch()

    monkeypatch.setattr(checkpoint_service, "get_db_path", lambda: db_path)

    service = CheckpointService(keep_last=20)

    result = asyncio.run(service.cleanup_keep_last(session_id="sse-check-001"))

    assert result.deleted_checkpoints == 0
    assert result.deleted_writes == 0
