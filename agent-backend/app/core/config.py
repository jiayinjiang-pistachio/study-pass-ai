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
