"""初始化模板数据校验：防止 agent_prompt.py 与注入白名单 / 智能体配置脱节。

只校验纯数据，不写数据库。
"""

import re

from app.services.prompt_injection_service import PROFILE_VARIABLES
from app.services.prompt_template_service import AGENT_CONFIG
from scripts import agent_prompt

PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def test_templates_cover_all_agent_scopes() -> None:
    """覆盖公共模板与全部 7 个智能体的专属场景，且无重复作用域。"""
    scopes = [(item["agent_name"], item["scene"]) for item in agent_prompt.TEMPLATES]
    assert len(scopes) == len(set(scopes)) == 8
    assert ("common", "common") in scopes

    for name, config in AGENT_CONFIG.items():
        for scene in config["scenes"]:
            assert (name, scene) in scopes, f"缺少模板：{name}:{scene}"


def test_only_v1_v2_and_declared_placeholders() -> None:
    """每个作用域只有 v1 / v2，占位符必须写进 variables，变量必须在注入白名单内。"""
    for spec in agent_prompt.TEMPLATES:
        for key in ("v1", "v2"):
            payload = spec[key]
            declared = set(payload["variables"])
            placeholders = set(PLACEHOLDER.findall(payload["content"]))

            assert payload["content"].strip()
            assert declared <= set(PROFILE_VARIABLES), (
                f"{spec['agent_name']} {key} 声明了不支持的变量：{declared - set(PROFILE_VARIABLES)}"
            )
            assert placeholders <= declared, (
                f"{spec['agent_name']} {key} 存在未声明的占位符：{placeholders - declared}"
            )


def test_demo_profile_fields_are_injectable() -> None:
    """演示资料字段必须都能被注入管线识别。"""
    assert set(agent_prompt.DEMO_PROFILE) <= set(PROFILE_VARIABLES)
