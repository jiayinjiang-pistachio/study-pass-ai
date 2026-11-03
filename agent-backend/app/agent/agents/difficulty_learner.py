"""难点讲解智能体（知识卡）：整理卡片原料 + 拼接绘图 / 播客提示词。

只调用大模型与纯函数，不感知接口、数据库、MinIO、出图与音频 API；
卡片原材料严格收敛为 title / topic / summary / points(≤3)，
绘图与播客提示词都由代码确定性拼接，避免模型自由发挥导致内容跑偏。
"""

import logging
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ...core.retry import run_with_retry
from ...db import user_profile_repo
from ...services import prompt_injection_service, prompt_template_service
from ...services.ai.json_utils import parse_json_object
from ...services.ai.llm import get_chat_model

logger = logging.getLogger(__name__)

AGENT_NAME = "difficulty_learner"
PROMPT_AGENT = "difficulty_learner"
PROMPT_SCENE = "study"
NODE_NAME = "difficulty_prepare_card"

MAX_POINTS = 3
TITLE_MAX_CHARS = 30
TOPIC_MAX_CHARS = 50
SUMMARY_MAX_CHARS = 120
POINT_TITLE_MAX_CHARS = 16
POINT_TIP_MAX_CHARS = 60

DEFAULT_CARD_ROLE = (
    "你是难点讲解助手。请把用户提出的知识点或薄弱点整理成一张可读性强的知识卡。"
)

# 静态输出契约：优先于模板中的长文讲解要求，避免模型输出大段文字
CARD_OUTPUT_RULES = """输出要求（优先于上方模板中的冲突规则）：
1. 只输出 JSON 对象，不要 Markdown 代码块、前后解释或多余字段；
2. 结构固定为：
{
  "title": "知识卡标题",
  "topic": "知识点主题",
  "summary": "一句话总结",
  "points": [
    {"title": "要点标题", "tip": "一句话说明"}
  ]
}
3. title ≤ 24 字，topic ≤ 30 字，summary ≤ 80 字；
4. points 为 1..3 项，每项 title ≤ 12 字、tip ≤ 40 字，按重要性排序；
5. 文案短、具体、适合信息图展示，避免术语堆砌与长段落；
6. 不编造用户问题中没有依据的事实；信息不足时给出最保守的通用解释。"""


def _clean(value: object, limit: int) -> str:
    """清洗模型输出文本；空白值返回空串。"""
    return prompt_injection_service.sanitize_text(value, limit)


def _fallback_title(request_text: str) -> str:
    """模型未给出标题时，用用户原话兜底（截断到卡片标题长度）。"""
    return _clean(request_text, TITLE_MAX_CHARS) or "知识点知识卡"


def normalize_card(data: dict[str, Any], request_text: str) -> dict[str, Any]:
    """把模型输出收敛成固定结构：去空、去重、限长、最多 3 个要点。"""
    title = _clean(data.get("title"), TITLE_MAX_CHARS) or _fallback_title(
        request_text
    )
    topic = _clean(data.get("topic"), TOPIC_MAX_CHARS) or title
    summary = _clean(data.get("summary"), SUMMARY_MAX_CHARS) or topic

    raw_points = data.get("points")
    points: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    if isinstance(raw_points, list):
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            point_title = _clean(item.get("title"), POINT_TITLE_MAX_CHARS)
            point_tip = _clean(item.get("tip"), POINT_TIP_MAX_CHARS)
            if not point_title or not point_tip:
                continue
            key = (point_title, point_tip)
            if key in seen:
                continue
            seen.add(key)
            points.append({"title": point_title, "tip": point_tip})
            if len(points) >= MAX_POINTS:
                break

    # 捣乱的模型可能一个要点都不给：用总结兜底，保证图片有可读内容
    if not points:
        points.append({"title": "核心要点", "tip": summary[:POINT_TIP_MAX_CHARS]})

    return {
        "title": title,
        "topic": topic,
        "summary": summary,
        "points": points,
    }


def build_image_prompt(card: dict[str, Any]) -> str:
    """把卡片原料拼成竖版信息图提示词。

    文案逐条列出并要求原样使用，减少模型改写、增字与画面杂乱；
    明确排除漫画分镜，保证输出是「一张知识卡」而不是故事图。
    """
    point_lines = "\n".join(
        f"- {point['title']}：{point['tip']}" for point in card["points"]
    )
    return (
        "一张竖版中文知识卡信息图，适合手机竖屏阅读。\n"
        f"主标题：{card['title']}\n"
        f"主题：{card['topic']}\n"
        f"核心总结：{card['summary']}\n"
        f"要点（共 {len(card['points'])} 条）：\n{point_lines}\n"
        "版式：顶部大标题，下方按顺序排列要点卡片，每张卡片只放一个小标题和"
        "一句话说明，底部用一行总结收尾；留白充足，层级清晰。\n"
        "风格：简洁现代扁平化信息图，浅色背景，主色不超过两种，字体清晰易读。\n"
        "图形：每个要点配一个简洁线性图标，图标数量少，不喧宾夺主。\n"
        "硬性约束：只使用上面给出的中文文案，不新增、不改写、不翻译；"
        "不要漫画分镜，不要多格故事场景，不要人物照片，不要复杂背景，"
        "不要大段文字，不要多余英文。"
    )


def build_podcast_topic(card: dict[str, Any]) -> str:
    """把同一份卡片原料拼成播客输入文本（确定性模板，不再调模型）。

    与绘图提示词同源：只用 title / topic / summary / points，不额外抽字段。
    播客接口 action=0 会对输入文本做总结生成，因此以卡片内容为主、
    只保留一句话的对话风格约束，避免把模板指令当成正文总结。
    """
    point_lines = "；".join(
        f"{point['title']}：{point['tip']}" for point in card["points"]
    )
    return (
        f"{card['title']}。{card['summary']}。"
        f"围绕主题「{card['topic']}」，核心要点包括：{point_lines}。"
        "请做成双人播客对话：一人提问、一人解答，口语化、有来有回，"
        "不要照读标题或罗列条目，时长控制在 3 分钟以内。"
    )


def _build_system_prompt(user_id: int) -> str:
    """公共 + 私有模板 + 用户画像；模板不可用时降级为内置角色。"""
    try:
        combined = prompt_template_service.get_combined_template(
            PROMPT_AGENT, PROMPT_SCENE, user_id
        )
        profile = user_profile_repo.get_by_user_id(user_id)
        injected = prompt_injection_service.build_variables(
            profile, combined["variables"]
        )
        rendered = prompt_injection_service.render_template(
            combined["final_template"], injected
        )
    except Exception:
        logger.warning(
            "知识卡提示词读取失败，使用内置提示词 | agent=%s scene=%s",
            PROMPT_AGENT,
            PROMPT_SCENE,
            exc_info=True,
        )
        rendered = DEFAULT_CARD_ROLE
    return f"{rendered}\n\n{CARD_OUTPUT_RULES}"


class DifficultyLearnerAgent:
    """难点讲解智能体；prepare_card 与 build_image_prompt 是仅有的能力。"""

    def prepare_card(
        self,
        user_id: int,
        request_text: str,
        qa_context: str = "",
    ) -> dict[str, Any]:
        """一次模型调用整理知识卡原料；解析失败交给统一重试。"""
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=_build_system_prompt(user_id)),
                (
                    "human",
                    "用户提出的知识点 / 薄弱点：\n{request_text}\n\n"
                    "可选的最近面试问答（可能为空，仅作背景）：\n{qa_context}",
                ),
            ]
        )
        chain = prompt | get_chat_model() | StrOutputParser()

        def _invoke() -> dict[str, Any]:
            raw = chain.invoke(
                {
                    "request_text": request_text.strip(),
                    "qa_context": qa_context.strip() or "（无）",
                }
            )
            return normalize_card(parse_json_object(raw or ""), request_text)

        return run_with_retry(_invoke, node=NODE_NAME)
