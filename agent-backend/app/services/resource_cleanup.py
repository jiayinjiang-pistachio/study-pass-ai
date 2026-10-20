"""业务层：过期资源清理。

每天 03:00 扫描 resources.expire_time：先删 MinIO 对象，成功后再删元数据；
对象删除失败时保留记录，下一轮重试。
"""

import logging
import threading
from datetime import datetime, time as dtime, timedelta

from ..core import minio_client
from ..core.exceptions import SystemException
from ..db import resource_repo

logger = logging.getLogger(__name__)

CLEANUP_HOUR = 3

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def cleanup_expired(now: datetime | None = None) -> int:
    """清理已过期资源，返回删除的元数据条数。"""
    deleted = 0
    for resource in resource_repo.list_expired(now or datetime.now()):
        object_key = (
            minio_client.object_key_from_storage_path(resource["storage_path"])
            if resource["storage_path"]
            else None
        )
        if object_key is not None:
            try:
                minio_client.remove_object(object_key)
            except SystemException:
                # 对象没删掉就不删元数据，避免留下无法追溯的孤儿对象
                logger.warning("过期资源对象删除失败，保留元数据：id=%s", resource["id"])
                continue

        resource_repo.delete(resource["id"])
        deleted += 1

    if deleted:
        logger.info("过期资源清理完成：删除 %s 条", deleted)
    return deleted


def _seconds_until_next_run(now: datetime | None = None) -> float:
    """计算距离下一个本地 03:00 的秒数。"""
    current = now or datetime.now()
    next_run = datetime.combine(current.date(), dtime(hour=CLEANUP_HOUR))
    if next_run <= current:
        next_run += timedelta(days=1)
    return (next_run - current).total_seconds()


def _run_loop() -> None:
    while not _stop_event.wait(_seconds_until_next_run()):
        try:
            cleanup_expired()
        except Exception:
            # 定时任务异常不能杀死线程，记录后继续等待下一轮
            logger.exception("过期资源清理任务异常")


def start_cleanup_thread() -> None:
    """启动后台清理线程（幂等）。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run_loop, name="resource-cleanup", daemon=True)
    _thread.start()
    logger.info("过期资源清理线程已启动（每天 %02d:00）", CLEANUP_HOUR)


def stop_cleanup_thread() -> None:
    """通知清理线程退出并等待其结束（幂等）。"""
    global _thread
    _stop_event.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=5)
    _thread = None
