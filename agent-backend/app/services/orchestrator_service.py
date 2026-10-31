"""业务层：流程总控。

按 agent_name 决定本轮走工作流还是通用聊天：

1. 未登记的 agent_name 直接 404（防止前端拼错被静默当成聊天）；
2. 关键词快筛命中 → 直接启动对应工作流，不调用向量模型；
3. 关键词未命中 → 用语义相似度兜底确认规则里的 intent_examples；
4. 仍未命中 → 返回聊天标记，由路由层复用流式聊天服务。

扩展方式：在 WORKFLOW_ROUTE_RULES 增加一条规则，并在 start_task 中补上
对应 workflow_type 的分支。
"""

import logging
from dataclasses import dataclass

from fastapi import status

from ..core.exceptions import BusinessException, SystemException
from ..schemas.chat import StreamChatIn
from ..schemas.learning_workflow import LearningWorkflowStartIn
from ..schemas.orchestrator import AgentTaskStartIn
from . import learning_workflow
from .a2a_handoff_service import A2AHandoffService
from .semantic_intent import SemanticIntentClassifier

logger = logging.getLogger(__name__)

QUIZ_AGENT_NAME = "quiz_generate_workflow"

# 已登记但暂未接入工作流的智能体：合法，直接走通用聊天（仍用统一聊天提示词）。
# 不在此集合且没有工作流规则的 agent_name 仍然 404，避免前端拼错被静默降级。
CHAT_AGENT_NAMES = frozenset(
    {
        "difficulty_learner",
        "note_archiver",
        "interview_host",
        "interview_evaluator",
    }
)


@dataclass(frozen=True)
class WorkflowRouteRule:
    """一个智能体到工作流的映射规则。

    关键词用双字词，避免「问题 / 话题 / 标题」里的单字误命中；
    intent_examples 只在关键词全部落空时才参与语义比较。
    """

    workflow_type: str
    required_keywords: tuple[str, ...]
    intent_examples: tuple[str, ...]
    intent_threshold: float = 0.6


WORKFLOW_ROUTE_RULES: dict[str, WorkflowRouteRule] = {
    QUIZ_AGENT_NAME: WorkflowRouteRule(
        workflow_type=learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ,
        required_keywords=(
            "出题",
            "刷题",
            "题目",
            "试题",
            "练习题",
            "练习",
            "测验",
            "测评",
            "小测",
            "面试题",
            "考考",
        ),
        intent_examples=(
            "帮我出几道练习题",
            "我想刷题巩固一下",
            "给我来一套小测验",
            "测测我对这个知识点的掌握程度",
            "来几道面试题",
        ),
        # 0.6 会把「你好，简单介绍一下你自己」这类问候判成出题（实测 0.61），
        # 真实出题改写句普遍 ≥ 0.68，故取 0.65 留出余量；短句「考考我…」走关键词。
        intent_threshold=0.65,
    ),
}


class OrchestratorService:
    """总控：判断走哪个流程，并把入参映射到对应服务。"""

    def route(
        self, agent_name: str, request_text: str
    ) -> WorkflowRouteRule | None:
        """返回命中的规则；None 表示走通用聊天。未知 agent_name 抛 404。"""
        rule = WORKFLOW_ROUTE_RULES.get(agent_name)
        if rule is None:
            if agent_name in CHAT_AGENT_NAMES:
                return None
            raise BusinessException(
                "智能体不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"agent_name={agent_name}",
            )

        text = request_text.strip()
        if any(keyword in text for keyword in rule.required_keywords):
            return rule

        if SemanticIntentClassifier.get().classify_intent(
            text, rule.intent_examples, rule.intent_threshold
        ):
            logger.info(
                "关键词未命中，语义意图命中工作流 | agent_name=%s", agent_name
            )
            return rule
        return None

    def start_task(self, user_id: int, payload: AgentTaskStartIn) -> dict:
        """启动工作流并返回结果；未命中规则时返回 {"route": "chat"}。"""
        rule = self.route(payload.agent_name, payload.request_text)
        if rule is None:
            return {"route": "chat"}

        if rule.workflow_type == learning_workflow.WORKFLOW_TYPE_LEARNING_QUIZ:
            # 显式构造：总控入参里的聊天字段不应进入工作流，避免契约被悄悄放大
            start = LearningWorkflowStartIn(
                session_id=payload.session_id,
                request_text=payload.request_text,
                question_count=payload.question_count,
                provider=payload.provider,
            )
            result = learning_workflow.start_learning_workflow(user_id, start)
            return {
                "route": "workflow",
                "agent_name": payload.agent_name,
                "workflow_type": rule.workflow_type,
                **result,
            }

        raise SystemException(
            "工作流配置错误，请联系管理员",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unsupported workflow_type={rule.workflow_type}",
        )

    def dispatch_handoff(
        self,
        envelope: dict | None,
        *,
        user_id: int,
        run_id: str,
        session_id: int | None,
        state: dict | None = None,
    ) -> dict:
        """统一 A2A 派发入口：只委托派发服务，不写具体下游业务。"""
        context = {
            "user_id": user_id,
            "run_id": run_id,
            "session_id": session_id,
        }
        # 上游已有完整快照时直接下传，下游无需再回源数据库
        if state is not None:
            context["state"] = state
        return A2AHandoffService().dispatch(envelope, context=context)

    def build_chat_payload(self, payload: AgentTaskStartIn) -> StreamChatIn:
        """把总控入参映射成聊天入参；question_count / provider 由聊天分支忽略。"""
        return StreamChatIn(
            request_text=payload.request_text,
            select_mode=payload.select_mode,
            request_id=payload.request_id,
            request_segments=payload.request_segments,
        )
