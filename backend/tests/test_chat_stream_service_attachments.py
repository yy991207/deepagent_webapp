from pathlib import Path

from backend.services.chat_stream_service import ChatStreamService


class _FakeMongo:
    def get_filesystem_write(self, *, write_id: str, session_id: str):  # noqa: ANN001
        if write_id != "w-001" or session_id != "s-001":
            return None
        return {
            "file_path": "outputs/设计方案.md",
            "metadata": {"title": "设计方案.md"},
        }

    def get_document_detail(self, *, doc_id: str):  # noqa: ANN001
        if doc_id != "mongo-1":
            return None
        return {"filename": "需求文档.md"}


def test_build_attachments_meta_should_support_filesystem_write_ref(tmp_path: Path):
    service = ChatStreamService(base_dir=tmp_path)

    result = service._build_attachments_meta(
        mongo=_FakeMongo(),
        file_refs=["mongo-1", "fsw:s-001:w-001"],
    )

    assert result == [
        {"mongo_id": "mongo-1", "filename": "需求文档.md"},
        {"mongo_id": "fsw:s-001:w-001", "filename": "设计方案.md"},
    ]
