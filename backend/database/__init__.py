"""数据库管理模块"""
from backend.database.mongo_manager import get_mongo_manager, MongoDbManager

__all__ = ["get_mongo_manager", "MongoDbManager"]
