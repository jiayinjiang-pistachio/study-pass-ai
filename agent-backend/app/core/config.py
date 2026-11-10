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
# 预签名 URL 有效期：历史消息每次读取都会重新续签，默认 7 天（MinIO 单次上限）
MINIO_PRESIGN_EXPIRE_SECONDS: int = int(
    os.getenv("MINIO_PRESIGN_EXPIRE_SECONDS", str(7 * 24 * 60 * 60))
)


# ---- Seedream 文生图（难点知识卡）----
# 密钥只走环境变量；缺失时知识卡接口返回 503，不影响其他工作流启动。
SEEDREAM_API_KEY: str | None = os.getenv("SEEDREAM_API_KEY")
SEEDREAM_BASE_URL: str = os.getenv(
    "SEEDREAM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
)
SEEDREAM_MODEL: str = os.getenv("SEEDREAM_MODEL", "doubao-seedream-4-0-250828")
# 合法值：WIDTHxHEIGHT 或 2k / 3k / 4k；默认 3:4 竖版，适配手机信息图
SEEDREAM_IMAGE_SIZE: str = os.getenv("SEEDREAM_IMAGE_SIZE", "1728x2304")
SEEDREAM_TIMEOUT: float = float(os.getenv("SEEDREAM_TIMEOUT", "120"))


class SeedreamConfig(NamedTuple):
    """Seedream 文生图连接参数。"""

    api_key: str
    base_url: str
    model: str
    image_size: str
    timeout: float


def get_seedream_config() -> SeedreamConfig:
    """返回 Seedream 配置；缺失时立即报错（与 get_llm_config 一致）。"""
    if not SEEDREAM_API_KEY:
        raise RuntimeError("环境变量 SEEDREAM_API_KEY 未配置，知识卡出图不可用")

    return SeedreamConfig(
        api_key=SEEDREAM_API_KEY,
        base_url=SEEDREAM_BASE_URL.rstrip("/"),
        model=SEEDREAM_MODEL,
        image_size=SEEDREAM_IMAGE_SIZE,
        timeout=SEEDREAM_TIMEOUT,
    )


# ---- 火山语音播客大模型（知识卡语音讲解）----
# 凭证来自语音控制台（不是 RTC）；缺失时只跳过音频，不影响知识卡图片生成。
PODCAST_TTS_APP_ID: str | None = os.getenv("PODCAST_TTS_APP_ID")
PODCAST_TTS_ACCESS_KEY: str | None = os.getenv("PODCAST_TTS_ACCESS_KEY")
PODCAST_TTS_BASE_URL: str = os.getenv(
    "PODCAST_TTS_BASE_URL", "wss://openspeech.bytedance.com"
).rstrip("/")
# 播客接口为 WebSocket（二进制协议），路径按控制台文档覆盖
PODCAST_TTS_PATH: str = os.getenv(
    "PODCAST_TTS_PATH", "/api/v3/sami/podcasttts"
)
PODCAST_TTS_RESOURCE_ID: str = os.getenv(
    "PODCAST_TTS_RESOURCE_ID", "volc.service_type.10050"
)
# 播客生成耗时明显长于出图，默认给到 5 分钟
PODCAST_TTS_TIMEOUT: float = float(os.getenv("PODCAST_TTS_TIMEOUT", "300"))


class PodcastTtsConfig(NamedTuple):
    """火山播客 WebSocket 连接参数。"""

    app_id: str
    access_key: str
    url: str
    resource_id: str
    timeout: float


def _to_ws_url(base_url: str, path: str) -> str:
    """兼容配置里写 http(s) 的情况，统一转成 ws(s) 地址。"""
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        base = f"wss://{base[len('https://'):]}"
    elif base.startswith("http://"):
        base = f"ws://{base[len('http://'):]}"
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base}{normalized_path}"


def get_podcast_tts_config() -> PodcastTtsConfig:
    """返回播客 TTS 配置；缺失时立即报错（由工作流降级为无音频）。"""
    if not PODCAST_TTS_APP_ID or not PODCAST_TTS_ACCESS_KEY:
        raise RuntimeError(
            "环境变量 PODCAST_TTS_APP_ID / PODCAST_TTS_ACCESS_KEY 未配置，"
            "知识卡音频不可用"
        )

    return PodcastTtsConfig(
        app_id=PODCAST_TTS_APP_ID,
        access_key=PODCAST_TTS_ACCESS_KEY,
        url=_to_ws_url(PODCAST_TTS_BASE_URL, PODCAST_TTS_PATH),
        resource_id=PODCAST_TTS_RESOURCE_ID,
        timeout=PODCAST_TTS_TIMEOUT,
    )


# ---- AI 对话配置（OpenAI 兼容协议）----
# provider 只影响 base_url 默认值；任意兼容 OpenAI 协议的服务也可用 LLM_BASE_URL 显式指定。
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").strip().lower()
LLM_MODEL: str | None = os.getenv("LLM_MODEL")
LLM_API_KEY: str | None = os.getenv("LLM_API_KEY")
LLM_BASE_URL: str | None = os.getenv("LLM_BASE_URL")
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "1"))

# 面试复盘：结束语音面试后是否自动在后台生成评估
# 关闭后仍可通过总控「面试复盘」能力按需生成；默认开启
INTERVIEW_EVAL_AUTO: bool = (
    os.getenv("INTERVIEW_EVAL_AUTO", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)

# 记忆层：取最近 N 轮（一问一答为一轮）已完成消息作为上下文
MEMORY_MAX_TURNS: int = int(os.getenv("MEMORY_MAX_TURNS", "8"))
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


# ---- 接口限流（Redis 集中式固定窗口，失败降级进程内）----
# 固定窗口长度（秒）；所有限流维度共用同一窗口，便于解释与验证。
RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
# 各高危接口的单窗口配额。注册沿用原有 5 次/分钟；其余按调用成本与风险设定。
RATE_LIMIT_REGISTER_MAX: int = int(os.getenv("RATE_LIMIT_REGISTER_MAX", "5"))
RATE_LIMIT_CHAT_MAX: int = int(os.getenv("RATE_LIMIT_CHAT_MAX", "20"))
RATE_LIMIT_UPLOAD_MAX: int = int(os.getenv("RATE_LIMIT_UPLOAD_MAX", "10"))
RATE_LIMIT_WORKFLOW_MAX: int = int(os.getenv("RATE_LIMIT_WORKFLOW_MAX", "5"))
# Redis key 前缀：ratelimit:{scope}:{identity}
RATE_LIMIT_KEY_PREFIX: str = os.getenv("RATE_LIMIT_KEY_PREFIX", "ratelimit")
# 计数后端：redis（多实例共享）| memory（仅进程内，测试 / 单机调试）
RATE_LIMIT_BACKEND: str = os.getenv("RATE_LIMIT_BACKEND", "redis").strip().lower()
# Redis 故障降级日志的最小间隔（秒），避免每次请求都刷屏
RATE_LIMIT_FALLBACK_LOG_INTERVAL: int = int(
    os.getenv("RATE_LIMIT_FALLBACK_LOG_INTERVAL", "30")
)


# ---- RAG 知识库向量化配置（DashScope 向量化 + Qdrant 持久化）----
# 密钥只走环境变量；Qdrant 默认本机 6333，部署时按实际地址覆盖。
DASHSCOPE_API_KEY: str | None = os.getenv("DASHSCOPE_API_KEY")
QDRANT_HOST: str = os.getenv("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))

# ---- 火山引擎 OCR（扫描版 PDF 文本识别）----
# 仅在 PDF 文本层稀疏、判定为扫描件时使用；缺失时扫描件入库失败并记录日志。
VOLC_ACCESS_KEY: str | None = os.getenv("VOLC_ACCESS_KEY")
VOLC_SECRET_KEY: str | None = os.getenv("VOLC_SECRET_KEY")
VOLC_REGION: str = os.getenv("VOLC_REGION", "cn-north-1")

# ---- 火山 RTC 实时语音面试（AI 面试官）----
# 应用凭证只走环境变量；缺失时不阻断面试确认，仅不返回入房 token、不启动 AI。
VOLC_RTC_APP_ID: str | None = os.getenv("VOLC_RTC_APP_ID")
VOLC_RTC_APP_KEY: str | None = os.getenv("VOLC_RTC_APP_KEY")
# 前端入房 token 有效期（秒），默认 6 小时
VOLC_RTC_TOKEN_TTL_SECONDS: int = int(
    os.getenv("VOLC_RTC_TOKEN_TTL_SECONDS", "21600")
)
# 豆包语音合成音色与可选凭证（凭证缺失时由 RTC 服务端默认配置兜底）
VOLC_RTC_TTS_SPEAKER: str = os.getenv(
    "VOLC_RTC_TTS_SPEAKER", "zh_female_linjianvhai_moon_bigtts"
)
VOLC_RTC_TTS_APP_ID: str | None = os.getenv("VOLC_RTC_TTS_APP_ID")
VOLC_RTC_TTS_ACCESS_TOKEN: str | None = os.getenv("VOLC_RTC_TTS_ACCESS_TOKEN")
# 流式语音识别可选凭证（bigmodel 模式需要）
VOLC_RTC_ASR_APP_ID: str | None = os.getenv("VOLC_RTC_ASR_APP_ID")
VOLC_RTC_ASR_ACCESS_TOKEN: str | None = os.getenv("VOLC_RTC_ASR_ACCESS_TOKEN")
# 判停静音时长（毫秒，官方允许 [500, 3000)）：面试场景语速较慢、思考停顿多，
# 默认 1500ms，避免用户句间停顿被误判为回答结束；AIVAD 开启语义判停，
# 语义不完整时会等到静音超过 2 秒才结束本轮。
VOLC_RTC_VAD_SILENCE_TIME_MS: int = int(
    os.getenv("VOLC_RTC_VAD_SILENCE_TIME_MS", "1500")
)
VOLC_RTC_AIVAD: bool = (
    os.getenv("VOLC_RTC_AIVAD", "true").strip().lower() in {"1", "true", "yes", "on"}
)
# AI 面试官开场白、LLM 带入的历史轮数、静默超时（秒）与字幕开关
VOLC_RTC_WELCOME_MESSAGE: str = os.getenv(
    "VOLC_RTC_WELCOME_MESSAGE", "你好，我是本场面试的 AI 面试官，我们现在开始。"
)
VOLC_RTC_HISTORY_LENGTH: int = int(os.getenv("VOLC_RTC_HISTORY_LENGTH", "10"))
VOLC_RTC_IDLE_TIMEOUT: int = int(os.getenv("VOLC_RTC_IDLE_TIMEOUT", "180"))
VOLC_RTC_SUBTITLE_MODE: int = int(os.getenv("VOLC_RTC_SUBTITLE_MODE", "0"))


class RTCConfig(NamedTuple):
    """火山 RTC 语音面试连接与默认参数。"""

    app_id: str
    app_key: str
    token_ttl_seconds: int
    tts_speaker: str
    tts_app_id: str | None
    tts_access_token: str | None
    asr_app_id: str | None
    asr_access_token: str | None
    vad_silence_time_ms: int
    aivad: bool
    welcome_message: str
    history_length: int
    idle_timeout: int
    subtitle_mode: int


def has_rtc_config() -> bool:
    """RTC 应用凭证是否齐全；缺失时语音面试降级为「只建面试、不启动 AI」。"""
    return bool(VOLC_RTC_APP_ID and VOLC_RTC_APP_KEY)


def get_rtc_config() -> RTCConfig:
    """返回 RTC 配置；缺失时立即报错（与 get_llm_config 一致）。

    延迟到调用时校验：未配置 RTC 时其他接口仍应可用，确认面试也不会因此失败。
    """
    if not VOLC_RTC_APP_ID or not VOLC_RTC_APP_KEY:
        raise RuntimeError(
            "环境变量 VOLC_RTC_APP_ID / VOLC_RTC_APP_KEY 未配置，语音面试不可用"
        )

    return RTCConfig(
        app_id=VOLC_RTC_APP_ID,
        app_key=VOLC_RTC_APP_KEY,
        token_ttl_seconds=VOLC_RTC_TOKEN_TTL_SECONDS,
        tts_speaker=VOLC_RTC_TTS_SPEAKER,
        tts_app_id=VOLC_RTC_TTS_APP_ID,
        tts_access_token=VOLC_RTC_TTS_ACCESS_TOKEN,
        asr_app_id=VOLC_RTC_ASR_APP_ID,
        asr_access_token=VOLC_RTC_ASR_ACCESS_TOKEN,
        vad_silence_time_ms=VOLC_RTC_VAD_SILENCE_TIME_MS,
        aivad=VOLC_RTC_AIVAD,
        welcome_message=VOLC_RTC_WELCOME_MESSAGE,
        history_length=VOLC_RTC_HISTORY_LENGTH,
        idle_timeout=VOLC_RTC_IDLE_TIMEOUT,
        subtitle_mode=VOLC_RTC_SUBTITLE_MODE,
    )


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


