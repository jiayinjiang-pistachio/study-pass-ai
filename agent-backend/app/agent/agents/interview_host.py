"""面试主考官智能体：只负责调用大模型从简历提取面试准备变量。

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

# 输出契约静态写在 SystemMessage 中，避免提示词模板里的花括号被当成变量
EXTRACT_SYSTEM_PROMPT = """你是面试主考官的资料分析助手。请仅依据候选人简历，提取面试准备所需信息。

输出严格为 JSON 对象，结构如下：
{
  "target_job": "目标岗位；简历未体现时填「未提供」",
  "target_level": "目标职级或经验层级（如 P6 / 高级 / 应届）；未体现时填「未提供」",
  "target_skills": ["候选人已掌握的技能，优先提取具体技术栈"],
  "weak_topics": ["简历中缺失或明显薄弱的面试考察点"],
  "opening_question": "一句中文开场问题，结合简历项目经历，只问一个问题"
}

要求：
1. 只提取简历中出现或可合理推断的信息，不编造公司、项目与数据；
2. target_skills 最多 20 项，weak_topics 最多 10 项，每项不超过 50 字；
3. 技能与薄弱点去重，使用简历原文中的技术名词；
4. 不要输出 Markdown 代码块或任何解释文字。"""


class InterviewHostAgent:
    """面试主考官智能体；extract_variables 是唯一的对外能力。"""

    def extract_variables(self, resume_text: str) -> dict[str, Any]:
        """从简历正文提取 target_job / target_level / target_skills /
        weak_topics / opening_question。"""
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
                ("human", "候选人简历正文如下：\n\n{resume_text}"),
            ]
        )
        chain = prompt | get_chat_model() | StrOutputParser()
        raw = run_with_retry(
            lambda: chain.invoke({"resume_text": resume_text}), node=NODE_NAME
        )
        return self._normalize(parse_json_object(raw))

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        """清洗模型输出：标量去掉模板符号，数组去空去重并限长。"""
        return {
            "target_job": sanitize_text(data.get("target_job")) or "未提供",
            "target_level": sanitize_text(data.get("target_level")) or "未提供",
            "target_skills": sanitize_items(data.get("target_skills")),
            "weak_topics": sanitize_items(data.get("weak_topics"))[:10],
            "opening_question": sanitize_text(
                data.get("opening_question"), OPENING_QUESTION_MAX_CHARS
            ),
        }
