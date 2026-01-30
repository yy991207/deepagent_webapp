"""
Celery 应用配置模块

处理方式：同步初始化
设计原因：Celery 应用在模块加载时初始化，Worker 和 API 共用同一个实例
"""
from celery import Celery

from backend.celery_scheduler.config import celery_config


def create_celery_app() -> Celery:
    """
    创建并配置 Celery 应用
    
    关键配置说明：
    1. broker: 使用 Redis 作为消息队列
    2. backend: 使用 Redis 存储任务结果
    3. task_time_limit: 任务执行的超时时间
    """
    app = Celery(
        "celery_scheduler",
        broker=celery_config.broker_url,
        backend=celery_config.result_backend_url,
        # 指定任务模块，Celery 会自动发现这些模块中的任务
        include=[
            "backend.celery_scheduler.tasks.podcast_tasks",
            "backend.celery_scheduler.tasks.agent_tasks",
        ]
    )
    
    # Celery 配置
    app.conf.update(
        # 任务超时设置（单位：秒）
        task_time_limit=celery_config.task_time_limit,
        task_soft_time_limit=celery_config.task_soft_time_limit,
        
        # Worker 预取设置
        # 设为 1 表示每次只取一个任务，避免任务堆积在单个 Worker
        worker_prefetch_multiplier=celery_config.worker_prefetch_multiplier,
        
        # 结果过期时间（单位：秒）
        result_expires=celery_config.result_expires,
        
        # 时区设置
        timezone=celery_config.timezone,
        enable_utc=True,
        
        # 序列化设置
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        
        # 任务确认设置
        # 任务成功完成后才确认，失败则重新入队
        task_acks_late=True,
        
        # 任务跟踪设置
        task_track_started=True,
        
        # 结果扩展设置
        result_extended=True,
        
        # Beat 定时任务配置
        beat_schedule={
            "check-timeout-tasks": {
                "task": "check_timeout_tasks",
                "schedule": 300.0,  # 每 5 分钟执行一次
            },
        },
    )
    
    return app


# 全局 Celery 应用实例
celery_app = create_celery_app()
