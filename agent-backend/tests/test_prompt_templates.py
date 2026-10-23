"""提示词版本管理接口测试。

覆盖：7 个智能体映射、公共通用模板（common:common）、公共 + 私有拼接、
版本自增、单一生效、一键回滚、Redis 缓存回填与失效、作用域校验。
模板写入功能暂未提供，测试数据直接写表构造。
依赖本地 MySQL（先 alembic upgrade head）；Redis 不可用时缓存用例自动跳过。
"""

import json
import uuid

import httpx
import pytest
from sqlalchemy import delete as sa_delete, select

from app.core import redis_client
from app.core.config import PROMPT_CACHE_KEY
from app.db.models import PromptTemplate
from app.db.session import SessionLocal
from app.services import prompt_template_service

# 本轮测试专用的描述前缀：只清理本文件创建的模板，避免误删真实数据
PROMPT_PREFIX = f"smoke_prompt_{uuid.uuid4().hex[:6]}_"

PUBLIC_FIELD = "common:common"


def _sync_cache() -> None:
    """把数据库中的生效模板同步进缓存；Redis 不可用时忽略。"""
    try:
        prompt_template_service.load_active_templates()
    except Exception:
        pass


def _cleanup() -> None:
    """删除测试模板并让缓存与数据库重新对齐。"""
    # LIKE 中 _ / % 是通配符，前缀带下划线，必须转义后才按字面匹配
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
def cleanup_prompt_templates() -> None:
    """每个用例前后清理测试模板，避免版本链相互影响。"""
    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def redis_ready() -> None:
    """缓存用例依赖真实 Redis；不可用时跳过。"""
    try:
        if not redis_client.get_client().ping():
            raise RuntimeError("ping 返回 false")
    except Exception as exc:
        pytest.skip(f"Redis 不可用，跳过缓存用例：{exc}")


def _payload(
    *,
    template_type: int = 2,
    agent_name: str = "common",
    scene: str = "common",
    content: str = "公共通用模板：请用中文回答。",
    variables: list[str] | None = None,
    description: str | None = None,
) -> dict:
    body: dict = {
        "agent_name": agent_name,
        "scene": scene,
        "template_type": template_type,
        "template_content": content,
        "description": description or f"{PROMPT_PREFIX}{uuid.uuid4().hex[:6]}",
    }
    if variables is not None:
        body["variables"] = variables
    return body


def _create(**kwargs) -> dict:
    """直接写表造数（新建版本功能暂未提供）。"""
    body = _payload(**kwargs)
    variables = body.get("variables")
    with SessionLocal() as session:
        siblings = session.scalars(
            select(PromptTemplate).where(
                PromptTemplate.agent_name == body["agent_name"],
                PromptTemplate.scene == body["scene"],
            )
        ).all()
        for row in siblings:
            row.is_active = 0
        obj = PromptTemplate(
            agent_name=body["agent_name"],
            scene=body["scene"],
            template_type=body["template_type"],
            template_content=body["template_content"],
            variables=(
                json.dumps(variables, ensure_ascii=False) if variables else None
            ),
            description=body["description"],
            version=max((row.version for row in siblings), default=0) + 1,
            is_active=1,
        )
        session.add(obj)
        session.commit()
        session.refresh(obj)
        row = {column.name: getattr(obj, column.name) for column in obj.__table__.columns}
    _sync_cache()
    return row


def _get(template_id: int) -> dict:
    """按 id 读回版本记录（断言生效状态用）。"""
    with SessionLocal() as session:
        obj = session.get(PromptTemplate, template_id)
        return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


# ---- 鉴权与配置 ----


async def test_prompt_requires_login(client: httpx.AsyncClient) -> None:
    """未携带令牌访问提示词接口 → 401。"""
    resp = await client.get("/api/prompt/config/agents")
    assert resp.status_code == 401


async def test_list_agent_config(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """返回学面通 7 个智能体及其专属场景。"""
    resp = await client.get("/api/prompt/config/agents", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    agents = resp.json()["data"]
    assert len(agents) == 7

    by_name = {item["name"]: item for item in agents}
    assert by_name["flow_controller"]["display_name"] == "流程总控"
    assert by_name["flow_controller"]["scenes"] == ["workflow"]
    assert by_name["resume_parser"]["display_name"] == "资料解析"
    assert by_name["resume_parser"]["scenes"] == ["resume"]
    assert by_name["quiz_generate"]["scenes"] == ["quiz"]
    assert by_name["interview_host"]["scenes"] == ["interview"]
    assert by_name["interview_evaluator"]["scenes"] == ["evaluation"]
    assert by_name["difficulty_learner"]["scenes"] == ["study"]
    assert by_name["note_archiver"]["scenes"] == ["note"]
    assert all("select_mode" not in item for item in agents)


# ---- 新建版本 ----


async def test_create_public_template() -> None:
    """公共通用模板固定 common:common，类型为 2，版本从 1 开始且立即生效。"""
    data = _create(
        template_type=2,
        agent_name="common",
        scene="common",
        content="公共约束：回答要简洁。",
        variables=["language"],
    )
    assert data["agent_name"] == "common"
    assert data["scene"] == "common"
    assert data["template_type"] == 2
    assert data["version"] == 1
    assert data["is_active"] == 1
    assert json.loads(data["variables"]) == ["language"]
    assert data["created_at"] > 0


# ---- 版本链与生效规则 ----


async def test_version_increment_and_single_active() -> None:
    """同作用域版本号自增，新版本生效后旧版本自动下线。"""
    first = _create(content="v1")
    second = _create(content="v2")

    assert first["version"] == 1
    assert second["version"] == 2
    assert second["is_active"] == 1
    assert _get(first["id"])["is_active"] == 0
    assert _get(second["id"])["is_active"] == 1


async def test_rollback(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """回滚把历史版本重新置为生效，并取消当前版本。"""
    first = _create(content="v1")
    second = _create(content="v2")

    resp = await client.post(
        "/api/prompt/rollback",
        headers=auth_headers,
        json={"template_id": first["id"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == first["id"]
    assert data["version"] == 1
    assert data["is_active"] == 1
    assert _get(second["id"])["is_active"] == 0

    active = await client.get(
        "/api/prompt/templates/common/common", headers=auth_headers
    )
    assert active.json()["data"]["id"] == first["id"]


async def test_rollback_missing_404(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """回滚不存在的模板 → 404。"""
    resp = await client.post(
        "/api/prompt/rollback", headers=auth_headers, json={"template_id": 999999999}
    )
    assert resp.status_code == 404


# ---- 公共 + 私有拼接 ----


async def test_get_full_prompt(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """full-prompt 拼接公共与私有模板，同时合并去重变量。"""
    public = _create(
        template_type=2,
        content="公共：用中文回答。",
        variables=["language", "tone"],
    )
    private = _create(
        template_type=1,
        agent_name="difficulty_learner",
        scene="study",
        content="私有：先讲原理再举例。",
        variables=["tone", "difficulty"],
    )

    resp = await client.get(
        "/api/prompt/full-prompt",
        params={"agent_name": "difficulty_learner", "scene": "study"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["agent_name"] == "difficulty_learner"
    assert data["scene"] == "study"
    assert data["public_template"]["id"] == public["id"]
    assert data["private_template"]["id"] == private["id"]
    assert data["final_template"] == "公共：用中文回答。\n\n私有：先讲原理再举例。"
    assert data["variables"] == ["language", "tone", "difficulty"]

    # 作用域接口只返回私有版本，不含公共模板
    scope = await client.get(
        "/api/prompt/templates/difficulty_learner/study", headers=auth_headers
    )
    assert scope.status_code == 200, scope.text
    scope_data = scope.json()["data"]
    assert scope_data["id"] == private["id"]
    assert "private_template" not in scope_data


async def test_get_public_only_via_common(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """common/common 只返回公共通用模板，不拼接私有模板。"""
    public = _create(content="公共通用模板")
    _create(
        template_type=1,
        agent_name="difficulty_learner",
        scene="study",
        content="私有模板",
    )

    resp = await client.get(
        "/api/prompt/full-prompt",
        params={"agent_name": "common", "scene": "common"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["agent_name"] == "common"
    assert data["scene"] == "common"
    assert data["public_template"]["id"] == public["id"]
    assert data["private_template"] is None
    assert data["final_template"] == "公共通用模板"


async def test_get_missing_template_404(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """作用域内没有生效模板 → 404；未知智能体 / 公共入口场景错误同样 404。"""
    resp = await client.get(
        "/api/prompt/templates/difficulty_learner/study", headers=auth_headers
    )
    assert resp.status_code == 404

    resp = await client.get(
        "/api/prompt/full-prompt",
        params={"agent_name": "difficulty_learner", "scene": "study"},
        headers=auth_headers,
    )
    assert resp.status_code == 404

    resp = await client.get(
        "/api/prompt/templates/not_exists/study", headers=auth_headers
    )
    assert resp.status_code == 404

    resp = await client.get(
        "/api/prompt/templates/common/study", headers=auth_headers
    )
    assert resp.status_code == 404

    resp = await client.get(
        "/api/prompt/full-prompt",
        params={"agent_name": "common", "scene": "study"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_create_endpoint_removed(
    client: httpx.AsyncClient, auth_headers: dict
) -> None:
    """对外不再提供新建版本接口：POST /templates 不存在。"""
    resp = await client.post(
        "/api/prompt/templates", headers=auth_headers, json={}
    )
    assert resp.status_code == 404


# ---- Redis 缓存 ----


async def test_cache_populated_and_rebuilt(
    client: httpx.AsyncClient,
    auth_headers: dict,
    redis_ready: None,
) -> None:
    """新建后缓存字段即时更新；缓存被清空时可回源数据库并重新回填。"""
    created = _create(
        template_type=1,
        agent_name="difficulty_learner",
        scene="study",
        content="私有模板",
    )

    client_redis = redis_client.get_client()
    cached = client_redis.hget(
        PROMPT_CACHE_KEY, "difficulty_learner:study"
    )
    assert cached is not None
    assert f'"version": {created["version"]}' in cached

    # 模拟缓存丢失：读取接口应回源数据库，并把结果重新写回缓存
    client_redis.delete(PROMPT_CACHE_KEY)
    resp = await client.get(
        "/api/prompt/templates/difficulty_learner/study", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["id"] == created["id"]
    assert client_redis.hget(PROMPT_CACHE_KEY, "difficulty_learner:study")


async def test_startup_load_active_templates(redis_ready: None) -> None:
    """启动预热把全部生效模板写入 Hash，同时清掉已失效的历史字段。"""
    public = _create(content="公共通用模板")
    private = _create(
        template_type=1,
        agent_name="note_archiver",
        scene="note",
        content="私有模板",
    )

    client_redis = redis_client.get_client()
    client_redis.hset(PROMPT_CACHE_KEY, "stale:field", "{}")
    count = prompt_template_service.load_active_templates()

    assert count == 2
    assert client_redis.hget(PROMPT_CACHE_KEY, PUBLIC_FIELD) is not None
    assert client_redis.hget(PROMPT_CACHE_KEY, "note_archiver:note") is not None
    assert client_redis.hget(PROMPT_CACHE_KEY, "stale:field") is None

    loaded_public = client_redis.hget(PROMPT_CACHE_KEY, PUBLIC_FIELD)
    assert f'"id": {public["id"]}' in loaded_public
    assert f'"id": {private["id"]}' in client_redis.hget(
        PROMPT_CACHE_KEY, "note_archiver:note"
    )
