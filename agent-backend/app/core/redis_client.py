"""Redis 客户端：懒加载单例 + 连接可用性判断。

Redis 只作为提示词模板的缓存，**不是数据源**：连接失败时调用方必须回源 MySQL，
因此这里不在启动阶段强制校验，也不把连接异常向上抛成系统错误。
"""

import redis

from .config import get_redis_config

# 连接 / 读超时压短：缓存不可用时快速回源数据库，避免拖慢请求
_CONNECT_TIMEOUT = 1.0
_SOCKET_TIMEOUT = 1.0

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """返回 Redis 客户端单例（首次调用时创建，创建本身不会建立连接）。"""
    global _client
    if _client is None:
        config = get_redis_config()
        _client = redis.Redis(
            host=config.host,
            port=config.port,
            db=config.db,
            password=config.password,
            decode_responses=True,
            socket_connect_timeout=_CONNECT_TIMEOUT,
            socket_timeout=_SOCKET_TIMEOUT,
            health_check_interval=30,
        )
    return _client


def reset() -> None:
    """关闭并丢弃单例，测试或配置变更后重新建立连接时使用。"""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            # 关闭失败无需处理：对象随后被丢弃
            pass
    _client = None
