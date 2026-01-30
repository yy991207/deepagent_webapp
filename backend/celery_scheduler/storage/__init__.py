"""
存储模块

职责：提供任务状态的 MongoDB 存储操作
"""

from backend.celery_scheduler.storage.task_storage import TaskStorage

__all__ = ["TaskStorage"]
