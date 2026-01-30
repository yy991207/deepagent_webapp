"""
配置管理模块

处理方式：同步加载，启动时一次性读取
设计原因：配置在服务启动时加载一次即可，无需异步
"""
from __future__ import annotations

import os
from pathlib import Path


class CelerySchedulerConfig:
    """
    Celery 调度服务配置类
    
    职责：
    1. 从环境变量读取配置
    2. 提供配置项的便捷访问方法
    3. 支持默认值回退
    """
    
    # ==================== Redis 配置 ====================
    
    @property
    def redis_host(self) -> str:
        return os.getenv("REDIS_HOST", "localhost")
    
    @property
    def redis_port(self) -> int:
        return int(os.getenv("REDIS_PORT", "6379"))
    
    @property
    def redis_password(self) -> str:
        return os.getenv("REDIS_PASSWORD", "")
    
    @property
    def redis_db_broker(self) -> int:
        return int(os.getenv("CELERY_BROKER_DB", "0"))
    
    @property
    def redis_db_backend(self) -> int:
        return int(os.getenv("CELERY_BACKEND_DB", "1"))
    
    @property
    def broker_url(self) -> str:
        """Celery Broker URL"""
        # 优先使用完整 URL 环境变量
        full_url = os.getenv("CELERY_BROKER_URL")
        if full_url:
            return full_url
        # 否则拼接
        pwd = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{pwd}{self.redis_host}:{self.redis_port}/{self.redis_db_broker}"
    
    @property
    def result_backend_url(self) -> str:
        """Celery Result Backend URL"""
        full_url = os.getenv("CELERY_RESULT_BACKEND")
        if full_url:
            return full_url
        pwd = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{pwd}{self.redis_host}:{self.redis_port}/{self.redis_db_backend}"
    
    # ==================== Celery Worker 配置 ====================
    
    @property
    def task_time_limit(self) -> int:
        """任务硬超时（秒）"""
        return int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800"))
    
    @property
    def task_soft_time_limit(self) -> int:
        """任务软超时（秒）"""
        return int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "1500"))
    
    @property
    def worker_concurrency(self) -> int:
        """Worker 并发数"""
        return int(os.getenv("CELERY_WORKER_CONCURRENCY", "4"))
    
    @property
    def worker_prefetch_multiplier(self) -> int:
        """Worker 预取数"""
        return int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))
    
    @property
    def result_expires(self) -> int:
        """结果过期时间（秒）"""
        return int(os.getenv("CELERY_RESULT_EXPIRES", "3600"))
    
    @property
    def timezone(self) -> str:
        """时区"""
        return os.getenv("CELERY_TIMEZONE", "Asia/Shanghai")
    
    # ==================== MongoDB 配置 ====================
    
    @property
    def mongo_url(self) -> str:
        return os.getenv("MONGODB_URI") or os.getenv("DEEPAGENTS_MONGO_URL") or "mongodb://127.0.0.1:27017"
    
    @property
    def mongo_db_name(self) -> str:
        return os.getenv("DEEPAGENTS_MONGO_DB", "deepagents_web")
    
    # ==================== 数据目录配置 ====================
    
    @property
    def data_dir(self) -> str:
        return os.getenv("DEEPAGENTS_DATA_DIR") or str(Path(__file__).resolve().parents[2] / "data")


# 全局配置实例（单例模式）
celery_config = CelerySchedulerConfig()
