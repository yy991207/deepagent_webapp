"""
任务状态存储模块

职责：直接操作 MongoDB 进行任务状态的 CRUD
设计原因：
1. 精简架构，移除 Java 中间层
2. 复用现有 MongoDB 连接配置
3. 提供幂等性保证
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from pymongo import MongoClient

from backend.celery_scheduler.config import celery_config


# 终态定义
TERMINAL_STATES = {"SUCCESS", "FAILURE", "REVOKED", "done", "error"}


def is_terminal_state(status: str) -> bool:
    """判断是否为终态"""
    return status in TERMINAL_STATES


class TaskStorage:
    """
    任务状态存储类
    
    职责：
    1. 创建任务记录
    2. 更新任务状态
    3. 查询任务状态和详情
    4. 幂等性保证（终态不可覆盖）
    
    设计原因：直接操作 MongoDB，移除 Java 中间层
    """
    
    def __init__(self) -> None:
        self._client: MongoClient | None = None
        self._mongo_url = celery_config.mongo_url
        self._db_name = celery_config.mongo_db_name
    
    def _get_client(self) -> MongoClient:
        """获取 MongoDB 客户端（懒加载）"""
        if self._client is None:
            self._client = MongoClient(self._mongo_url)
        return self._client
    
    def _runs_collection(self):
        """获取 runs 集合"""
        return self._get_client()[self._db_name]["agent_run_records"]
    
    def _results_collection(self):
        """获取 results 集合"""
        return self._get_client()[self._db_name]["podcast_generation_results"]
    
    def _now(self) -> datetime:
        """获取当前 UTC 时间"""
        return datetime.now(timezone.utc)
    
    def close(self) -> None:
        """关闭 MongoDB 连接"""
        if self._client is not None:
            self._client.close()
            self._client = None
    
    # ==================== 任务记录操作 ====================
    
    def create_task(
        self,
        *,
        task_id: str,
        run_id: str,
        task_type: str = "generic",
        metadata: dict[str, Any] | None = None,
        # 以下为播客任务专用参数
        episode_profile: str | None = None,
        speaker_profile: str | None = None,
        episode_name: str | None = None,
        source_ids: list[str] | None = None,
        briefing_suffix: str | None = None,
    ) -> dict[str, Any]:
        """
        创建任务记录（支持通用和播客任务）
        
        处理方式：幂等插入，已存在则不覆盖
        设计原因：防止重复提交导致数据覆盖
        
        Args:
            task_id: Celery 任务 ID
            run_id: 运行 ID
            task_type: 任务类型（generic/podcast_generation）
            metadata: 附加元数据
            episode_profile: 节目配置名称（播客任务）
            speaker_profile: 说话人配置名称（播客任务）
            episode_name: 节目名称（播客任务）
            source_ids: 源文件 ID 列表（播客任务）
            briefing_suffix: 附加说明（播客任务）
            
        Returns:
            创建结果，包含 task_id 和 created 标志
        """
        now = self._now()
        doc = {
            "task_id": task_id,
            "run_id": run_id,
            "celery_task_id": task_id,  # 兼容旧字段
            "task_type": task_type,
            "status": "PENDING",
            "message": None,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        
        # 播客任务专用字段
        if task_type == "podcast_generation":
            doc.update({
                "episode_profile": episode_profile,
                "speaker_profile": speaker_profile,
                "episode_name": episode_name,
                "source_ids": source_ids or [],
                "briefing_suffix": briefing_suffix,
            })
        
        # 幂等插入：使用 upsert，$setOnInsert 只在插入时设置
        result = self._runs_collection().update_one(
            {"task_id": task_id},
            {"$setOnInsert": doc},
            upsert=True
        )
        
        return {
            "task_id": task_id,
            "run_id": run_id,
            "created": result.upserted_id is not None
        }
    
    def update_task_status(
        self,
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        status: str,
        message: str | None = None,
    ) -> dict[str, Any]:
        """
        更新任务状态
        
        处理方式：原子更新，终态不可覆盖
        设计原因：保证幂等性，防止状态回退
        
        Args:
            task_id: Celery 任务 ID（优先使用）
            run_id: 运行 ID（兼容旧代码）
            status: 新状态
            message: 状态消息或错误信息
            
        Returns:
            更新结果，包含 updated 标志和 reason
        """
        now = self._now()
        
        # 构建查询条件
        if task_id:
            query = {"task_id": task_id}
        elif run_id:
            query = {"run_id": run_id}
        else:
            return {"updated": False, "reason": "no_identifier"}
        
        # 原子更新：只更新非终态的记录
        # 使用 $nin 确保当前状态不在终态列表中
        result = self._runs_collection().update_one(
            {**query, "status": {"$nin": list(TERMINAL_STATES)}},
            {
                "$set": {
                    "status": status,
                    "message": message,
                    "updated_at": now,
                }
            }
        )
        
        if result.matched_count == 0:
            # 可能是：1) 不存在  2) 已终态
            existing = self._runs_collection().find_one(query)
            if existing and is_terminal_state(existing.get("status", "")):
                return {
                    "task_id": task_id,
                    "run_id": run_id,
                    "updated": False,
                    "reason": "already_terminal"
                }
            return {
                "task_id": task_id,
                "run_id": run_id,
                "updated": False,
                "reason": "not_found"
            }
        
        return {
            "task_id": task_id,
            "run_id": run_id,
            "updated": True
        }
    
    def update_celery_task_id(
        self,
        *,
        run_id: str,
        celery_task_id: str,
    ) -> dict[str, Any]:
        """
        更新 Celery 任务 ID
        
        Args:
            run_id: 运行 ID
            celery_task_id: Celery 任务 ID
            
        Returns:
            更新结果
        """
        now = self._now()
        
        result = self._runs_collection().update_one(
            {"run_id": run_id},
            {
                "$set": {
                    "celery_task_id": celery_task_id,
                    "updated_at": now,
                }
            }
        )
        
        return {
            "run_id": run_id,
            "updated": result.modified_count > 0
        }
    
    def get_task_status(self, *, run_id: str) -> dict[str, Any] | None:
        """
        获取任务状态
        
        Args:
            run_id: 运行 ID
            
        Returns:
            任务状态信息，不存在返回 None
        """
        doc = self._runs_collection().find_one(
            {"run_id": run_id},
            projection={"_id": 0, "run_id": 1, "status": 1, "celery_task_id": 1}
        )
        if not doc:
            return None
        return {
            "run_id": doc.get("run_id"),
            "status": doc.get("status"),
            "celery_task_id": doc.get("celery_task_id"),
            "exists": True
        }
    
    def get_task_detail(self, *, run_id: str) -> dict[str, Any] | None:
        """
        获取任务详情
        
        Args:
            run_id: 运行 ID
            
        Returns:
            完整任务信息，不存在返回 None
        """
        doc = self._runs_collection().find_one(
            {"run_id": run_id},
            projection={"_id": 0}
        )
        if not doc:
            return None
        
        # 转换时间字段为 ISO 格式
        for field in ["created_at", "updated_at"]:
            if field in doc and hasattr(doc[field], "isoformat"):
                doc[field] = doc[field].isoformat()
        
        doc["exists"] = True
        return doc
    
    # ==================== 结果记录操作 ====================
    
    def save_result(
        self,
        *,
        run_id: str,
        episode_profile: str,
        speaker_profile: str,
        episode_name: str,
        audio_file_path: str | None,
        transcript: Any,
        outline: Any,
        processing_time: float,
    ) -> dict[str, Any]:
        """
        保存生成结果
        
        处理方式：upsert，允许更新已有结果
        设计原因：重试生成时可以覆盖之前的结果
        
        Args:
            run_id: 运行 ID
            其他参数: 生成结果数据
            
        Returns:
            保存结果
        """
        now = self._now()
        doc = {
            "run_id": run_id,
            "episode_profile": episode_profile,
            "speaker_profile": speaker_profile,
            "episode_name": episode_name,
            "audio_file_path": audio_file_path,
            "transcript": transcript,
            "outline": outline,
            "processing_time": processing_time,
            "created_at": now,
        }
        
        self._results_collection().update_one(
            {"run_id": run_id},
            {"$set": doc},
            upsert=True
        )
        
        return {"run_id": run_id, "saved": True}
    
    def get_result(self, *, run_id: str) -> dict[str, Any] | None:
        """
        获取生成结果
        
        Args:
            run_id: 运行 ID
            
        Returns:
            生成结果数据，不存在返回 None
        """
        doc = self._results_collection().find_one(
            {"run_id": run_id},
            projection={"_id": 0}
        )
        if not doc:
            return None
        
        # 转换时间字段
        if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
            doc["created_at"] = doc["created_at"].isoformat()
        
        return doc
    
    # ==================== 超时检查 ====================
    
    def find_timeout_tasks(self, *, timeout_minutes: int = 30) -> list[str]:
        """
        查找超时任务
        
        处理方式：查找 running 状态超过指定时间的任务
        设计原因：定时任务检查，标记超时任务为 error
        
        Args:
            timeout_minutes: 超时时间（分钟）
            
        Returns:
            超时任务的 run_id 列表
        """
        threshold = self._now() - timedelta(minutes=timeout_minutes)
        
        cursor = self._runs_collection().find(
            {
                "status": "running",
                "updated_at": {"$lt": threshold}
            },
            projection={"run_id": 1}
        )
        
        return [doc["run_id"] for doc in cursor]
    
    def mark_timeout_tasks(self, *, run_ids: list[str]) -> int:
        """
        批量标记超时任务
        
        Args:
            run_ids: 要标记的 run_id 列表
            
        Returns:
            实际更新的数量
        """
        if not run_ids:
            return 0
        
        now = self._now()
        result = self._runs_collection().update_many(
            {
                "run_id": {"$in": run_ids},
                "status": {"$nin": list(TERMINAL_STATES)}
            },
            {
                "$set": {
                    "status": "error",
                    "message": "执行超时，已超过最大时限",
                    "updated_at": now,
                }
            }
        )
        
        return result.modified_count
