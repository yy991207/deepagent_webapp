from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from bson.binary import Binary
from bson.objectid import ObjectId
from pymongo import MongoClient


# 东八区北京时区
BEIJING_TZ = timezone(timedelta(hours=8))


def get_beijing_time() -> datetime:
    """获取东八区北京时间"""
    return datetime.now(BEIJING_TZ)


@dataclass(frozen=True)
class StoredDocument:
    id: str
    sha256: str
    filename: str
    rel_path: str
    size: int


@dataclass(frozen=True)
class StoredDocumentSummary:
    id: str
    sha256: str
    filename: str
    rel_path: str
    size: int
    created_at: str


class MongoDbManager:
    def __init__(
        self,
        *,
        mongo_url: str,
        db_name: str,
        collection_name: str,
    ) -> None:
        self._mongo_url = mongo_url
        self._db_name = db_name
        self._collection_name = collection_name
        self._client: MongoClient | None = None

    def _get_client(self) -> MongoClient:
        if self._client is None:
            self._client = MongoClient(self._mongo_url)
        return self._client

    def _collection(self):
        client = self._get_client()
        return client[self._db_name][self._collection_name]

    def _chat_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_CHAT_COLLECTION]

    def _chat_memory_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_CHAT_MEMORY_COLLECTION]

    def store_file(
        self,
        *,
        filename: str,
        rel_path: str,
        content_bytes: bytes,
    ) -> StoredDocument:
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        size = len(content_bytes)

        doc: dict[str, Any] = {
            "sha256": sha256,
            "filename": filename,
            "rel_path": rel_path,
            "size": size,
            "content": Binary(content_bytes),
            "created_at": datetime.now(timezone.utc),
        }

        collection = self._collection()
        result = collection.insert_one(doc)

        return StoredDocument(
            id=str(result.inserted_id),
            sha256=sha256,
            filename=filename,
            rel_path=rel_path,
            size=size,
        )

    def list_documents(
        self,
        *,
        q: str | None = None,
        limit: int = 200,
        skip: int = 0,
    ) -> list[StoredDocumentSummary]:
        query: dict[str, Any] = {}
        if q and q.strip():
            query["filename"] = {"$regex": q.strip(), "$options": "i"}

        projection = {
            "content": 0,
        }
        cursor = (
            self._collection()
            .find(filter=query, projection=projection)
            .sort("created_at", -1)
            .skip(max(skip, 0))
            .limit(max(min(limit, 500), 1))
        )

        out: list[StoredDocumentSummary] = []
        for item in cursor:
            oid = item.get("_id")
            created = item.get("created_at")
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)
            out.append(
                StoredDocumentSummary(
                    id=str(oid),
                    sha256=str(item.get("sha256") or ""),
                    filename=str(item.get("filename") or ""),
                    rel_path=str(item.get("rel_path") or ""),
                    size=int(item.get("size") or 0),
                    created_at=created_at,
                )
            )
        return out

    def get_document_bytes(self, *, doc_id: str) -> tuple[dict[str, Any], bytes] | None:
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return None

        item = self._collection().find_one({"_id": oid})
        if not item:
            return None
        content = item.get("content")
        if not isinstance(content, (bytes, Binary)):
            return None
        raw = bytes(content)
        meta = {
            "id": str(item.get("_id")),
            "sha256": item.get("sha256"),
            "filename": item.get("filename"),
            "rel_path": item.get("rel_path"),
            "size": item.get("size"),
            "created_at": item.get("created_at"),
        }
        return meta, raw

    def get_document_detail(
        self,
        *,
        doc_id: str,
        max_bytes: int = 200_000,
    ) -> dict[str, Any] | None:
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return None

        item = self._collection().find_one({"_id": oid})
        if not item:
            return None

        content = item.get("content")
        content_preview: str | None = None
        if isinstance(content, (bytes, Binary)):
            raw = bytes(content)
            raw = raw[: max(max_bytes, 0)]
            content_preview = raw.decode("utf-8", errors="replace")

        created = item.get("created_at")
        created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)

        return {
            "id": str(item.get("_id")),
            "sha256": item.get("sha256"),
            "filename": item.get("filename"),
            "rel_path": item.get("rel_path"),
            "size": item.get("size"),
            "created_at": created_at,
            "content_preview": content_preview,
        }

    def append_chat_message(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        role: str,
        content: str,
        attachments: list[Any] | None = None,
        references: list[dict[str, Any]] | None = None,
        suggested_questions: list[str] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tool_args: Any | None = None,
        tool_status: str | None = None,
        tool_output: Any | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> str:
        if created_at is None:
            created_at = get_beijing_time()

        doc: dict[str, Any] = {
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "role": role,
            "content": content,
            "attachments": attachments or [],
            "references": references or [],
            "suggested_questions": suggested_questions or [],
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_status": tool_status,
            "tool_output": tool_output,
            "started_at": started_at,
            "ended_at": ended_at,
            "created_at": created_at,
        }
        result = self._chat_collection().insert_one(doc)
        return str(result.inserted_id)

    def upsert_tool_message(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        tool_call_id: str,
        tool_name: str,
        tool_args: Any | None = None,
        tool_status: str | None = None,
        tool_output: Any | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if created_at is None:
            created_at = get_beijing_time()

        set_on_insert: dict[str, Any] = {
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "role": "tool",
            "content": "",
            "attachments": [],
            "references": [],
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "created_at": created_at,
        }

        set_doc: dict[str, Any] = {}
        if tool_args is not None:
            set_doc["tool_args"] = tool_args
        if tool_status is not None:
            set_doc["tool_status"] = tool_status
        if tool_output is not None:
            set_doc["tool_output"] = tool_output
        if started_at is not None:
            set_doc["started_at"] = started_at
        if ended_at is not None:
            set_doc["ended_at"] = ended_at

        self._chat_collection().update_one(
            {
                "thread_id": thread_id,
                "assistant_id": assistant_id,
                "role": "tool",
                "tool_call_id": tool_call_id,
            },
            {
                "$setOnInsert": set_on_insert,
                "$set": set_doc,
            },
            upsert=True,
        )

    def get_chat_history(self, *, thread_id: str, limit: int = 200) -> list[dict[str, Any]]:
        # 修复：按降序查询最新的 N 条记录，然后反转结果
        cursor = (
            self._chat_collection()
            .find({"thread_id": thread_id})
            .sort("created_at", -1)  # -1 = 降序（从新到旧）
            .limit(max(min(limit, 500), 1))
        )
        out: list[dict[str, Any]] = []
        for item in cursor:
            created = item.get("created_at")
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)
            out.append(
                {
                    "id": str(item.get("_id")),
                    "thread_id": item.get("thread_id"),
                    "assistant_id": item.get("assistant_id"),
                    "role": item.get("role"),
                    "content": item.get("content"),
                    "attachments": item.get("attachments") or [],
                    "references": item.get("references") or [],
                    "suggested_questions": item.get("suggested_questions") or [],
                    "tool_call_id": item.get("tool_call_id"),
                    "tool_name": item.get("tool_name"),
                    "tool_args": item.get("tool_args"),
                    "tool_status": item.get("tool_status"),
                    "tool_output": item.get("tool_output"),
                    "started_at": (
                        item.get("started_at").isoformat()
                        if hasattr(item.get("started_at"), "isoformat")
                        else item.get("started_at")
                    ),
                    "ended_at": (
                        item.get("ended_at").isoformat()
                        if hasattr(item.get("ended_at"), "isoformat")
                        else item.get("ended_at")
                    ),
                    "created_at": created_at,
                }
            )
        # 反转结果，按时间升序返回（旧消息在前，新消息在后）
        return list(reversed(out))

    def list_chat_threads(self, *, assistant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        pipeline: list[dict[str, Any]] = []
        match: dict[str, Any] = {}
        if assistant_id:
            match["assistant_id"] = assistant_id
        if match:
            pipeline.append({"$match": match})
        pipeline.extend(
            [
                {
                    "$group": {
                        "_id": "$thread_id",
                        "last_at": {"$max": "$created_at"},
                    }
                },
                {"$sort": {"last_at": -1}},
                {"$limit": max(min(limit, 200), 1)},
            ]
        )
        out: list[dict[str, Any]] = []
        for row in self._chat_collection().aggregate(pipeline):
            last = row.get("last_at")
            last_at = last.isoformat() if hasattr(last, "isoformat") else str(last)
            out.append({"thread_id": str(row.get("_id")), "last_at": last_at})
        return out

    def get_chat_memory(self, *, thread_id: str, assistant_id: str) -> str:
        doc = self._chat_memory_collection().find_one(
            {"thread_id": thread_id, "assistant_id": assistant_id},
            projection={"memory_text": 1},
            sort=[("updated_at", -1)],
        )
        if not doc:
            return ""
        value = doc.get("memory_text")
        return str(value) if value is not None else ""

    def append_chat_memory(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        user_text: str,
        assistant_text: str,
        max_chars: int = 8000,
    ) -> None:
        prev = self.get_chat_memory(thread_id=thread_id, assistant_id=assistant_id)
        block = f"User: {user_text.strip()}\nAssistant: {assistant_text.strip()}".strip()
        merged = (prev + "\n\n" + block).strip() if prev else block
        if max_chars > 0 and len(merged) > max_chars:
            merged = merged[-max_chars:]

        now = get_beijing_time()
        self._chat_memory_collection().update_one(
            {"thread_id": thread_id, "assistant_id": assistant_id},
            {
                "$set": {
                    "thread_id": thread_id,
                    "assistant_id": assistant_id,
                    "memory_text": merged,
                    "updated_at": now,
                }
            },
            upsert=True,
        )


_DEFAULT_MONGO_URL = (
    os.getenv("MONGODB_URI")
    or os.getenv("DEEPAGENTS_MONGO_URL")
    or "mongodb://127.0.0.1:27017"
)
_DEFAULT_DB_NAME = os.getenv("DEEPAGENTS_MONGO_DB") or "deepagents_web"
_DEFAULT_COLLECTION = os.getenv("DEEPAGENTS_MONGO_COLLECTION") or "uploaded_sources"
_DEFAULT_CHAT_COLLECTION = os.getenv("DEEPAGENTS_MONGO_CHAT_COLLECTION") or "chat_messages"
_DEFAULT_CHAT_MEMORY_COLLECTION = os.getenv("DEEPAGENTS_MONGO_CHAT_MEMORY_COLLECTION") or "agent_chat_memories"


def get_mongo_manager() -> MongoDbManager:
    return MongoDbManager(
        mongo_url=_DEFAULT_MONGO_URL,
        db_name=_DEFAULT_DB_NAME,
        collection_name=_DEFAULT_COLLECTION,
    )
