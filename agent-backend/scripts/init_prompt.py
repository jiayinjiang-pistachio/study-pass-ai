"""初始化提示词模板与演示用户背景资料。

数据源：scripts/agent_prompt.py（TEMPLATES / DEMO_USER / DEMO_PROFILE）。

写入规则：
- prompt_templates：每个作用域只维护 v1 / v2；v2 为生效版本，v1 作为回滚目标。
  重复执行会原地更新这两个版本，不产生新版本。
- user_profiles：默认创建（或重置密码）演示用户 prompt_demo，并写入其背景资料；
  也可用 --username 指定已有用户，只写该用户的资料。
- 最后刷新 Redis 提示词缓存（Redis 不可用时仅告警，读取时会回源 MySQL）。

用法：
    source .venv/bin/activate
    python scripts/init_prompt.py
    python scripts/init_prompt.py --username bob
"""

import argparse
import json
import sys
from pathlib import Path

# 允许直接 `python scripts/init_prompt.py`：把仓库根与 scripts 目录加入导入路径
_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
for path in (str(_ROOT), str(_SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from sqlalchemy import select

import agent_prompt
from app.core.security import hash_password
from app.db import user_profile_repo, user_repo
from app.db.models import PromptTemplate
from app.db.session import SessionLocal
from app.services import prompt_template_service

# 作用域内固定的两个版本号：v2 生效，v1 保留用于演示回滚
VERSION_SPECS = (("v1", 1), ("v2", 2))
ACTIVE_VERSION = 2


def _sync_templates() -> list[dict]:
    """把 TEMPLATES 同步进 prompt_templates，返回作用域与版本 id 概览。"""
    summary: list[dict] = []
    with SessionLocal() as session:
        for spec in agent_prompt.TEMPLATES:
            rows = session.scalars(
                select(PromptTemplate).where(
                    PromptTemplate.agent_name == spec["agent_name"],
                    PromptTemplate.scene == spec["scene"],
                )
            ).all()
            by_version = {row.version: row for row in rows}

            for key, version in VERSION_SPECS:
                payload = spec[key]
                row = by_version.get(version)
                if row is None:
                    row = PromptTemplate(
                        agent_name=spec["agent_name"],
                        scene=spec["scene"],
                        version=version,
                    )
                    session.add(row)
                    by_version[version] = row

                row.template_type = spec["template_type"]
                row.template_content = payload["content"].strip()
                variables = payload.get("variables") or []
                row.variables = json.dumps(variables, ensure_ascii=False) if variables else None
                row.description = payload.get("description") or (
                    f"{spec['display_name']} v{version}"
                )
                row.is_active = 1 if version == ACTIVE_VERSION else 0

            # 兜底：若历史上存在 v3 等多余版本，一律下线，保证单一生效
            for row in rows:
                if row.version not in {version for _, version in VERSION_SPECS}:
                    row.is_active = 0

            session.flush()
            summary.append(
                {
                    "scope": f"{spec['agent_name']}:{spec['scene']}",
                    "display_name": spec["display_name"],
                    "ids": {version: by_version[version].id for _, version in VERSION_SPECS},
                }
            )

        session.commit()
    return summary


def _resolve_user(username: str | None) -> tuple[dict, bool]:
    """返回 (用户记录, 是否新建或重置了演示密码)。"""
    if username:
        user = user_repo.find_by_username(username)
        if user is None:
            raise SystemExit(f"用户 {username} 不存在，请先注册或改用默认演示用户")
        return user, False

    demo = agent_prompt.DEMO_USER
    user = user_repo.find_by_username(demo["username"])
    if user is None:
        user = user_repo.insert(
            {
                "username": demo["username"],
                "password": hash_password(demo["password"]),
            }
        )
        return user, True

    # 演示账号的密码固定，保证操作指南中的登录步骤可重复复现
    user_repo.update(user["id"], {"password": hash_password(demo["password"])})
    return user, True


def _refresh_cache() -> bool:
    """刷新 Redis 缓存；Redis 不可用不影响初始化结果。"""
    try:
        prompt_template_service.load_active_templates()
        return True
    except Exception as exc:  # noqa: BLE001 - 初始化脚本需要对任何 Redis 故障降级
        print(f"⚠ Redis 缓存刷新失败（读取时会回源 MySQL）：{exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化智能体提示词与用户背景资料")
    parser.add_argument(
        "--username",
        help="把演示背景资料写入已有用户；缺省则创建/复用 prompt_demo 演示账号",
    )
    args = parser.parse_args()

    summary = _sync_templates()
    user, demo_ready = _resolve_user(args.username)
    user_profile_repo.upsert(user["id"], dict(agent_prompt.DEMO_PROFILE))
    cache_ok = _refresh_cache()

    print("✔ 提示词模板已同步（每作用域 v1 历史 / v2 生效）：")
    print(f"  {'作用域':<32}{'v1_id':>8}{'v2_id':>8}")
    for item in summary:
        ids = item["ids"]
        print(f"  {item['scope']:<32}{ids[1]:>8}{ids[2]:>8}")

    print(f"\n✔ 用户背景资料已写入：user_id={user['id']}，username={user['username']}")
    profile = agent_prompt.DEMO_PROFILE
    print(
        f"  target_job={profile['target_job']}，years_experience={profile['years_experience']}，"
        f"target_level={profile['target_level']}"
    )
    if demo_ready:
        print(
            f"  演示账号：{agent_prompt.DEMO_USER['username']} / "
            f"{agent_prompt.DEMO_USER['password']}"
        )

    print(f"\n✔ Redis 缓存：{'已刷新' if cache_ok else '跳过（回源 MySQL）'}")
    print(
        "\n下一步：uvicorn app.main:app --port 8000 → 打开 http://127.0.0.1:8000/docs，"
        "按 docs/prompt-injection-guide.md 验证。"
    )


if __name__ == "__main__":
    main()
