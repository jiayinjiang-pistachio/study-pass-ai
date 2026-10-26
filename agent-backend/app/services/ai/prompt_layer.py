"""提示词层：Prompt 定义 + LangChain 链路组装。

职责边界：
- 只负责「系统提示词」与「prompt | model | parser」链路的拼装；
- 不查数据库、不做流式输出，历史消息由记忆层以消息列表注入。
"""

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

from .llm import get_chat_model

SESSION_MODE_STUDY = 0
SESSION_MODE_INTERVIEW = 1

SYSTEM_BASE = """你是「学面通 AI」的学习与面试助手，服务对象是正在准备求职的用户。
回答要求：
1. 使用中文，先给结论，再给必要的解释；表达准确、条理清晰。
2. 不确定的内容要明确说明，不要编造事实、数据或来源。
3. 展示代码时使用 Markdown 代码块并标注语言；结构化信息优先用表格或列表。
4. 内容要落到求职场景，兼顾知识讲解与面试实战。"""

SESSION_PROMPTS: dict[int, str] = {
    SESSION_MODE_STUDY: (
        "当前处于【学习模式】：侧重讲清概念、原理与推导过程，"
        "用循序渐进的例子帮助用户建立知识体系，必要时给出练习建议。"
    ),
    SESSION_MODE_INTERVIEW: (
        "当前处于【面试模式】：侧重考察点、答题思路与表达方式，"
        "可以追问细节，帮助用户把知识转化为面试中可复述的答案。"
    ),
}

# select_mode：0=默认，1=知识精讲，2=刷题，3=简历优化，4=模拟面试，5=面试复盘
SELECT_MODE_PROMPTS: dict[int, str] = {
    1: "本次任务是【知识精讲】：围绕主题分层拆解，覆盖核心概念、常见误区与高频追问。",
    2: "本次任务是【刷题测评】：先给出题目，再给出解析；涉及评分时说明得分点与改进方向。",
    3: "本次任务是【简历优化】：指出问题、给出改写示例，避免空泛评价，尽量用可量化表达。",
    4: "本次任务是【模拟面试】：以面试官口吻提问与追问，一次聚焦一个问题，并给出点评。",
    5: "本次任务是【面试复盘】：分析回答中的亮点与不足，给出可直接复用的改进表述。",
}


# 仅在本轮确实检索到知识片段时追加，避免干扰普通对话
RAG_SYSTEM_PROMPT = """本轮回答已附带用户知识库中检索到的参考资料。RAG 回答规则：
1. 优先依据参考资料作答，不要与其矛盾；资料未覆盖的部分直说，不要臆造。
2. 引用资料时用 [1] [2] 标注来源，编号与参考资料条目一致。
3. 只使用与问题相关的资料，不要复述无关内容。"""


def build_rag_system_prompt() -> str:
    """返回 RAG 回答规则；命中资料时由 build_chat_chain 追加到系统提示词。"""
    return RAG_SYSTEM_PROMPT


def build_system_prompt(session_mode: int, select_mode: int = 0) -> str:
    """按会话模式 + 子模式组装系统提示词；未知模式回退到默认规则。"""
    parts = [SYSTEM_BASE]
    session_prompt = SESSION_PROMPTS.get(session_mode)
    if session_prompt:
        parts.append(session_prompt)
    select_prompt = SELECT_MODE_PROMPTS.get(select_mode)
    if select_prompt:
        parts.append(select_prompt)
    return "\n\n".join(parts)


def build_chat_chain(
    session_mode: int,
    select_mode: int = 0,
    *,
    rag_enabled: bool = False,
) -> Runnable[dict, str]:
    """组装对话链路：系统提示词 + 历史消息 + 当前问题 → 模型 → 纯文本。

    入参固定为 {"history": list[BaseMessage], "input": str}，由记忆层构造；
    rag_enabled=True 时在系统提示词后追加 RAG 回答规则。
    """
    system_prompt = build_system_prompt(session_mode, select_mode)
    if rag_enabled:
        system_prompt = f"{system_prompt}\n\n{build_rag_system_prompt()}"

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder("history"),
            ("human", "{input}"),
        ]
    )
    return prompt | get_chat_model() | StrOutputParser()
