"""业务层：提示词版本管理（多智能体、公共模板、一键回滚、Redis 缓存）。

数据源始终是 MySQL `prompt_templates`，Redis Hash 只缓存「当前生效版本」：
- Hash Key：`prompt:templates:active`（`PROMPT_CACHE_KEY`）
- 私有模板字段：`{agent_name}:{scene}`；公共模板字段：`common:common`
- 缓存未命中或 Redis 不可用时回源数据库，并顺带刷新缓存。

同一作用域只有一个生效版本；回滚会把历史版本重新置为生效。
新建版本功能暂未实现，待提示词注入需求确定后再补充。
"""

import json
import logging

from fastapi import status

from ..core import redis_client
from ..core.config import PROMPT_CACHE_KEY
from ..core.exceptions import BusinessException
from ..db import prompt_template_repo
from . import prompt_injection_service

logger = logging.getLogger(__name__)

# 公共通用模板固定标识：agent_name='common' + scene='common'
PUBLIC_AGENT = "common"
PUBLIC_SCENE = "common"

# 缓存整体过期时间：多实例部署时最多 1 小时后自动回源数据库重新对齐
CACHE_TTL_SECONDS = 3600

_KNOWN_SCENES = {
    "workflow",
    "resume",
    "quiz",
    "interview",
    "evaluation",
    "study",
    "note",
    PUBLIC_SCENE,
}

# 7 个智能体映射：name 为数据库中的 agent_name，scene 为各自专属场景
AGENT_CONFIG: dict[str, dict] = {
    "flow_controller": {
        "display_name": "流程总控",
        "scenes": ["workflow"],
        "description": "多智能体流程编排与任务分发",
    },
    "resume_parser": {
        "display_name": "资料解析",
        "scenes": ["resume"],
        "description": "简历 / 资料解析与结构化信息提取",
    },
    "quiz_generate": {
        "display_name": "出题题库",
        "scenes": ["quiz"],
        "description": "生成题目与题库",
    },
    "interview_host": {
        "display_name": "面试主考官",
        "scenes": ["interview"],
        "description": "模拟面试提问与追问",
    },
    "interview_evaluator": {
        "display_name": "面试评测",
        "scenes": ["evaluation"],
        "description": "面试表现评测与反馈",
    },
    "difficulty_learner": {
        "display_name": "难点学习",
        "scenes": ["study"],
        "description": "难点讲解与针对性学习",
    },
    "note_archiver": {
        "display_name": "笔记归档",
        "scenes": ["note"],
        "description": "笔记整理、归档与结构化",
    },
}

# 缓存未命中哨兵：区分「Redis 没有该字段」与「Redis 不可用」
_CACHE_MISS = object()


def _cache_field(agent_name: str | None, scene: str) -> str:
    """缓存 Hash 字段名：私有 `{agent}:{scene}`，公共 `common:common`。"""
    return f"{agent_name or PUBLIC_AGENT}:{scene}"


def _parse_variables(raw: str | None) -> list[str]:
    """把数据库中的 JSON 字符串解析成变量列表；脏数据按空列表处理。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _to_out(row: dict) -> dict:
    """把仓储层记录裁剪成出参结构（variables 还原为列表）。"""
    return {
        "id": row["id"],
        "agent_name": row["agent_name"],
        "scene": row["scene"],
        "template_type": row["template_type"],
        "template_content": row["template_content"],
        "variables": _parse_variables(row.get("variables")),
        "version": row["version"],
        "is_active": row["is_active"],
        "description": row["description"],
        "created_at": row["created_at"],
    }


def _cache_set(field: str, row: dict) -> None:
    """写入单个作用域的缓存；Redis 异常只告警，不影响主流程。"""
    try:
        client = redis_client.get_client()
        client.hset(
            PROMPT_CACHE_KEY,
            field,
            json.dumps(_to_out(row), ensure_ascii=False),
        )
        client.expire(PROMPT_CACHE_KEY, CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("提示词缓存写入失败（已回退数据库）：%s", exc)


def _cache_delete(field: str) -> None:
    """删除单个作用域的缓存字段；Redis 异常只告警。"""
    try:
        redis_client.get_client().hdel(PROMPT_CACHE_KEY, field)
    except Exception as exc:
        logger.warning("提示词缓存删除失败：%s", exc)


def _cache_get(field: str):
    """读取缓存字段；未命中、脏数据或 Redis 不可用都返回哨兵。"""
    try:
        raw = redis_client.get_client().hget(PROMPT_CACHE_KEY, field)
    except Exception as exc:
        logger.warning("提示词缓存读取失败（已回退数据库）：%s", exc)
        return _CACHE_MISS
    if raw is None:
        return _CACHE_MISS
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return _CACHE_MISS


def load_active_templates() -> int:
    """启动时把全部生效模板预热进 Redis，返回写入条数。

    Redis 不可用时由调用方捕获并告警：后续读取会自动回源数据库。
    """
    rows = prompt_template_repo.list_active()
    mapping = {
        _cache_field(row["agent_name"], row["scene"]): json.dumps(
            _to_out(row), ensure_ascii=False
        )
        for row in rows
    }

    client = redis_client.get_client()
    pipe = client.pipeline()
    # 整体重建 Hash：清掉数据库中已不再生效的历史字段
    pipe.delete(PROMPT_CACHE_KEY)
    if mapping:
        pipe.hset(PROMPT_CACHE_KEY, mapping=mapping)
        pipe.expire(PROMPT_CACHE_KEY, CACHE_TTL_SECONDS)
    pipe.execute()

    logger.info("提示词缓存预热完成：%s 条生效模板", len(mapping))
    return len(mapping)


def _load_active(agent_name: str | None, scene: str) -> dict | None:
    """读取作用域内的生效模板：优先 Redis，未命中回源数据库并回填。"""
    field = _cache_field(agent_name, scene)
    cached = _cache_get(field)
    if cached is not _CACHE_MISS:
        return cached

    row = prompt_template_repo.get_active(agent_name, scene)
    if row is None:
        # 数据库也没有生效版本时顺手清掉可能残留的缓存字段
        _cache_delete(field)
        return None

    _cache_set(field, row)
    return _to_out(row)


def _refresh_scope(agent_name: str, scene: str) -> None:
    """模板变更后刷新该作用域的缓存字段。"""
    row = prompt_template_repo.get_active(agent_name, scene)
    field = _cache_field(agent_name, scene)
    if row is None:
        _cache_delete(field)
    else:
        _cache_set(field, row)


def _require_scene(scene: str) -> str:
    """校验场景是否已知，并返回去空白后的值。"""
    value = scene.strip()
    if value not in _KNOWN_SCENES:
        raise BusinessException(
            "提示词场景不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"scene={scene}",
        )
    return value


def _require_agent(agent_name: str) -> str:
    """校验智能体是否在 AGENT_CONFIG 中，并返回去空白后的值。"""
    value = agent_name.strip()
    if value not in AGENT_CONFIG:
        raise BusinessException(
            "智能体不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"agent_name={agent_name}",
        )
    return value


def _require_private_scope(agent_name: str, scene: str) -> None:
    """校验私有模板的 (智能体, 场景) 组合是否被支持。"""
    if scene not in AGENT_CONFIG[agent_name]["scenes"]:
        raise BusinessException(
            f"智能体 {agent_name} 不支持场景 {scene}",
            http_status=status.HTTP_400_BAD_REQUEST,
            detail=f"agent_name={agent_name} scene={scene}",
        )


def list_agents() -> list[dict]:
    """返回全部智能体配置。"""
    return [
        {"name": name, **config} for name, config in AGENT_CONFIG.items()
    ]


def get_combined_template(
    agent_name: str, scene: str, user_id: int | None = None
) -> dict:
    """读取生效模板并拼接：公共通用模板在前，私有模板在后，用空行分隔。

    agent_name='common' 且 scene='common' 时只返回公共通用模板。
    user_id 用于注入用户背景变量；为空时按默认值渲染（如通用模板预览）。
    """
    agent = agent_name.strip()

    if agent == PUBLIC_AGENT:
        # 公共入口只认 common:common，其他场景视为不存在
        if scene.strip() != PUBLIC_SCENE:
            raise BusinessException(
                "提示词模板不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"agent_name={agent_name} scene={scene}",
            )
        public = _load_active(PUBLIC_AGENT, PUBLIC_SCENE)
        private = None
        scene = PUBLIC_SCENE
    else:
        agent = _require_agent(agent)
        scene = _require_scene(scene)
        _require_private_scope(agent, scene)
        public = _load_active(PUBLIC_AGENT, PUBLIC_SCENE)
        private = _load_active(agent, scene)

    if public is None and private is None:
        raise BusinessException(
            "提示词模板不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"agent_name={agent_name} scene={scene}",
        )

    parts = [
        row["template_content"].strip()
        for row in (public, private)
        if row and row["template_content"].strip()
    ]
    variables = list(
        dict.fromkeys(
            [item for row in (public, private) if row for item in row["variables"]]
        )
    )

    final_template = "\n\n".join(parts)
    rendered_template, injected_variables = prompt_injection_service.render_for_user(
        final_template, variables, user_id
    )

    return {
        "agent_name": agent,
        "scene": scene,
        "public_template": public,
        "private_template": private,
        "final_template": final_template,
        "variables": variables,
        "rendered_template": rendered_template,
        "injected_variables": injected_variables,
    }


def get_rendered_prompt(
    agent_name: str, scene: str, user_id: int | None = None
) -> str:
    """返回公共 + 私有模板拼接并注入用户画像后的提示词文本。

    业务链路只需要最终文本；模板不存在时抛 404，由调用方决定是否降级。
    """
    return get_combined_template(agent_name, scene, user_id)["rendered_template"]


def get_active_template(agent_name: str, scene: str) -> dict:
    """读取单个作用域的生效模板（不做公共 / 私有拼接）。

    `common/common` 返回公共通用模板；其余返回该智能体专属场景的私有模板。
    """
    agent = agent_name.strip()

    if agent == PUBLIC_AGENT:
        if scene.strip() != PUBLIC_SCENE:
            raise BusinessException(
                "提示词模板不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"agent_name={agent_name} scene={scene}",
            )
        scene = PUBLIC_SCENE
    else:
        agent = _require_agent(agent)
        scene = _require_scene(scene)
        _require_private_scope(agent, scene)

    row = _load_active(agent, scene)
    if row is None:
        raise BusinessException(
            "提示词模板不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"agent_name={agent_name} scene={scene}",
        )
    return row


def rollback(template_id: int) -> dict:
    """一键回滚：把指定历史版本重新置为生效。"""
    row = prompt_template_repo.activate(template_id)
    if row is None:
        raise BusinessException(
            "提示词模板不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"template_id={template_id}",
        )

    _refresh_scope(row["agent_name"], row["scene"])
    return _to_out(row)
