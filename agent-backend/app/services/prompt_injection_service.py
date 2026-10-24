"""业务层：提示词变量注入（验证 → 转换 → 填充三层）。

三层职责：
1. 验证层：清除控制字符 / 换行 / 花括号 / 反斜杠，限制单值与数组长度，防模板注入；
2. 转换层：把用户背景资料格式化为字符串（数组转「、」、缺失值走默认值）；
3. 填充层：按 `{变量名}` 单花括号占位符替换，未声明的占位符原样保留。

只注入模板 `variables` 中声明过的用户资料变量，用户输入永远不会被二次解析。
"""

import re

from ..db import user_profile_repo

# 单个标量最长字符数（岗位 / 等级等）
SCALAR_MAX_CHARS = 100
# 数组单个元素最长字符数（技能 / 薄弱点）
ITEM_MAX_CHARS = 50
# 数组最多元素个数
MAX_ITEMS = 20
# 一次注入的全部变量文本总长上限
TOTAL_MAX_CHARS = 1000

# 支持注入的用户资料变量，顺序即转换与截断顺序
PROFILE_VARIABLES = (
    "target_job",
    "years_experience",
    "target_level",
    "target_skills",
    "weak_topics",
)

# 占位符只认「字母或下划线开头、仅含字母数字下划线」的单花括号形式
_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# 控制字符（含换行、制表符）统一转空格
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
# 花括号与反斜杠是模板语法字符，直接移除，避免注入值被再次当作占位符
_TEMPLATE_CHAR_PATTERN = re.compile(r"[{}\\]")

# 缺失值默认文案
DEFAULT_SCALAR = "未提供"
DEFAULT_LIST = "暂无"


def sanitize_text(value: object, max_chars: int = SCALAR_MAX_CHARS) -> str:
    """验证层：把任意标量清洗为安全文本（去控制符、模板符号、折叠空白、截断）。"""
    if value is None:
        return ""
    text = str(value)
    text = _CONTROL_PATTERN.sub(" ", text)
    text = _TEMPLATE_CHAR_PATTERN.sub("", text)
    # 折叠连续空白，避免注入内容破坏提示词排版
    text = " ".join(text.split())
    return text[:max_chars].strip()


def sanitize_items(values: object) -> list[str]:
    """验证层：清洗字符串数组（逐项清洗、去空、去重、限项数）。"""
    if not isinstance(values, list):
        return []
    items: list[str] = []
    for value in values:
        item = sanitize_text(value, ITEM_MAX_CHARS)
        if item and item not in items:
            items.append(item)
        if len(items) >= MAX_ITEMS:
            break
    return items


def _format_years(value: object) -> str:
    """把工作年限格式化为文案：0 → 应届/无经验，N → N 年，缺失 → 未提供。"""
    if value is None or value == "":
        return DEFAULT_SCALAR
    try:
        years = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SCALAR
    if years <= 0:
        return "应届/无经验"
    return f"{years} 年"


def build_variables(profile: dict | None, declared: list[str]) -> dict[str, str]:
    """转换层：只保留已声明的用户资料变量，并格式化为注入文本。"""
    profile = profile or {}
    allowed = set(declared)
    raw: dict[str, str] = {}

    if "target_job" in allowed:
        raw["target_job"] = sanitize_text(profile.get("target_job")) or DEFAULT_SCALAR
    if "years_experience" in allowed:
        raw["years_experience"] = _format_years(profile.get("years_experience"))
    if "target_level" in allowed:
        raw["target_level"] = sanitize_text(profile.get("target_level")) or DEFAULT_SCALAR
    if "target_skills" in allowed:
        raw["target_skills"] = "、".join(sanitize_items(profile.get("target_skills"))) or DEFAULT_LIST
    if "weak_topics" in allowed:
        raw["weak_topics"] = "、".join(sanitize_items(profile.get("weak_topics"))) or DEFAULT_LIST

    # 按固定顺序累计长度，超出总上限后截断，保证注入文本体积可控
    result: dict[str, str] = {}
    used = 0
    for key in PROFILE_VARIABLES:
        if key not in raw:
            continue
        remaining = TOTAL_MAX_CHARS - used
        value = raw[key][: max(remaining, 0)]
        result[key] = value
        used += len(value)
    return result


def render_template(template: str, variables: dict[str, str]) -> str:
    """填充层：替换 `{变量名}`，未声明的占位符保持原样。

    值由 re.sub 回调按字面插入，不会被当作新模板再次解析。
    """

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return variables.get(name, match.group(0))

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


def render_for_user(
    template: str, declared: list[str], user_id: int | None
) -> tuple[str, dict[str, str]]:
    """按用户背景渲染模板，返回（渲染结果, 实际注入的变量）。"""
    profile = user_profile_repo.get_by_user_id(user_id) if user_id is not None else None
    variables = build_variables(profile, declared)
    return render_template(template, variables), variables
