"""自定义日志配置，支持东八区北京时间"""
import logging
import os
from datetime import datetime, timezone, timedelta

# 设置时区环境变量为东八区
os.environ['TZ'] = 'Asia/Shanghai'


class BeijingFormatter(logging.Formatter):
    """使用东八区北京时间的日志格式化器"""
    
    converter = lambda *args: datetime.now(timezone(timedelta(hours=8))).timetuple()
    
    def formatTime(self, record, datefmt=None):
        """重写 formatTime 方法，使用东八区时间"""
        beijing_tz = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(record.created, tz=beijing_tz)
        if datefmt:
            return dt.strftime(datefmt)
        else:
            return dt.strftime('%Y-%m-%d %H:%M:%S')


def get_uvicorn_log_config():
    """获取 uvicorn 的日志配置"""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "deepagents_cli.logging_config.BeijingFormatter",
                "fmt": "%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "access": {
                "()": "deepagents_cli.logging_config.BeijingFormatter",
                "fmt": "%(asctime)s | %(levelname)-8s | %(client_addr)s - \"%(request_line)s\" %(status_code)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
        },
    }
