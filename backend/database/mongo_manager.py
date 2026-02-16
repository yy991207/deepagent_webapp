from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from bson.binary import Binary
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo import ReturnDocument

from backend.utils.snowflake import generate_snowflake_id


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

    def _chat_sessions_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_CHAT_SESSIONS_COLLECTION]

    def _filesystem_writes_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_FILESYSTEM_WRITES_COLLECTION]

    def _creative_runs_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_CREATIVE_RUNS_COLLECTION]

    def _creative_final_docs_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_CREATIVE_FINAL_DOCS_COLLECTION]

    def _distributed_locks_collection(self):
        client = self._get_client()
        return client[self._db_name][_DEFAULT_DISTRIBUTED_LOCKS_COLLECTION]

    def store_file(
        self,
        *,
        filename: str,
        rel_path: str,
        content_bytes: bytes,
        parent_id: str | None = None,
    ) -> StoredDocument:
        sha256 = hashlib.sha256(content_bytes).hexdigest()
        size = len(content_bytes)
        now = get_beijing_time()

        doc: dict[str, Any] = {
            "sha256": sha256,
            "filename": filename,
            "rel_path": rel_path,
            "size": size,
            "content": Binary(content_bytes),
            "parent_id": parent_id,
            "item_type": "file",
            "sort_order": self._get_next_sort_order(parent_id),
            "created_at": now,
            "updated_at": now,
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

    # ========== 文件树相关方法 ==========

    def create_folder(
        self,
        *,
        name: str,
        parent_id: str | None = None,
    ) -> StoredDocument:
        """创建文件夹"""
        now = get_beijing_time()
        doc: dict[str, Any] = {
            "filename": name,
            "rel_path": name,
            "parent_id": parent_id,
            "item_type": "folder",
            "size": 0,
            "content": None,
            "sha256": "",
            "sort_order": self._get_next_sort_order(parent_id),
            "created_at": now,
            "updated_at": now,
        }
        result = self._collection().insert_one(doc)
        return StoredDocument(
            id=str(result.inserted_id),
            sha256="",
            filename=name,
            rel_path=name,
            size=0,
        )

    def get_tree(self) -> list[dict[str, Any]]:
        """获取完整树形结构（不含文件内容）"""
        projection = {"content": 0}
        items = list(self._collection().find({}, projection).sort([("sort_order", 1), ("created_at", 1)]))

        out: list[dict[str, Any]] = []
        for item in items:
            created = item.get("created_at")
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created or "")
            updated = item.get("updated_at")
            updated_at = updated.isoformat() if hasattr(updated, "isoformat") else str(updated or "")

            out.append({
                "id": str(item.get("_id")),
                "filename": item.get("filename", ""),
                "rel_path": item.get("rel_path", ""),
                "parent_id": item.get("parent_id"),
                "item_type": item.get("item_type", "file"),
                "size": item.get("size", 0),
                "file_type": self._get_file_type(item.get("filename", "")),
                "sort_order": item.get("sort_order", 0),
                "created_at": created_at,
                "updated_at": updated_at,
            })
        return out

    def move_item(
        self,
        *,
        item_id: str,
        target_parent_id: str | None,
    ) -> bool:
        """移动文件/文件夹到目标位置"""
        try:
            oid = ObjectId(item_id)
        except Exception:
            return False

        # 检查是否会造成循环引用（文件夹不能移到自己的子文件夹下）
        if target_parent_id:
            if self._is_descendant(item_id, target_parent_id):
                return False

        result = self._collection().update_one(
            {"_id": oid},
            {
                "$set": {
                    "parent_id": target_parent_id,
                    "sort_order": self._get_next_sort_order(target_parent_id),
                    "updated_at": get_beijing_time(),
                }
            },
        )
        return bool(result.modified_count)

    def reorder_item(
        self,
        *,
        item_id: str,
        target_id: str,
        position: str,  # "before" | "after" | "inside"
    ) -> dict[str, Any] | None:
        """重新排序/移动项目

        Args:
            item_id: 被移动的项目 ID
            target_id: 参照项目 ID
            position:
                - "before": 移到 target 前面（同级）
                - "after": 移到 target 后面（同级）
                - "inside": 移到 target 内部（target 必须是文件夹）
        """
        try:
            item_oid = ObjectId(item_id)
            target_oid = ObjectId(target_id)
        except Exception:
            return None

        # 获取目标项目信息
        target = self._collection().find_one({"_id": target_oid})
        if not target:
            return None

        # 确定新的 parent_id 和 sort_order
        if position == "inside":
            # 移动到文件夹内部
            if target.get("item_type") != "folder":
                return None  # 只能移动到文件夹内

            new_parent_id = target_id
            # 获取文件夹内最大的 sort_order，新项目排在最后
            max_order = self._get_max_sort_order(new_parent_id)
            new_sort_order = max_order + 1

        else:
            # 移动到同级 before/after
            new_parent_id = target.get("parent_id")
            target_order = target.get("sort_order", 0)

            if position == "before":
                new_sort_order = target_order
                # 将 target 及其后面的项目 sort_order +1
                self._shift_sort_orders(new_parent_id, target_order, 1)
            else:  # after
                new_sort_order = target_order + 1
                # 将 target 后面的项目 sort_order +1
                self._shift_sort_orders(new_parent_id, target_order + 1, 1)

        # 检查循环引用
        if new_parent_id and self._is_descendant(item_id, new_parent_id):
            return None

        # 更新项目
        result = self._collection().update_one(
            {"_id": item_oid},
            {
                "$set": {
                    "parent_id": new_parent_id,
                    "sort_order": new_sort_order,
                    "updated_at": get_beijing_time(),
                }
            },
        )

        if not result.modified_count:
            return None

        return {
            "item_id": item_id,
            "parent_id": new_parent_id,
            "sort_order": new_sort_order,
        }

    def duplicate_document(
        self,
        *,
        doc_id: str,
        target_parent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """复制文档到指定位置"""
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return None

        item = self._collection().find_one({"_id": oid})
        if not item:
            return None

        # 如果是文件夹，需要递归复制子项目
        if item.get("item_type") == "folder":
            return self._duplicate_folder(item, target_parent_id)

        # 复制文件
        now = get_beijing_time()
        new_doc = {
            "sha256": item.get("sha256", ""),
            "filename": f"{item.get('filename', 'copy')} (副本)",
            "rel_path": item.get("rel_path", ""),
            "size": item.get("size", 0),
            "content": item.get("content"),
            "parent_id": target_parent_id if target_parent_id is not None else item.get("parent_id"),
            "item_type": "file",
            "sort_order": self._get_next_sort_order(target_parent_id if target_parent_id is not None else item.get("parent_id")),
            "created_at": now,
            "updated_at": now,
        }

        result = self._collection().insert_one(new_doc)
        return {
            "id": str(result.inserted_id),
            "filename": new_doc["filename"],
            "parent_id": new_doc["parent_id"],
            "item_type": "file",
        }

    def _duplicate_folder(
        self,
        folder: dict[str, Any],
        target_parent_id: str | None,
    ) -> dict[str, Any] | None:
        """递归复制文件夹"""
        now = get_beijing_time()
        parent_id = target_parent_id if target_parent_id is not None else folder.get("parent_id")

        new_folder_doc = {
            "filename": f"{folder.get('filename', 'folder')} (副本)",
            "rel_path": folder.get("rel_path", ""),
            "parent_id": parent_id,
            "item_type": "folder",
            "size": 0,
            "content": None,
            "sha256": "",
            "sort_order": self._get_next_sort_order(parent_id),
            "created_at": now,
            "updated_at": now,
        }

        result = self._collection().insert_one(new_folder_doc)
        new_folder_id = str(result.inserted_id)

        # 递归复制子项目
        old_folder_id = str(folder.get("_id"))
        children = list(self._collection().find({"parent_id": old_folder_id}))
        for child in children:
            if child.get("item_type") == "folder":
                self._duplicate_folder(child, new_folder_id)
            else:
                self.duplicate_document(doc_id=str(child.get("_id")), target_parent_id=new_folder_id)

        return {
            "id": new_folder_id,
            "filename": new_folder_doc["filename"],
            "parent_id": parent_id,
            "item_type": "folder",
        }

    def delete_folder_recursive(self, *, folder_id: str) -> int:
        """递归删除文件夹及其所有子项目"""
        try:
            oid = ObjectId(folder_id)
        except Exception:
            return 0

        deleted_count = 0

        # 先删除所有子项目
        children = list(self._collection().find({"parent_id": folder_id}))
        for child in children:
            child_id = str(child.get("_id"))
            if child.get("item_type") == "folder":
                deleted_count += self.delete_folder_recursive(folder_id=child_id)
            else:
                result = self._collection().delete_one({"_id": ObjectId(child_id)})
                deleted_count += result.deleted_count

        # 删除文件夹本身
        result = self._collection().delete_one({"_id": oid})
        deleted_count += result.deleted_count

        return deleted_count

    def _get_file_type(self, filename: str) -> str:
        """从文件名提取文件类型"""
        if not filename or "." not in filename:
            return "unknown"
        return filename.rsplit(".", 1)[-1].lower()

    def _is_descendant(self, ancestor_id: str, descendant_id: str) -> bool:
        """检查 descendant_id 是否是 ancestor_id 的子孙节点"""
        current = descendant_id
        visited: set[str] = set()
        while current:
            if current in visited:
                break
            visited.add(current)
            if current == ancestor_id:
                return True
            try:
                doc = self._collection().find_one({"_id": ObjectId(current)}, {"parent_id": 1})
                current = doc.get("parent_id") if doc else None
            except Exception:
                break
        return False

    def _get_next_sort_order(self, parent_id: str | None) -> int:
        """获取指定父级下的下一个 sort_order"""
        return self._get_max_sort_order(parent_id) + 1

    def _get_max_sort_order(self, parent_id: str | None) -> int:
        """获取指定父级下的最大 sort_order"""
        query: dict[str, Any] = {"parent_id": parent_id}
        doc = self._collection().find_one(
            query,
            sort=[("sort_order", -1)],
            projection={"sort_order": 1},
        )
        return doc.get("sort_order", 0) if doc else 0

    def _shift_sort_orders(self, parent_id: str | None, from_order: int, delta: int) -> None:
        """批量调整 sort_order"""
        self._collection().update_many(
            {
                "parent_id": parent_id,
                "sort_order": {"$gte": from_order},
            },
            {"$inc": {"sort_order": delta}},
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

    def rename_document(self, *, doc_id: str, filename: str) -> bool:
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return False

        new_name = str(filename or "").strip()
        if not new_name:
            return False

        item = self._collection().find_one({"_id": oid}, projection={"rel_path": 1})
        if not item:
            return False

        rel_path = str(item.get("rel_path") or "")
        if "/" in rel_path:
            prefix = rel_path.rsplit("/", 1)[0]
            new_rel_path = f"{prefix}/{new_name}" if prefix else new_name
        else:
            new_rel_path = new_name

        result = self._collection().update_one(
            {"_id": oid},
            {"$set": {"filename": new_name, "rel_path": new_rel_path}},
        )
        return bool(getattr(result, "modified_count", 0) or 0)

    def delete_document(self, *, doc_id: str) -> bool:
        try:
            oid = ObjectId(doc_id)
        except Exception:
            return False

        result = self._collection().delete_one({"_id": oid})
        return bool(getattr(result, "deleted_count", 0) or 0)

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
            # 前端反馈信息：按 [copy, like, dislike] 的顺序记录，默认均为 0
            "feedback": [0, 0, 0],
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

    def set_chat_memory(
        self,
        *,
        thread_id: str,
        assistant_id: str,
        memory_text: str,
    ) -> None:
        """覆盖写入 chat memory。"""
        now = get_beijing_time()
        self._chat_memory_collection().update_one(
            {"thread_id": thread_id, "assistant_id": assistant_id},
            {
                "$set": {
                    "thread_id": thread_id,
                    "assistant_id": assistant_id,
                    "memory_text": str(memory_text or ""),
                    "updated_at": now,
                }
            },
            upsert=True,
        )

    def acquire_distributed_lock(
        self,
        *,
        lock_key: str,
        owner_id: str,
        ttl_seconds: int,
    ) -> bool:
        """获取分布式锁（Mongo 版本）。

        说明：
        - 单条记录表示一个锁
        - expires_at 过期后可被其他 owner 抢占
        """
        if not lock_key or not owner_id or ttl_seconds <= 0:
            return False

        now = get_beijing_time()
        expires_at = now + timedelta(seconds=int(ttl_seconds))
        query = {
            "lock_key": lock_key,
            "$or": [
                {"expires_at": {"$lte": now}},
                {"expires_at": {"$exists": False}},
                {"owner_id": owner_id},
            ],
        }
        update = {
            "$set": {
                "lock_key": lock_key,
                "owner_id": owner_id,
                "expires_at": expires_at,
                "updated_at": now,
            }
        }
        doc = self._distributed_locks_collection().find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return bool(doc and doc.get("owner_id") == owner_id)

    def release_distributed_lock(self, *, lock_key: str, owner_id: str) -> None:
        """释放分布式锁（仅允许 owner 释放）。"""
        if not lock_key or not owner_id:
            return
        self._distributed_locks_collection().delete_one({"lock_key": lock_key, "owner_id": owner_id})

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
            # MongoDB 存储的是 UTC 时间，需要转换为北京时间
            created = item.get("created_at")
            if isinstance(created, datetime):
                # 如果是 naive datetime（无时区信息），假定为 UTC，转换为北京时间
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
                created_at = created.isoformat()
            else:
                created_at = str(created) if created else None
            
            # 处理 started_at 和 ended_at
            started = item.get("started_at")
            if isinstance(started, datetime) and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            started_at = started.isoformat() if hasattr(started, "isoformat") else started
            
            ended = item.get("ended_at")
            if isinstance(ended, datetime) and ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            ended_at = ended.isoformat() if hasattr(ended, "isoformat") else ended
            
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
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "feedback": item.get("feedback") or [0, 0, 0],
                    "created_at": created_at,
                }
            )
        # 反转结果，按时间升序返回（旧消息在前，新消息在后）
        return list(reversed(out))

    def update_message_feedback(self, *, thread_id: str, message_id: str, index: int) -> None:
        """更新单条消息的反馈信息。

        说明：
        - feedback 字段为长度为 3 的数组，含义为 [copy, like, dislike]
        - 本方法会将指定下标位置的值置为 1，其它位置保持不变
        """

        if index not in (0, 1, 2):
            return

        try:
            from bson import ObjectId  # 延迟导入，避免模块加载时出错
        except Exception:
            return

        try:
            oid = ObjectId(str(message_id))
        except Exception:
            return

        coll = self._chat_collection()
        doc = coll.find_one({"_id": oid, "thread_id": thread_id})
        if not doc:
            return

        fb = doc.get("feedback")
        if not isinstance(fb, list) or len(fb) != 3:
            fb = [0, 0, 0]

        try:
            fb[index] = 1
        except Exception:
            fb = [0, 0, 0]
            fb[index] = 1

        now = get_beijing_time()
        coll.update_one({"_id": oid}, {"$set": {"feedback": fb, "updated_at": now}})

    def upsert_chat_session_title(self, *, session_id: str, assistant_id: str, title: str) -> None:
        """写入/更新会话标题。

        说明：
        - 这是给前端会话列表展示用的“自定义标题”。
        - 若不设置该标题，列表接口会回退到“首条 user 消息缩略”。
        """
        now = get_beijing_time()
        self._chat_sessions_collection().update_one(
            {"session_id": session_id, "assistant_id": assistant_id},
            {"$set": {"session_id": session_id, "assistant_id": assistant_id, "title": title, "updated_at": now}},
            upsert=True,
        )

    def list_chat_sessions(self, *, assistant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """列出会话列表。

        返回字段：
        - session_id: 会话 id（当前落库字段 thread_id 的语义视为 session_id）
        - title: 自定义标题优先；否则取首条 user 消息缩略
        - message_count: 消息数量（包含 tool 消息）
        - created_at / updated_at: 创建与最后更新时间
        """

        match: dict[str, Any] = {}
        if assistant_id:
            match["assistant_id"] = assistant_id

        pipeline: list[dict[str, Any]] = []
        if match:
            pipeline.append({"$match": match})

        # 先按 created_at 升序，让 $first 更接近“首条消息”
        pipeline.extend(
            [
                {"$sort": {"created_at": 1}},
                {
                    "$group": {
                        "_id": "$thread_id",
                        "created_at": {"$min": "$created_at"},
                        "updated_at": {"$max": "$created_at"},
                        "message_count": {"$sum": 1},
                        "first_user_message": {
                            "$first": {
                                "$cond": [
                                    {"$eq": ["$role", "user"]},
                                    "$content",
                                    None,
                                ]
                            }
                        },
                    }
                },
                {"$sort": {"updated_at": -1}},
                {"$limit": max(min(limit, 200), 1)},
            ]
        )

        rows = list(self._chat_collection().aggregate(pipeline))
        if not rows:
            return []

        session_ids = [str(r.get("_id")) for r in rows]
        title_map: dict[str, str] = {}

        # 批量读取自定义标题
        title_query: dict[str, Any] = {"session_id": {"$in": session_ids}}
        if assistant_id:
            title_query["assistant_id"] = assistant_id

        for doc in self._chat_sessions_collection().find(title_query):
            sid = str(doc.get("session_id") or "")
            t = str(doc.get("title") or "").strip()
            if sid and t:
                title_map[sid] = t

        out: list[dict[str, Any]] = []
        for r in rows:
            sid = str(r.get("_id") or "")
            
            # MongoDB 存储的是 UTC 时间，需要转换为北京时间
            created = r.get("created_at")
            if isinstance(created, datetime) and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)
            
            updated = r.get("updated_at")
            if isinstance(updated, datetime) and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            updated_at = updated.isoformat() if hasattr(updated, "isoformat") else str(updated)

            fallback = str(r.get("first_user_message") or "").strip() or "新对话"
            fallback_title = fallback[:30] + ("..." if len(fallback) > 30 else "")
            title = title_map.get(sid) or fallback_title

            out.append(
                {
                    "session_id": sid,
                    "assistant_id": assistant_id,
                    "title": title,
                    "message_count": int(r.get("message_count") or 0),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        return out

    # ==================== Creative Mode 相关 ====================

    def create_creative_run(self, *, run_doc: dict[str, Any]) -> None:
        """创建创作模式运行记录。"""
        # 关键逻辑：insert_one 会给原字典补 `_id`，这里用副本避免污染上层返回对象。
        self._creative_runs_collection().insert_one(dict(run_doc))

    def get_creative_run(self, *, run_id: str) -> dict[str, Any] | None:
        """按 run_id 查询创作模式运行记录。"""
        doc = self._creative_runs_collection().find_one({"run_id": run_id})
        if not doc:
            return None

        out = {k: v for k, v in doc.items() if k != "_id"}
        for key in ("created_at", "updated_at", "completed_at"):
            value = out.get(key)
            if isinstance(value, datetime) and value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            if hasattr(value, "isoformat"):
                out[key] = value.isoformat()
        return out

    def update_creative_run(self, *, run_id: str, set_fields: dict[str, Any]) -> bool:
        """更新创作模式运行记录。"""
        now = get_beijing_time()
        payload = dict(set_fields)
        payload["updated_at"] = now
        result = self._creative_runs_collection().update_one(
            {"run_id": run_id},
            {"$set": payload},
        )
        return bool(result.modified_count)

    def list_creative_runs(
        self,
        *,
        session_id: str,
        assistant_id: str = "agent",
        active_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """列出某个会话的创作模式运行记录。"""
        query: dict[str, Any] = {
            "session_id": session_id,
            "assistant_id": assistant_id,
        }
        if active_only:
            query["status"] = {"$nin": ["completed", "cancelled", "error"]}

        cursor = (
            self._creative_runs_collection()
            .find(query, projection={"_id": 0})
            .sort("updated_at", -1)
            .limit(max(min(limit, 100), 1))
        )

        out: list[dict[str, Any]] = []
        for item in cursor:
            for key in ("created_at", "updated_at", "completed_at"):
                value = item.get(key)
                if isinstance(value, datetime) and value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
                if hasattr(value, "isoformat"):
                    item[key] = value.isoformat()
            out.append(item)
        return out

    def save_creative_final_doc(
        self,
        *,
        run_id: str,
        session_id: str,
        assistant_id: str,
        content: str,
        title: str,
        write_id: str | None = None,
    ) -> None:
        """保存创作模式终稿。"""
        now = get_beijing_time()
        self._creative_final_docs_collection().update_one(
            {"run_id": run_id},
            {
                "$set": {
                    "run_id": run_id,
                    "session_id": session_id,
                    "assistant_id": assistant_id,
                    "title": title,
                    "content": content,
                    "write_id": write_id,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def create_filesystem_write(
        self,
        *,
        write_id: str,
        session_id: str,
        file_path: str,
        content: str,
        binary_content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """创建文件写入记录。

        Args:
            write_id: 文件写入唯一标识符
            session_id: 会话标识符
            file_path: 文件路径
            content: 文本内容（用于文本文件或作为 fallback）
            binary_content: 二进制内容的 base64 编码（用于 PDF、图片等二进制文件）
            metadata: 元数据（title, type, size 等）

        Returns:
            插入文档的 MongoDB ObjectId 字符串
        """
        now = get_beijing_time()
        doc: dict[str, Any] = {
            "write_id": write_id,
            "session_id": session_id,
            "file_path": file_path,
            "content": content,
            "metadata": metadata or {},
            "created_at": now,
        }
        # 只有当存在二进制内容时才添加该字段，避免存储空值浪费空间
        if binary_content:
            doc["binary_content"] = binary_content
        result = self._filesystem_writes_collection().insert_one(doc)
        return str(result.inserted_id)

    def save_filesystem_write(
        self,
        *,
        session_id: str,
        file_path: str,
        content: str,
        binary_content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """保存文件写入记录的便捷方法。

        Args:
            session_id: 会话标识符
            file_path: 文件路径
            content: 文本内容
            binary_content: 二进制内容的 base64 编码（可选）
            metadata: 元数据（可选）

        Returns:
            生成的 write_id
        """
        write_id = str(generate_snowflake_id())
        self.create_filesystem_write(
            write_id=write_id,
            session_id=session_id,
            file_path=file_path,
            content=content,
            binary_content=binary_content,
            metadata=metadata,
        )
        return write_id

    def get_filesystem_write(self, *, write_id: str, session_id: str) -> dict[str, Any] | None:
        """获取单个文件写入记录。

        Args:
            write_id: 文件写入唯一标识符
            session_id: 会话标识符

        Returns:
            文件写入记录字典，包含 binary_content（如果存在），不存在返回 None
        """
        doc = self._filesystem_writes_collection().find_one(
            {"write_id": write_id, "session_id": session_id}
        )
        if not doc:
            return None

        # MongoDB 存储的是 UTC 时间，需要转换为北京时间
        created = doc.get("created_at")
        if isinstance(created, datetime) and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
        created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)

        result = {
            "write_id": doc.get("write_id"),
            "session_id": doc.get("session_id"),
            "file_path": doc.get("file_path"),
            "content": doc.get("content"),
            "metadata": doc.get("metadata") or {},
            "created_at": created_at,
        }
        # 只有当存在二进制内容时才返回该字段
        if doc.get("binary_content"):
            result["binary_content"] = doc.get("binary_content")
        return result

    def list_filesystem_writes(self, *, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        cursor = (
            self._filesystem_writes_collection()
            .find({"session_id": session_id})
            .sort("created_at", -1)
            .limit(max(min(limit, 500), 1))
        )

        out: list[dict[str, Any]] = []
        for doc in cursor:
            # MongoDB 存储的是 UTC 时间，需要转换为北京时间
            created = doc.get("created_at")
            if isinstance(created, datetime) and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc).astimezone(BEIJING_TZ)
            created_at = created.isoformat() if hasattr(created, "isoformat") else str(created)
            metadata = doc.get("metadata") or {}

            # 计算文件大小：优先使用 metadata 中的 size，否则使用 content 长度
            file_size = metadata.get("size")
            if file_size is None:
                file_size = len(doc.get("content") or "")

            out.append(
                {
                    "write_id": doc.get("write_id"),
                    "session_id": doc.get("session_id"),
                    "file_path": doc.get("file_path"),
                    "title": metadata.get("title") or doc.get("file_path", "").split("/")[-1],
                    "type": metadata.get("type") or "unknown",
                    "size": file_size,
                    "has_binary": metadata.get("has_binary", False),
                    "created_at": created_at,
                }
            )
        return list(reversed(out))

    def delete_chat_session(self, *, session_id: str, assistant_id: str | None = None) -> dict[str, int]:
        """删除某个会话在 MongoDB 下的所有聊天相关数据。"""

        msg_filter: dict[str, Any] = {"thread_id": session_id}
        if assistant_id:
            msg_filter["assistant_id"] = assistant_id

        msg_res = self._chat_collection().delete_many(msg_filter)

        mem_filter: dict[str, Any] = {"thread_id": session_id}
        if assistant_id:
            mem_filter["assistant_id"] = assistant_id

        mem_res = self._chat_memory_collection().delete_many(mem_filter)

        sess_filter: dict[str, Any] = {"session_id": session_id}
        if assistant_id:
            sess_filter["assistant_id"] = assistant_id
        sess_res = self._chat_sessions_collection().delete_many(sess_filter)

        fs_filter: dict[str, Any] = {"session_id": session_id}
        fs_res = self._filesystem_writes_collection().delete_many(fs_filter)
        creative_runs_res = self._creative_runs_collection().delete_many(fs_filter)
        creative_final_docs_res = self._creative_final_docs_collection().delete_many(fs_filter)

        return {
            "messages": int(getattr(msg_res, "deleted_count", 0) or 0),
            "memories": int(getattr(mem_res, "deleted_count", 0) or 0),
            "sessions": int(getattr(sess_res, "deleted_count", 0) or 0),
            "filesystem_writes": int(getattr(fs_res, "deleted_count", 0) or 0),
            "creative_runs": int(getattr(creative_runs_res, "deleted_count", 0) or 0),
            "creative_final_docs": int(getattr(creative_final_docs_res, "deleted_count", 0) or 0),
        }

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
_DEFAULT_CHAT_SESSIONS_COLLECTION = os.getenv("DEEPAGENTS_MONGO_CHAT_SESSIONS_COLLECTION") or "chat_sessions"
_DEFAULT_FILESYSTEM_WRITES_COLLECTION = os.getenv("DEEPAGENTS_MONGO_FILESYSTEM_WRITES_COLLECTION") or "filesystem_writes"
_DEFAULT_CREATIVE_RUNS_COLLECTION = os.getenv("DEEPAGENTS_MONGO_CREATIVE_RUNS_COLLECTION") or "creative_runs"
_DEFAULT_CREATIVE_FINAL_DOCS_COLLECTION = (
    os.getenv("DEEPAGENTS_MONGO_CREATIVE_FINAL_DOCS_COLLECTION") or "creative_final_docs"
)
_DEFAULT_DISTRIBUTED_LOCKS_COLLECTION = os.getenv("DEEPAGENTS_MONGO_DISTRIBUTED_LOCKS_COLLECTION") or "distributed_locks"


def get_mongo_manager() -> MongoDbManager:
    return MongoDbManager(
        mongo_url=_DEFAULT_MONGO_URL,
        db_name=_DEFAULT_DB_NAME,
        collection_name=_DEFAULT_COLLECTION,
    )
