from pathlib import Path

from backend.middleware import rag_middleware
from backend.middleware.rag_middleware import LlamaIndexRagMiddleware


class _FakeMongo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_document_bytes(self, *, doc_id: str):  # noqa: ANN001
        return None

    def get_filesystem_write(self, *, write_id: str, session_id: str):  # noqa: ANN001
        self.calls.append((session_id, write_id))
        if write_id != "w-001":
            return None
        return {
            "write_id": write_id,
            "session_id": session_id,
            "file_path": "reports/demo.md",
            "content": "这是来自 filesystem_writes 的测试内容",
            "metadata": {"type": "md"},
        }


def test_iter_mongo_documents_should_support_filesystem_write_ref(tmp_path: Path, monkeypatch):
    fake_mongo = _FakeMongo()
    monkeypatch.setattr(rag_middleware, "get_mongo_manager", lambda: fake_mongo)

    middleware = LlamaIndexRagMiddleware(
        assistant_id="agent",
        workspace_root=tmp_path,
        source_files=["fsw:s-001:w-001"],
        persist_dir=tmp_path / "rag-index",
    )

    docs = middleware._iter_mongo_documents()

    assert docs is not None
    assert len(docs) == 1
    assert docs[0]["id"] == "fsw:s-001:w-001"
    assert docs[0]["meta"]["filename"] == "demo.md"
    assert docs[0]["bytes"].decode("utf-8") == "这是来自 filesystem_writes 的测试内容"
    assert fake_mongo.calls == [("s-001", "w-001")]
