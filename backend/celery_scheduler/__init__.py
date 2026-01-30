"""
Celery 调度服务模块

职责：提供基于 Celery 的异步任务调度能力
设计原因：
1. 与主应用解耦，支持独立部署
2. 直接操作 MongoDB，移除 Java 中间层
3. 复用现有 podcast_middleware 的业务逻辑
"""

from backend.celery_scheduler.celery_app import celery_app

__all__ = ["celery_app"]
