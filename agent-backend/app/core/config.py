"""应用配置：从环境变量 / .env 读取，集中管理敏感配置（如 MySQL 连接串）。

约定（见 AGENTS.md §5）：数据库口令等只放环境变量，禁止硬编码、禁止提交。
本模块是配置的唯一读取入口，其他层通过 get_mysql_url() 取连接串，不直接碰 os.getenv。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 仓库根目录：本文件位于 app/core/config.py，向上三级即 agent-backend/
_ROOT = Path(__file__).resolve().parents[2]
# 存在才加载，缺失不报错（CI / 生产可直接用真实环境变量）
load_dotenv(_ROOT / ".env")

MYSQL_URL: str | None = os.getenv("MYSQL_URL")


def get_mysql_url() -> str:
    """返回 MySQL 连接串（形如 mysql+pymysql://user:pwd@host:3306/db?charset=utf8mb4）。

    未配置时立即报错，避免 None 被拼进连接串导致更难定位的问题。
    """
    if not MYSQL_URL:
        raise RuntimeError(
            "环境变量 MYSQL_URL 未配置，请复制 .env.example 为 .env 并填写连接串"
        )
    return MYSQL_URL
