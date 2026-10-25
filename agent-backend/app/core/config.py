"""应用配置：环境变量分层加载 + 类型化读取，是全局配置的唯一入口。

分层优先级（高 → 低）：
    1. 真实进程环境变量（CI / 生产部署注入，最高优先，不被文件覆盖）
    2. .env.{APP_ENV}   环境专属覆盖（如 .env.prod）
    3. .env             基础 / 共享配置（提交 .env.example 作模板）

实现方式：先加载「环境专属文件」再加载「基础文件」，且都 override=False——
先写入的不被覆盖，从而天然形成上述优先级，无需手动改写 os.environ。

约定（见 AGENTS.md §5）：数据库口令等敏感信息只放环境变量 / 配置文件，
禁止硬编码进业务代码；其他层一律通过本模块读取，不直接碰 os.getenv。
"""

import os
from pathlib import Path
from typing import NamedTuple

from dotenv import dotenv_values, load_dotenv

# 仓库根目录：本文件位于 app/core/config.py，向上三级即 agent-backend/
_ROOT = Path(__file__).resolve().parents[2]


def _resolve_app_env() -> str:
    """确定运行环境：dev（默认）/ prod。真实环境变量优先，其次基础 .env。"""
    # interpolate=False：避免口令中的 $ 被 dotenv 当作变量插值而破坏
    base = dotenv_values(_ROOT / ".env", interpolate=False)
    return (os.getenv("APP_ENV") or base.get("APP_ENV") or "dev").strip().lower()


APP_ENV: str = _resolve_app_env()
IS_PROD: bool = APP_ENV == "prod"

# 先加载环境专属文件（值先落定），再加载基础文件补齐未覆盖项
load_dotenv(_ROOT / f".env.{APP_ENV}", override=False)
load_dotenv(_ROOT / ".env", override=False)

# ---- 类型化配置项（业务 / 其他层只从这里读，禁止再直接 os.getenv）----

MYSQL_URL: str | None = os.getenv("MYSQL_URL")

# 日志：级别 / 目录 / 文件名 / 是否输出控制台（生产默认只落文件）
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE_NAME: str = os.getenv("LOG_FILE_NAME", "app.log")
LOG_TO_CONSOLE: bool = os.getenv(
    "LOG_TO_CONSOLE", "false" if IS_PROD else "true"
).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_log_dir() -> Path:
    """日志目录：相对路径锚定到仓库根，规避 uvicorn 工作目录漂移。"""
    raw = os.getenv("LOG_DIR", "logs")
    path = Path(raw)
    return path if path.is_absolute() else _ROOT / path


LOG_DIR: Path = _resolve_log_dir()


def _resolve_upload_dir() -> Path:
    """上传根目录：与日志目录一致，相对路径锚定仓库根。"""
    raw = os.getenv("UPLOAD_DIR", "uploads")
    path = Path(raw)
    return path if path.is_absolute() else _ROOT / path


# 上传文件根目录：/uploads 由 main.py 挂载为静态目录。
# 通用文档默认上限 10MB；图片会写入头像字段，沿用更严格的 2MB 上限。
# 路由先按通用上限多读 1 字节，由业务层按识别结果判断是否超限。
UPLOAD_DIR: Path = _resolve_upload_dir()
FILE_MAX_BYTES: int = int(os.getenv("FILE_MAX_BYTES", str(10 * 1024 * 1024)))
AVATAR_MAX_BYTES: int = int(os.getenv("AVATAR_MAX_BYTES", str(2 * 1024 * 1024)))


def get_mysql_url() -> str:
    """返回 MySQL 连接串（形如 mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4）。

    未配置时立即报错，避免 None 被拼进连接串导致更难定位的问题。
    """
    if not MYSQL_URL:
        raise RuntimeError(
            "环境变量 MYSQL_URL 未配置，请复制 .env.example 为 .env 并填写连接串"
        )
    return MYSQL_URL


# ---- JWT 鉴权配置（密钥只走环境变量，禁止硬编码）----

JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
JWT_SECRET: str | None = os.getenv("JWT_SECRET")

# ---- MinIO 对象存储配置（连接信息只走环境变量）----

MINIO_ENDPOINT: str | None = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY: str | None = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY: str | None = os.getenv("MINIO_SECRET_KEY")
MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "ai-resource")
MINIO_SECURE: bool = os.getenv("MINIO_SECURE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


# ---- AI 对话配置（OpenAI 兼容协议）----
# provider 只影响 base_url 默认值；任意兼容 OpenAI 协议的服务也可用 LLM_BASE_URL 显式指定。
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_MODEL: str | None = os.getenv("LLM_MODEL")
LLM_API_KEY: str | None = os.getenv("LLM_API_KEY")
LLM_BASE_URL: str | None = os.getenv("LLM_BASE_URL")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "1"))

# 记忆层：取最近 N 轮（一问一答为一轮）已完成消息作为上下文
MEMORY_MAX_TURNS: int = int(os.getenv("MEMORY_MAX_TURNS", "10"))
# 单条历史消息注入上下文的最大字符数：附件提取文本可能很长，超限截断避免撑爆上下文
MEMORY_MESSAGE_MAX_CHARS: int = int(os.getenv("MEMORY_MESSAGE_MAX_CHARS", "4000"))

_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}


class LLMConfig(NamedTuple):
    """大模型连接参数（OpenAI 兼容协议）。"""

    provider: str
    model: str
    api_key: str
    base_url: str
    temperature: float
    timeout: float
    max_retries: int


def get_llm_config() -> LLMConfig:
    """返回大模型配置；缺失时立即报错（与 get_mysql_url 一致）。

    延迟到调用时校验，而不是启动即失败：未配置 AI 密钥时其他接口仍应可用，
    只有流式对话接口返回 503。
    """
    if not LLM_API_KEY:
        raise RuntimeError("环境变量 LLM_API_KEY 未配置，流式对话接口不可用")
    if not LLM_MODEL:
        raise RuntimeError("环境变量 LLM_MODEL 未配置（如 deepseek-chat / gpt-4o-mini）")

    base_url = LLM_BASE_URL or _PROVIDER_BASE_URLS.get(LLM_PROVIDER)
    if not base_url:
        raise RuntimeError(
            f"未知的 LLM_PROVIDER={LLM_PROVIDER}，请配置 LLM_BASE_URL"
        )

    return LLMConfig(
        provider=LLM_PROVIDER,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=base_url.rstrip("/"),
        temperature=LLM_TEMPERATURE,
        timeout=LLM_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )


# ---- Redis 配置（提示词版本管理的缓存，连接信息只走环境变量）----
REDIS_HOST: str = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
# 默认 db1：与其他项目常用的 db0 隔离；可用 REDIS_DB 覆盖
REDIS_DB: int = int(os.getenv("REDIS_DB", "1"))
REDIS_PASSWORD: str | None = os.getenv("REDIS_PASSWORD")
# 生效提示词缓存：Redis Hash，字段为 `{agent}:{scene}` / `common:common`
PROMPT_CACHE_KEY: str = os.getenv("PROMPT_CACHE_KEY", "prompt:templates:active")


class RedisConfig(NamedTuple):
    """Redis 客户端连接参数。"""

    host: str
    port: int
    db: int
    password: str | None


def get_redis_config() -> RedisConfig:
    """返回 Redis 配置。

    与 AI / MinIO 一致采用延迟校验：Redis 不可用时提示词接口回源数据库，
    不影响其他接口启动。
    """
    return RedisConfig(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD or None,
    )


# ---- RAG 知识库向量化配置（DashScope 向量化 + Qdrant 持久化）----
# 密钥只走环境变量；Qdrant 默认本机 6333，部署时按实际地址覆盖。
DASHSCOPE_API_KEY: str | None = os.getenv("DASHSCOPE_API_KEY")
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))


class MinioConfig(NamedTuple):
    """MinIO 客户端连接参数。"""

    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool


def get_minio_config() -> MinioConfig:
    """返回 MinIO 连接配置；缺失时立即报错（与 get_mysql_url 一致）。"""
    if not (MINIO_ENDPOINT and MINIO_ACCESS_KEY and MINIO_SECRET_KEY):
        raise RuntimeError(
            "MinIO 配置缺失，请配置 MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY"
        )
    return MinioConfig(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        bucket=MINIO_BUCKET,
        secure=MINIO_SECURE,
    )


def get_jwt_secret() -> str:
    """返回 JWT 签名密钥。

    未配置时立即报错（与 get_mysql_url 一致）：密钥缺失属于致命配置问题，
    宁可启动失败，也不要带病运行或退回不安全的默认值。
    """
    if not JWT_SECRET:
        raise RuntimeError(
            "环境变量 JWT_SECRET 未配置，请在 .env 中设置一个足够随机的密钥"
        )
    return JWT_SECRET


