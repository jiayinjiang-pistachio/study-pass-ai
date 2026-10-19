"""日志配置：基于 Loguru 统一格式，开发输出控制台、生产落文件，供留痕与排障。

- 级别 / 目录 / 是否输出控制台由 app.core.config 统一读取，本模块不再直接 os.getenv；
- 文件按大小滚动（10MB × 5）并自动保留历史，避免单文件无限增长；
- 用 InterceptHandler 接管标准库 logging，使 uvicorn 与项目内 logging.getLogger 的
  日志都汇入 Loguru，格式一致、同样落文件，且不会重复输出；
- 业务错误（4xx）记 WARNING、系统错误（5xx）记 ERROR 的约定见 handlers.py。

级别与开关可用环境变量覆盖（LOG_LEVEL / LOG_DIR / LOG_TO_CONSOLE）。
"""

import logging
import sys

from loguru import logger

from .config import LOG_DIR, LOG_FILE_NAME, LOG_LEVEL, LOG_TO_CONSOLE

# 单文件上限与备份数：兼顾留痕与磁盘占用
_ROTATION = "10 MB"
_RETENTION = 5

# 用 extra[logger] 展示「原始 logger 名」（如 uvicorn.access / app.core.handlers），
# 比 Loguru 默认的 {name}（调用模块）更贴近日志来源。
_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {extra[logger]} | {message}"


class _InterceptHandler(logging.Handler):
    """把标准库 logging（含 uvicorn）的记录转发进 Loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        # 标准库的 levelname 映射到 Loguru 的级别名
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # 保留原始 logger 名，供 {extra[logger]} 使用
        logger.bind(logger=record.name).opt(exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    """配置 Loguru 与标准库 logging 的衔接；应用启动时调用一次。"""
    # 去掉 Loguru 默认的 stderr handler，重建为「控制台 + 文件」
    logger.remove()
    # 直接调用 Loguru（未 bind）时，extra[logger] 回退为调用模块名，避免格式缺字段
    logger.configure(patcher=lambda r: r["extra"].setdefault("logger", r["name"]))

    file_error: OSError | None = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.add(
            LOG_DIR / LOG_FILE_NAME,
            level=LOG_LEVEL,
            format=_FORMAT,
            rotation=_ROTATION,
            retention=_RETENTION,
            encoding="utf-8",
        )
    except OSError as exc:  # 目录不可写时降级为仅控制台，保证应用仍能启动
        file_error = exc

    # 生产默认不输出控制台；若文件也没配上，则兜底保留控制台，避免日志全丢
    if LOG_TO_CONSOLE or file_error is not None:
        logger.add(sys.stderr, level=LOG_LEVEL, format=_FORMAT)

    if file_error is not None:
        logger.warning("日志目录不可用，降级为仅控制台：{}", file_error)

    # 接管标准库 logging：uvicorn 与项目内 logging.getLogger(__name__) 的记录，
    # 经 InterceptHandler 汇入 Loguru。uvicorn 默认 propagate=False 且自带 handler，
    # 需显式替换，否则其日志不会进入 Loguru（也就不会落文件）。
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [_InterceptHandler()]
        lg.propagate = False
