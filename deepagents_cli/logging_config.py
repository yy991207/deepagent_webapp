"""兼容层日志配置，复用 webapp 内置格式化器。"""

from backend.utils.logging_config import BeijingFormatter

__all__ = ["BeijingFormatter"]
