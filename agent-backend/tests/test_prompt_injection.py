"""提示词变量注入测试：验证层 / 转换层 / 填充层 + full-prompt 接口集成。

覆盖：控制字符与模板符号清洗、长度截断、数组格式化、默认值、年限格式化、
占位符替换（重复 / 未声明 / 注入值不被二次解析），以及按登录用户资料注入。
依赖本地 MySQL（先 alembic upgrade head）；Redis 不可用时自动回源数据库。
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import delete as sa_delete, select

from app.db import user_profile_repo
from app.db.models import PromptTemplate
from app.db.session import SessionLocal
from app.services import prompt_injection_service, prompt_template_service

# 只清理本文件创建的模板，避免误删真实数据与其他用例的数据
PROMPT_PREFIX = f"smoke_inject_{uuid.uuid4().hex[:6]}_"


def _sync_cache() -> None:
    """把数据库中的生效模板同步进缓存；Redis 不可用时忽略。"""
    try:
        prompt_template_service.load_active_templates()
    except Exception:
        pass


def _cleanup_templates() -> None:
    """删除本文件创建的模板并让缓存与数据库重新对齐。"""
    escaped = PROMPT_PREFIX.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with SessionLocal() as session:
        session.execute(
            sa_delete(PromptTemplate).where(
                PromptTemplate.description.like(f"{escaped}%", escape="\\")
            )
        )
        session.commit()
    _sync_cache()


@pytest.fixture(autouse=True)
def cleanup_injection_templates(isolated_prompt_templates: None) -> None:
    """每个用例前后清理测试模板，并隔离 init_prompt 写入的种子数据。

    用例结束后 isolated_prompt_templates 会把开发库原有模板原样还原。
    """
    _cleanup_templates()
    yield
    _cleanup_templates()


def _create_template(
    *,
    agent_name: str = "common",
    scene: str = "common",
    template_type: int = 2,
    content: str,
    variables: list[str] | None = None,
) -> dict:
    """直接写表造数（新建版本功能暂未提供），新版本立即生效。"""
    with SessionLocal() as session:
        siblings = session.scalars(
            select(PromptTemplate).where(
                PromptTemplate.agent_name == agent_name,
                PromptTemplate.scene == scene,
            )
        ).all()
        for row in siblings:
            row.is_active = 0
        obj = PromptTemplate(
            agent_name=agent_name,
            scene=scene,
            template_type=template_type,
            template_content=content,
            variables=json.dumps(variables, ensure_ascii=False) if variables else None,
            description=f"{PROMPT_PREFIX}{uuid.uuid4().hex[:6]}",
            version=max((row.version for row in siblings), default=0) + 1,
            is_active=1,
        )
        session.add(obj)
        session.commit()
        session.refresh(obj)
        row = {column.name: getattr(obj, column.name) for column in obj.__table__.columns}
    _sync_cache()
    return row


# ---- 验证层 ----


def test_sanitize_text_strips_control_and_template_chars() -> None:
    """控制字符 / 换行折叠为空格，花括号与反斜杠被移除。"""
    raw = "Python\n开发\x00工程师\t{target_job}\\"
    assert prompt_injection_service.sanitize_text(raw) == "Python 开发 工程师 target_job"


def test_sanitize_text_truncates() -> None:
    """超长标量按上限截断。"""
    text = prompt_injection_service.sanitize_text("a" * 500)
    assert len(text) == prompt_injection_service.SCALAR_MAX_CHARS


def test_sanitize_items_dedupes_and_limits() -> None:
    """数组逐项清洗、去空去重，并限制项数与单项长度。"""
    values = ["Python", "Python", "", None, "x" * 200] + [f"s{i}" for i in range(50)]
    items = prompt_injection_service.sanitize_items(values)

    assert items[0] == "Python"
    assert len(items) == prompt_injection_service.MAX_ITEMS
    assert len(items[1]) == prompt_injection_service.ITEM_MAX_CHARS
    assert len(set(items)) == len(items)


def test_sanitize_items_ignores_non_list() -> None:
    """非数组一律按空数组处理。"""
    assert prompt_injection_service.sanitize_items("Python") == []
    assert prompt_injection_service.sanitize_items(None) == []


# ---- 转换层 ----


def test_build_variables_formats_profile() -> None:
    """资料字段格式化为文本：数组用「、」连接，年限按 0 / N 格式化。"""
    profile = {
        "target_job": "后端工程师",
        "years_experience": 3,
        "target_level": "P6",
        "target_skills": ["Python", "MySQL"],
        "weak_topics": ["分布式", "缓存"],
    }
    declared = list(prompt_injection_service.PROFILE_VARIABLES)

    assert prompt_injection_service.build_variables(profile, declared) == {
        "target_job": "后端工程师",
        "years_experience": "3 年",
        "target_level": "P6",
        "target_skills": "Python、MySQL",
        "weak_topics": "分布式、缓存",
    }


def test_build_variables_defaults_and_years() -> None:
    """缺失字段走默认值；年限 0 视为应届，缺失 / 非法视为未提供。"""
    declared = list(prompt_injection_service.PROFILE_VARIABLES)

    empty = prompt_injection_service.build_variables(None, declared)
    assert empty["target_job"] == "未提供"
    assert empty["years_experience"] == "未提供"
    assert empty["target_level"] == "未提供"
    assert empty["target_skills"] == "暂无"
    assert empty["weak_topics"] == "暂无"

    zero = prompt_injection_service.build_variables({"years_experience": 0}, declared)
    assert zero["years_experience"] == "应届/无经验"

    invalid = prompt_injection_service.build_variables(
        {"years_experience": "三年"}, declared
    )
    assert invalid["years_experience"] == "未提供"


def test_build_variables_only_declared() -> None:
    """只转换模板声明过的变量。"""
    result = prompt_injection_service.build_variables(
        {"target_job": "前端", "target_skills": ["Vue"]},
        ["target_job"],
    )
    assert result == {"target_job": "前端"}


def test_build_variables_respects_total_limit() -> None:
    """多变量合计长度受总上限约束。"""
    big = [("s" * 45) + str(i).zfill(5) for i in range(20)]
    profile = {
        "target_job": "j" * 100,
        "target_level": "l" * 100,
        "target_skills": big,
        "weak_topics": big,
    }
    result = prompt_injection_service.build_variables(
        profile, list(prompt_injection_service.PROFILE_VARIABLES)
    )
    assert sum(len(value) for value in result.values()) <= (
        prompt_injection_service.TOTAL_MAX_CHARS
    )


# ---- 填充层 ----


def test_render_template_replaces_and_keeps_unknown() -> None:
    """重复占位符全部替换，未声明的占位符保持原样。"""
    template = "{target_job} / {target_job} / {unknown}"
    rendered = prompt_injection_service.render_template(
        template, {"target_job": "后端"}
    )
    assert rendered == "后端 / 后端 / {unknown}"


def test_render_template_does_not_reparse_values() -> None:
    """注入值按字面插入，即使包含花括号也不会被二次解析。"""
    rendered = prompt_injection_service.render_template(
        "{tone}", {"tone": "{target_job}"}
    )
    assert rendered == "{target_job}"


# ---- 接口集成 ----


async def test_full_prompt_injects_user_profile(
    client: httpx.AsyncClient, auth_headers: dict, auth_user: dict
) -> None:
    """full-prompt 按当前登录用户资料渲染模板。"""
    _create_template(
        content="目标岗位：{target_job}；等级：{target_level}",
        variables=["target_job", "target_level"],
    )
    _create_template(
        agent_name="difficulty_learner",
        scene="study",
        template_type=1,
        content=(
            "技能：{target_skills}；薄弱点：{weak_topics}；"
            "年限：{years_experience}；未声明：{not_declared}"
        ),
        variables=["target_skills", "weak_topics", "years_experience"],
    )
    user_profile_repo.upsert(
        auth_user["id"],
        {
            "target_job": "后端工程师",
            "years_experience": 3,
            "target_level": "P6",
            "target_skills": ["Python", "MySQL"],
            "weak_topics": ["分布式"],
        },
    )

    resp = await client.get(
        "/api/prompt/full-prompt",
        params={"agent_name": "difficulty_learner", "scene": "study"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["rendered_template"] == (
        "目标岗位：后端工程师；等级：P6\n\n"
        "技能：Python、MySQL；薄弱点：分布式；年限：3 年；未声明：{not_declared}"
    )
    assert data["injected_variables"] == {
        "target_job": "后端工程师",
        "years_experience": "3 年",
        "target_level": "P6",
        "target_skills": "Python、MySQL",
        "weak_topics": "分布式",
    }
    # final_template 保持未渲染的原始拼接
    assert "{target_job}" in data["final_template"]


async def test_full_prompt_defaults_without_profile(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """用户未填写背景资料时按默认值渲染。"""
    _create_template(
        content="岗位：{target_job}；技能：{target_skills}",
        variables=["target_job", "target_skills"],
    )

    resp = await client.get(
        "/api/prompt/full-prompt",
        params={"agent_name": "common", "scene": "common"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["rendered_template"] == "岗位：未提供；技能：暂无"
    assert data["injected_variables"] == {
        "target_job": "未提供",
        "target_skills": "暂无",
    }
