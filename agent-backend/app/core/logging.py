"""日志配置：统一格式与级别，供全局异常处理器记录错误。

约定（见 AGENTS.md 错误处理约定）：
- 业务错误（4xx）记 WARNING：预期内，不打堆栈；
- 系统错误（5xx）记 ERROR：附堆栈，供后端定位。

级别可用环境变量 LOG_LEVEL 覆盖，默认 INFO。
"""

import os
from logging.config import dictConfig

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def setup_logging() -> None:
    """配置根 logger。应用启动时调用一次即可。"""
    dictConfig(
        {
            "version": 1,
            # 保留第三方库（uvicorn 等）已建立的 logger，避免其日志被静默
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": LOG_LEVEL,
                }
            },
            "root": {"handlers": ["console"], "level": LOG_LEVEL},
        }
    )
