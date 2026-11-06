"""通用能力：分布式固定窗口限流（Redis 集中计数，故障降级进程内）。

以 FastAPI 依赖形式挂在需要限流的路由上；超限抛 BusinessException(429)，
交由全局处理器转成统一错误信封，路由层不写 try/except。

身份维度：
- 已登录（Bearer 访问令牌有效）→ `user:{user_id}`，同一账号跨设备共享配额；
- 游客 / 令牌非法 → `ip:{真实 IP}`。真实 IP 取 X-Forwarded-For **最右侧**一项，
  它由最近的受信代理追加，客户端自造的左侧内容无法影响它。

计数用 Lua 把 INCR 与首次 EXPIRE 绑成一次原子操作：多实例并发下不会出现
「计数已加、过期未设」的永不过期 key。Redis 异常时降级为进程内固定窗口，
日志按固定间隔节流，避免故障期间刷屏。
"""

import ipaddress
import logging
import threading
import time

from fastapi import Request, status

from . import redis_client
from .config import (
    RATE_LIMIT_BACKEND,
    RATE_LIMIT_CHAT_MAX,
    RATE_LIMIT_FALLBACK_LOG_INTERVAL,
    RATE_LIMIT_KEY_PREFIX,
    RATE_LIMIT_REGISTER_MAX,
    RATE_LIMIT_TASK_MAX,
    RATE_LIMIT_UPLOAD_MAX,
    RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_WORKFLOW_MAX,
)
from .exceptions import BusinessException
from .security import ACCESS_TOKEN_TYPE, decode_token

logger = logging.getLogger(__name__)

# 兼容旧调用方 / 既有测试：注册配额与窗口的默认值。
WINDOW_SECONDS = RATE_LIMIT_WINDOW_SECONDS
MAX_REQUESTS = RATE_LIMIT_REGISTER_MAX

# 原子操作：首次创建 key 时立刻设过期，后续请求只自增。
# 返回 {当前计数, 剩余 TTL}；TTL 仅用于排查，不参与判定。
_INCREMENT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return {current, redis.call('TTL', KEYS[1])}
"""

_lock = threading.Lock()
# 降级路径的进程内计数：key -> (窗口起点 monotonic, 计数)
_buckets: dict[str, tuple[float, int]] = {}
# 降级告警节流：上次打印时间（monotonic）
_last_fallback_log = 0.0


def client_ip(request: Request) -> str:
    """取真实客户端 IP。

    XFF 形如 `client, proxy1, proxy2`：右侧由最近的受信代理追加，左侧可被客户端
    伪造。因此固定取最右一项；解析失败才回落到直连地址，不信任任何左侧内容。
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        rightmost = forwarded.split(",")[-1].strip().strip('"')
        parsed = _normalize_ip(rightmost)
        if parsed:
            return parsed
    return request.client.host if request.client else "unknown"


def _normalize_ip(raw: str) -> str | None:
    """规范化单个 XFF 条目，兼容 `1.2.3.4:5678` / `[::1]:5678`，非法返回 None。"""
    candidate = raw
    if candidate.startswith("["):
        end = candidate.find("]")
        if end == -1:
            return None
        candidate = candidate[1:end]
    elif candidate.count(":") == 1:
        # 仅 IPv4:port 需要剥端口；裸 IPv6 含多个冒号，不能按端口处理
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _identity(request: Request) -> str:
    """解析限流主体：有效访问令牌 → user_id，否则按真实 IP。

    decode_token 在令牌过期 / 非法时自身抛 401 信封；这里捕获后按游客处理，
    让鉴权依赖决定最终响应（限流不代替鉴权）。
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        try:
            payload = decode_token(token.strip(), expected_type=ACCESS_TOKEN_TYPE)
            return f"user:{int(payload['sub'])}"
        except Exception:
            logger.debug("限流身份解析失败，按 IP 限流")
    return f"ip:{client_ip(request)}"


def _redis_increment(key: str, window_seconds: int) -> int:
    result = redis_client.get_client().eval(
        _INCREMENT_SCRIPT, 1, key, window_seconds
    )
    # decode_responses=True 时返回 [int, int]
    return int(result[0])


def _local_increment(key: str, window_seconds: int) -> int:
    now = time.monotonic()
    with _lock:
        start, count = _buckets.get(key, (now, 0))
        if now - start >= window_seconds:  # 窗口过期 → 重置
            start, count = now, 0
        count += 1
        _buckets[key] = (start, count)
        return count


def _log_fallback(exc: Exception) -> None:
    """降级告警节流：同一实例每个间隔最多一条 WARNING。"""
    global _last_fallback_log
    now = time.monotonic()
    with _lock:
        if now - _last_fallback_log < RATE_LIMIT_FALLBACK_LOG_INTERVAL:
            return
        _last_fallback_log = now
    logger.warning("限流 Redis 不可用，已降级为进程内限流: %s", exc)


def _increment(scope: str, identity: str, window_seconds: int) -> int:
    key = f"{RATE_LIMIT_KEY_PREFIX}:{scope}:{identity}"
    if RATE_LIMIT_BACKEND == "redis":
        try:
            return _redis_increment(key, window_seconds)
        except Exception as exc:  # 网络 / 超时 / 脚本错误一律降级
            _log_fallback(exc)
    return _local_increment(key, window_seconds)


def _limit_dependency(scope: str, max_requests: int, message: str):
    """生成指定作用域的 FastAPI 依赖。"""

    def dependency(request: Request) -> None:
        identity = _identity(request)
        count = _increment(scope, identity, WINDOW_SECONDS)
        if count > max_requests:
            raise BusinessException(
                message,
                http_status=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"scope={scope} identity={identity} "
                    f"limit={max_requests}/{WINDOW_SECONDS}s count={count}"
                ),
            )

    dependency.__name__ = f"enforce_{scope}_limit"
    return dependency


enforce_register_limit = _limit_dependency(
    "register", RATE_LIMIT_REGISTER_MAX, "注册过于频繁，请稍后再试"
)
enforce_chat_limit = _limit_dependency(
    "chat", RATE_LIMIT_CHAT_MAX, "对话请求过于频繁，请稍后再试"
)
enforce_task_limit = _limit_dependency(
    "task", RATE_LIMIT_TASK_MAX, "任务提交过于频繁，请稍后再试"
)
enforce_upload_limit = _limit_dependency(
    "upload", RATE_LIMIT_UPLOAD_MAX, "文件上传过于频繁，请稍后再试"
)
enforce_workflow_limit = _limit_dependency(
    "workflow", RATE_LIMIT_WORKFLOW_MAX, "工作流启动过于频繁，请稍后再试"
)


def reset() -> None:
    """清空进程内计数与告警节流状态（仅供测试隔离使用）。"""
    global _last_fallback_log
    with _lock:
        _buckets.clear()
        _last_fallback_log = 0.0
