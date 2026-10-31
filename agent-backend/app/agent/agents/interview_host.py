"""面试主考官智能体：只负责调用大模型提取面试准备变量。

一次调用同时完成两件事：从简历提取基础变量，并从用户本轮表述中解析
显式提出的要求（`user_stated`），供工作流按「最新输入优先」覆盖。
流程编排、会话 / 简历校验与实际提示词注入都在工作流层，本模块不感知。
"""

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ...core.retry import run_with_retry
from ...services.ai.json_utils import parse_json_object
from ...services.ai.llm import get_chat_model
from ...services.prompt_injection_service import sanitize_items, sanitize_text

NODE_NAME = "interview_host_extract"
OPENING_QUESTION_MAX_CHARS = 500
PROJECT_EXPERIENCE_MAX_CHARS = 1000
# 工作年限允许范围，与用户资料校验保持一致
YEARS_MIN = 0
YEARS_MAX = 60

# 输出契约静态写在 SystemMessage 中，避免提示词模板里的花括号被当成变量
EXTRACT_SYSTEM_PROMPT = """你是面试主考官的资料分析助手。请阅读候选人简历与候选人本次提出的要求。

输出严格为 JSON 对象，结构如下：
{
  "target_job": "目标岗位；简历未体现时填「未提供」",
  "target_level": "目标职级或经验层级（如 P6 / 高级 / 应届）；未体现时填「未提供」",
  "years_experience": 3,
  "target_skills": ["候选人已掌握的技能，优先提取具体技术栈"],
  "project_experience": "用一句话概括候选人最重要的项目经历；未体现时输出空字符串",
  "weak_topics": ["简历中缺失或明显薄弱的面试考察点"],
  "opening_question": "一句中文开场问题，结合简历项目经历，只问一个问题",
  "user_stated": {
    "target_job": "仅当候选人本次明确说明目标岗位时输出该键",
    "target_level": "仅当候选人本次明确说明目标职级时输出该键",
    "years_experience": 5,
    "target_skills": ["仅当候选人本次明确说明技能时输出该键"],
    "weak_topics": ["仅当候选人本次明确说明薄弱点时输出该键"]
  }
}

要求：
1. 除 user_stated 外的键只依据简历提取，不因本次要求改写；
2. user_stated 只提取候选人本次要求中明确表达的信息，不推断、不照抄简历；
   没有明确信息时输出空对象 {}；
3. years_experience 为整数（0 表示应届 / 无经验）；简历未体现时填 null，
   user_stated 中未提及则不要输出该键；
4. target_skills 最多 20 项，weak_topics 最多 10 项，每项不超过 50 字；
5. 技能与薄弱点去重，使用原文中的技术名词，不编造公司、项目与数据；
6. project_experience 只概括简历中已出现的一个代表性项目，不超过 200 字；
7. 不要输出 Markdown 代码块或任何解释文字。"""


class InterviewHostAgent:
    """面试主考官智能体；extract_variables 是唯一的对外能力。"""

    def extract_variables(
        self, resume_text: str, user_request: str = ""
    ) -> dict[str, Any]:
        """从简历提取基础变量，并解析用户本轮明确提出的要求。

        返回的 `user_stated` 只包含用户明确说明的字段，供工作流按
        「最新输入优先」覆盖简历 / 画像结果。
        """
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
                (
                    "human",
                    "候选人简历正文如下：\n\n{resume_text}\n\n"
                    "候选人本次提出的要求（可能为空）：\n{user_request}",
                ),
            ]
        )
        chain = prompt | get_chat_model() | StrOutputParser()
        raw = run_with_retry(
            lambda: chain.invoke(
                {
                    "resume_text": resume_text,
                    "user_request": user_request.strip() or "（未提供）",
                }
            ),
            node=NODE_NAME,
        )
        data = parse_json_object(raw)
        result = self._normalize(data)
        result["user_stated"] = self._normalize_stated(data.get("user_stated"))
        return result

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        """清洗模型输出：标量去掉模板符号，数组去空去重并限长。"""
        return {
            "target_job": sanitize_text(data.get("target_job")) or "未提供",
            "target_level": sanitize_text(data.get("target_level")) or "未提供",
            "years_experience": _normalize_years(data.get("years_experience")),
            "target_skills": sanitize_items(data.get("target_skills")),
            "project_experience": sanitize_text(
                data.get("project_experience"), PROJECT_EXPERIENCE_MAX_CHARS
            ),
            "weak_topics": sanitize_items(data.get("weak_topics"))[:10],
            "opening_question": sanitize_text(
                data.get("opening_question"), OPENING_QUESTION_MAX_CHARS
            ),
        }

    @staticmethod
    def _normalize_stated(data: object) -> dict[str, Any]:
        """清洗用户本轮表述：只保留出现且非空的字段，年限限定 0..60。"""
        if not isinstance(data, dict):
            return {}
        stated: dict[str, Any] = {}
        job = sanitize_text(data.get("target_job"))
        if job:
            stated["target_job"] = job
        level = sanitize_text(data.get("target_level"))
        if level:
            stated["target_level"] = level
        skills = sanitize_items(data.get("target_skills"))
        if skills:
            stated["target_skills"] = skills
        weak_topics = sanitize_items(data.get("weak_topics"))
        if weak_topics:
            stated["weak_topics"] = weak_topics[:10]

        years = _normalize_years(data.get("years_experience"))
        if years is not None:
            stated["years_experience"] = years
        return stated


def _normalize_years(value: object) -> int | None:
    """把年限清洗为 0..60 的整数；缺失或非法返回 None。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        years = int(value)
    except (TypeError, ValueError):
        return None
    return years if YEARS_MIN <= years <= YEARS_MAX else None
