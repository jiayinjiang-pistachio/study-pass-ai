"""业务层：流程总控（规划 → 分发 → 统一 SSE 事件流）。

三层路由，延迟与成本可控：

1. Tier 0：前端快捷指令 `preferred_agent`，校验房间 / 前置数据后直接分发；
2. Tier 1：注册表关键词 + fastembed 语义示例快筛，命中即分发，不调用大模型；
3. Tier 2：仅当消息像任务但快筛未命中时，调用一次 FlowControllerAgent 规划；
   规划失败 / JSON 非法 / 置信度不足一律降级为普通聊天。

执行层按能力类型分流：聊天复用 chat_service；工作流复用既有
learning_workflow / interview_host_workflow；一次性任务复用
difficulty_card_workflow 与 note_archive_service。事件顺序统一为
meta → step(route) → agent(start) → step*（节点进度）→ delta / task → done
（失败为 step(failed) → error）。
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import BackgroundTasks, status
from starlette.concurrency import run_in_threadpool

from ..agent.agents.flow_controller import FlowControllerAgent
from ..agent.registry import (
    CHAT_AGENT,
    DIFFICULTY_AGENT,
    INTERVIEW_EVALUATOR_AGENT,
    INTERVIEW_HOST_AGENT,
    NOTE_AGENT,
    QUIZ_AGENT,
    REQUIRE_COMPLETED_INTERVIEW,
    REQUIRE_INTERVIEW_ROOM,
    REQUIRE_NOTE_SOURCE,
    REQUIRE_RESUME,
    ROOM_INTERVIEW,
    AgentCapability,
    capabilities_for_room,
    get_capability,
    is_room_allowed,
)
from ..core.exceptions import BusinessException, SystemException
from ..db import (
    interview_repo,
    message_repo,
    resource_repo,
    session_repo,
    workflow_run_repo,
)
from ..schemas.agent import AgentChatIn
from ..schemas.chat import StreamChatIn
from ..schemas.learning_workflow import (
    MAX_QUESTION_COUNT,
    LearningWorkflowStartIn,
)
from . import (
    chat_service,
    difficulty_card_workflow,
    interview_evaluation_service,
    interview_host_workflow,
    learning_workflow,
    note_archive_service,
    session_agent_state,
)
from .agent_progress import (
    STEP_DONE,
    STEP_FAILED,
    STEP_START,
    StepCallback,
    emit_step,
)
from .a2a_handoff_service import A2AHandoffService
from .note_service import NoteService
from .semantic_intent import SemanticIntentClassifier

logger = logging.getLogger(__name__)

STATUS_SCHEDULED = "scheduled"
RESUME_DOC_CATEGORY = "resume"
WORKFLOW_TYPE_LEARNING_QUIZ = "learning_quiz"
STATUS_COMPLETED = "completed"

EVENT_META = "meta"
EVENT_AGENT = "agent"
EVENT_STEP = "step"
EVENT_TASK = "task"
EVENT_DONE = "done"
EVENT_ERROR = "error"

# 进度节点：聊天分支在总控层维护；任务分支由能力自身上报
ROUTE_AGENT = "flow_controller"
ROUTE_NODE = "route"
ROUTE_TITLE = "理解请求"
REPLY_NODE = "generate_reply"
REPLY_TITLE = "生成回答"
GENERIC_ERROR = "任务执行失败，请稍后重试"

STATUS_MESSAGE_DONE = 1
# 快筛未命中但消息达到该长度时，才值得调用一次规划模型
TASK_MIN_CHARS = 10
# 普通聊天 / 无产物任务的占位 message_id：前端据此知道本轮没有可对账的消息
NO_MESSAGE_ID = 0
# 落库的时间轴状态用前端展示态；SSE 仍用 start / done / failed
ACTIVITY_RUNNING = "running"

# 可在一轮内先后执行的「追加型」能力：只做一次性产物，不打断用户作答。
# 其它能力（出题等待作答、面试主考官需确认、复盘）命中后仍只取首个。
COMPOSABLE_AGENTS = frozenset({DIFFICULTY_AGENT, NOTE_AGENT})
# 归档必须是明确动作；避免「讲解我的笔记」这类句子被误判成归档
NOTE_ARCHIVE_ACTIONS = ("归档", "整理成笔记", "总结成笔记", "存成笔记", "记录下来")


def _run_a2a_handoff(envelope: dict, context: dict) -> None:
    """后台执行一次完整派发；异常只记日志，不影响已返回的提交结果。"""
    try:
        A2AHandoffService().dispatch(envelope, context=context)
    except Exception:
        logger.error(
            "后台 A2A 接力执行失败 | from=%s", envelope.get("from_agent"), exc_info=True
        )


@dataclass(frozen=True)
class PlannedAgent:
    """计划中的一个执行单元；slots 供出题等能力使用。"""

    name: str
    slots: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentPlan:
    """一次调度的最终决策；chat 走普通聊天，其余进入 task 事件流。"""

    session: dict
    trace_id: str
    tier: int
    intent: str
    agents: tuple[PlannedAgent, ...]
    reason: str = ""
    confidence: float = 1.0

    @property
    def is_chat(self) -> bool:
        return bool(self.agents) and self.agents[0].name == CHAT_AGENT


def _get_owned_session(user_id: int, session_id: int) -> dict:
    """取当前用户的会话；不存在或不属于该用户统一 404。"""
    session = session_repo.get_for_user(session_id, user_id)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={session_id} user_id={user_id}",
        )
    return session


def _recent_history(session_id: int, limit: int = 4) -> list[dict]:
    """最近几轮已完成对话，供规划器区分「继续」与新任务。"""
    rows = message_repo.list_recent_completed(session_id, limit)
    history: list[dict] = []
    for row in rows:
        history.append({"role": "user", "content": row.get("request_text") or ""})
        history.append(
            {"role": "assistant", "content": row.get("response_text") or ""}
        )
    return history[-limit:]


class OrchestratorService:
    """总控：决定本轮能力，并按统一事件协议执行。"""

    def plan(self, user_id: int, payload: AgentChatIn) -> AgentPlan:
        """三层路由；会话校验在进入流之前完成，404 仍返回标准 JSON 信封。"""
        session = _get_owned_session(user_id, payload.session_id)
        session_mode = session["session_mode"]
        text = payload.request_text
        trace_id = uuid.uuid4().hex

        capability = self._explicit_capability(payload.preferred_agent, user_id, session)
        if capability is not None:
            logger.info(
                "Tier0 显式指令命中 | user_id=%s session_id=%s agent=%s",
                user_id,
                session["id"],
                capability.name,
            )
            return self._fast_plan(session, trace_id, (capability,), text, tier=0)

        capabilities = self._fast_match(text, session_mode, user_id, session)
        if capabilities:
            logger.info(
                "Tier1 快筛命中 | user_id=%s session_id=%s agent=%s",
                user_id,
                session["id"],
                ",".join(capability.name for capability in capabilities),
            )
            return self._fast_plan(session, trace_id, capabilities, text)

        if len(text.strip()) >= TASK_MIN_CHARS:
            planned = self._plan_with_model(user_id, session, text)
            if planned is not None:
                logger.info(
                    "Tier2 规划命中 | user_id=%s session_id=%s intent=%s agents=%s "
                    "confidence=%s",
                    user_id,
                    session["id"],
                    planned["intent"],
                    ",".join(item["name"] for item in planned["agents"]),
                    planned["confidence"],
                )
                return AgentPlan(
                    session=session,
                    trace_id=trace_id,
                    tier=2,
                    intent=planned["intent"],
                    agents=tuple(
                        PlannedAgent(name=item["name"], slots=item["slots"])
                        for item in planned["agents"]
                    ),
                    reason=planned["reason"] or "由总控规划器判断",
                    confidence=planned["confidence"],
                )

        return AgentPlan(
            session=session,
            trace_id=trace_id,
            tier=3,
            intent="chat",
            agents=(PlannedAgent(name=CHAT_AGENT),),
            reason="未命中任务意图，走普通聊天",
        )

    # ---------- 路由内部 ----------

    def _explicit_capability(
        self, preferred: str | None, user_id: int, session: dict
    ) -> AgentCapability | None:
        """快捷指令只是提示：未知 / 不适用 / 前置不足时静默忽略。"""
        capability = get_capability(preferred)
        if capability is None or capability.kind == "chat":
            return None
        if not is_room_allowed(capability, session["session_mode"]):
            return None
        if not self._requires_met(capability, user_id, session):
            return None
        return capability

    def _fast_match(
        self, text: str, session_mode: int, user_id: int, session: dict
    ) -> tuple[AgentCapability, ...] | None:
        """关键词优先，全部落空后再逐能力做语义比较。

        关键词命中多个能力时：若都属于「追加型」且归档是明确动作，则一并调度
        （如「归档这次面试，并讲解薄弱点」→ 笔记归档 + 难点学习），按原话提及
        的先后执行；其余情况保持只取第一个命中，避免出题 / 面试等被打断。
        """
        candidates = capabilities_for_room(session_mode)
        keyword_hits: list[tuple[int, AgentCapability]] = []
        for capability in candidates:
            if not self._requires_met(capability, user_id, session):
                continue
            if not capability.triggers:
                continue
            positions = [
                text.find(keyword)
                for keyword in capability.triggers
                if keyword in text
            ]
            if positions:
                keyword_hits.append((min(positions), capability))

        if keyword_hits:
            keyword_hits.sort(key=lambda item: item[0])
            hits = tuple(capability for _, capability in keyword_hits)
            if self._is_composable(hits, text):
                return hits
            return (hits[0],)

        for capability in candidates:
            if not self._requires_met(capability, user_id, session):
                continue
            if capability.examples and SemanticIntentClassifier.get().classify_intent(
                text, capability.examples, capability.threshold
            ):
                return (capability,)
        return None

    @staticmethod
    def _is_composable(hits: tuple[AgentCapability, ...], text: str) -> bool:
        """多个关键词命中是否可组合执行：仅限追加型 + 明确归档动作。"""
        if len(hits) < 2 or not all(hit.name in COMPOSABLE_AGENTS for hit in hits):
            return False
        if any(hit.name == NOTE_AGENT for hit in hits):
            return any(action in text for action in NOTE_ARCHIVE_ACTIONS)
        return True

    def _requires_met(
        self, capability: AgentCapability, user_id: int, session: dict
    ) -> bool:
        """前置数据校验；未满足的能力不参与路由，避免硬调后 404。"""
        if (
            REQUIRE_INTERVIEW_ROOM in capability.requires
            and session["session_mode"] != ROOM_INTERVIEW
        ):
            return False
        if REQUIRE_RESUME in capability.requires and (
            resource_repo.get_latest_by_category(user_id, RESUME_DOC_CATEGORY)
            is None
        ):
            return False
        if REQUIRE_COMPLETED_INTERVIEW in capability.requires and (
            interview_repo.get_latest_completed_for_session(
                user_id, session["id"]
            )
            is None
        ):
            return False
        if REQUIRE_NOTE_SOURCE in capability.requires and (
            self._completed_run(user_id, session["id"]) is None
            and interview_repo.get_latest_completed_for_session(
                user_id, session["id"]
            )
            is None
        ):
            return False
        return True

    @staticmethod
    def _completed_run(user_id: int, session_id: int) -> dict | None:
        """本会话最近一次已完成的学习测评；笔记归档的优先来源。"""
        return workflow_run_repo.get_latest_for_session(
            user_id,
            session_id,
            workflow_type=WORKFLOW_TYPE_LEARNING_QUIZ,
            status=STATUS_COMPLETED,
        )

    def _plan_with_model(
        self, user_id: int, session: dict, text: str
    ) -> dict[str, Any] | None:
        """快筛未命中时调用一次规划器，并再次按注册表 / 前置数据过滤。"""
        candidates = capabilities_for_room(session["session_mode"])
        result = FlowControllerAgent().plan(
            user_id=user_id,
            session_mode=session["session_mode"],
            request_text=text,
            capabilities=candidates,
            history=_recent_history(session["id"]),
            state=session_agent_state.get_state(user_id, session["id"]),
        )
        if not result:
            return None

        allowed = {capability.name: capability for capability in candidates}
        agents: list[dict[str, Any]] = []
        for item in result["agents"]:
            capability = allowed.get(item["name"])
            if capability is None:
                continue
            if not self._requires_met(capability, user_id, session):
                continue
            agents.append(
                {"name": capability.name, "slots": item.get("slots") or {}}
            )
        if not agents:
            return None
        return {**result, "agents": agents}

    @staticmethod
    def _fast_plan(
        session: dict,
        trace_id: str,
        capabilities: tuple[AgentCapability, ...],
        text: str,
        *,
        tier: int = 1,
    ) -> AgentPlan:
        """快筛 / 显式指令命中的计划；出题题量从原话提取，多能力按顺序执行。"""
        agents: list[PlannedAgent] = []
        for capability in capabilities:
            slots: dict[str, Any] = {}
            if capability.name == QUIZ_AGENT:
                count = learning_workflow.infer_question_count(text)
                if count is not None:
                    slots["question_count"] = count
            agents.append(PlannedAgent(name=capability.name, slots=slots))
        return AgentPlan(
            session=session,
            trace_id=trace_id,
            tier=tier,
            intent="+".join(capability.returns for capability in capabilities),
            agents=tuple(agents),
            reason="、".join(
                f"{capability.title}触发" for capability in capabilities
            ),
        )

    # ---------- 事件流 ----------

    async def stream(
        self, plan: AgentPlan, user_id: int, payload: AgentChatIn
    ) -> AsyncIterator[str]:
        """按计划输出统一 SSE；路由层不再区分 JSON / SSE。"""
        if plan.is_chat:
            async for event in self._stream_chat(plan, user_id, payload):
                yield event
            return
        async for event in self._stream_tasks(plan, user_id, payload):
            yield event

    async def _stream_chat(
        self, plan: AgentPlan, user_id: int, payload: AgentChatIn
    ) -> AsyncIterator[str]:
        """聊天分支：复用 chat_service，meta 由总控补充 trace_id。"""
        state = await run_in_threadpool(
            chat_service.prepare_stream,
            user_id,
            plan.session["id"],
            self._chat_payload(payload),
            trace_id=plan.trace_id,
        )
        yield chat_service.sse_event(
            EVENT_META,
            {
                "session_id": plan.session["id"],
                "message_id": state.message["id"],
                "request_id": state.message["request_id"],
                "trace_id": plan.trace_id,
            },
        )
        activity: list[dict[str, Any]] = []
        yield self._record_step(
            activity,
            plan.trace_id,
            ROUTE_AGENT,
            ROUTE_NODE,
            ROUTE_TITLE,
            STEP_DONE,
            detail=plan.reason,
        )
        yield self._agent_event(plan, plan.agents[0].name, "start")
        yield self._record_step(
            activity,
            plan.trace_id,
            plan.agents[0].name,
            REPLY_NODE,
            REPLY_TITLE,
            STEP_START,
        )

        # 内层 stream_reply 已把成功 / 失败收尾成 done / error 事件，
        # 据此补上本轮节点状态，避免前端时间轴停留在 running。
        try:
            async for event in chat_service.stream_reply(state, emit_meta=False):
                if event.startswith("event: done"):
                    yield self._record_step(
                        activity,
                        plan.trace_id,
                        plan.agents[0].name,
                        REPLY_NODE,
                        REPLY_TITLE,
                        STEP_DONE,
                    )
                elif event.startswith("event: error"):
                    yield self._record_step(
                        activity,
                        plan.trace_id,
                        plan.agents[0].name,
                        REPLY_NODE,
                        REPLY_TITLE,
                        STEP_FAILED,
                        error=self._sse_error_message(event),
                    )
                yield event
        finally:
            # 客户端中途断开也会走到这里，保留已执行节点的快照
            self._persist_activity(state.message["id"], activity)

    async def _stream_tasks(
        self, plan: AgentPlan, user_id: int, payload: AgentChatIn
    ) -> AsyncIterator[str]:
        """任务分支：同步执行子能力，依次下发 agent / step / task / done。

        任务自身的会话消息由子工作流写入（Phase 1 保持现状），
        meta 的 message_id 先置 0，前端凭 task.payload 对账。
        """
        yield chat_service.sse_event(
            EVENT_META,
            {
                "session_id": plan.session["id"],
                "message_id": NO_MESSAGE_ID,
                "request_id": payload.request_id or "",
                "trace_id": plan.trace_id,
            },
        )
        # 路由规划在建立流之前完成，这里补一条「理解请求」的完成节点
        yield self._step_event(
            plan.trace_id, ROUTE_AGENT, ROUTE_NODE, ROUTE_TITLE, STEP_DONE, detail=plan.reason
        )

        last_message_id = NO_MESSAGE_ID
        for agent in plan.agents:
            yield self._agent_event(plan, agent.name, "start")
            outcome: dict[str, Any] = {}
            try:
                async for event in self._run_agent_with_steps(
                    plan, agent, user_id, payload, outcome
                ):
                    yield event
            except Exception as exc:
                logger.error(
                    "子 Agent 执行失败 | trace_id=%s agent=%s",
                    plan.trace_id,
                    agent.name,
                    exc_info=True,
                )
                yield self._error_event(exc)
                return

            kind, result = outcome["kind"], outcome["value"]
            message_id = result.get("message_id")
            if isinstance(message_id, int) and message_id > 0:
                last_message_id = message_id
                # 先落库再下发 task：前端收到 task 立即刷新时即可拿到完整时间轴
                self._persist_activity(message_id, outcome.get("activity") or [])
            yield chat_service.sse_event(
                EVENT_TASK,
                {
                    "trace_id": plan.trace_id,
                    "kind": kind,
                    "run_id": result.get("run_id"),
                    "payload": result,
                },
            )
            yield self._agent_event(plan, agent.name, "done")

        yield chat_service.sse_event(
            EVENT_DONE,
            {
                "message_id": last_message_id,
                "status": STATUS_MESSAGE_DONE,
                "sources": [],
                "trace_id": plan.trace_id,
            },
        )

    async def _run_agent_with_steps(
        self,
        plan: AgentPlan,
        agent: PlannedAgent,
        user_id: int,
        payload: AgentChatIn,
        out: dict[str, Any],
    ) -> AsyncIterator[str]:
        """在线程池执行子能力，并把工作线程的节点进度实时转成 SSE。

        生成器跑在事件循环、能力跑在 worker 线程：用 asyncio.Queue +
        call_soon_threadsafe 桥接，保证 step 事件总是先于 result / error
        到达；失败时把仍停在 start 的节点统一标记为 failed。
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def put(kind: str, data: Any) -> None:
            # 客户端断开后事件循环可能已关闭，进度无需再上报
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, data))
            except RuntimeError:
                pass

        def emit(
            node: str,
            title: str,
            status: str,
            detail: str | None = None,
            error: str | None = None,
        ) -> None:
            put("step", (node, title, status, detail, error))

        def worker() -> None:
            try:
                result = self._execute_agent(
                    plan, agent, user_id, payload, on_step=emit
                )
            except Exception as exc:
                put("error", exc)
                return
            put("result", result)

        loop.run_in_executor(None, worker)
        # 只在本生成器线程维护 active / activity，避免与 worker 并发读写
        active: list[tuple[str, str]] = []
        activity: list[dict[str, Any]] = []
        while True:
            kind, data = await queue.get()
            if kind == "result":
                out["kind"], out["value"] = data
                out["activity"] = activity
                return
            if kind == "error":
                exc = data
                message = getattr(exc, "message", None) or GENERIC_ERROR
                for node, title in active:
                    yield self._record_step(
                        activity,
                        plan.trace_id,
                        agent.name,
                        node,
                        title,
                        STEP_FAILED,
                        error=str(message),
                    )
                raise exc
            node, title, status, detail, error = data
            if status == STEP_START:
                active.append((node, title))
            elif status in (STEP_DONE, STEP_FAILED):
                active = [item for item in active if item[0] != node]
            yield self._record_step(
                activity, plan.trace_id, agent.name, node, title, status, detail, error
            )

    def _execute_agent(
        self,
        plan: AgentPlan,
        agent: PlannedAgent,
        user_id: int,
        payload: AgentChatIn,
        *,
        on_step: StepCallback | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """按能力名执行；返回 (task.kind, payload)。"""
        session_id = plan.session["id"]
        text = payload.request_text

        if agent.name == QUIZ_AGENT:
            start = LearningWorkflowStartIn(
                session_id=session_id,
                request_text=text,
                question_count=self._question_count(agent, payload),
                provider=payload.provider,
            )
            result = learning_workflow.start_learning_workflow(
                user_id, start, on_step=on_step
            )
            message = message_repo.get_by_request_id(
                f"{result['run_id']}:quiz", user_id
            )
            result["message_id"] = message["id"] if message else NO_MESSAGE_ID
            session_agent_state.record_dispatch(
                user_id,
                session_id,
                agent=agent.name,
                intent=plan.intent,
                run_id=result["run_id"],
                message_id=result["message_id"],
            )
            return "quiz", result

        if agent.name == DIFFICULTY_AGENT:
            result = difficulty_card_workflow.start_difficulty_card(
                user_id, session_id, text, on_step=on_step
            )
            message = message_repo.get_by_request_id(
                f"{result['run_id']}:card", user_id
            )
            result["message_id"] = message["id"] if message else NO_MESSAGE_ID
            session_agent_state.record_dispatch(
                user_id,
                session_id,
                agent=agent.name,
                intent=plan.intent,
                run_id=result["run_id"],
                message_id=result["message_id"],
            )
            return "knowledge_card", result

        if agent.name == INTERVIEW_HOST_AGENT:
            result = interview_host_workflow.start_interview_prepare(
                user_id, session_id, text, on_step=on_step
            )
            result["message_id"] = NO_MESSAGE_ID
            session_agent_state.record_dispatch(
                user_id,
                session_id,
                agent=agent.name,
                intent=plan.intent,
                run_id=result["run_id"],
            )
            return "interview_prepare", result

        if agent.name == INTERVIEW_EVALUATOR_AGENT:
            result = interview_evaluation_service.InterviewEvaluationService().evaluate_session(
                user_id, session_id, on_step=on_step
            )
            session_agent_state.record_dispatch(
                user_id,
                session_id,
                agent=agent.name,
                intent=plan.intent,
                interview_id=result["interview_id"],
                message_id=result["message_id"],
            )
            return "interview_evaluation", result

        if agent.name == NOTE_AGENT:
            emit_step(on_step, "select_source", "选择归档来源", STEP_START)
            # 优先用已完成的测评；没有测评时退到最近一次已结束的面试
            run_row = self._completed_run(user_id, session_id)
            interview = None
            if run_row is None:
                interview = interview_repo.get_latest_completed_for_session(
                    user_id, session_id
                )
            if run_row is None and interview is None:
                raise BusinessException(
                    "当前会话还没有已完成的测评或面试，暂时无法生成笔记",
                    http_status=status.HTTP_409_CONFLICT,
                    detail=f"session_id={session_id} user_id={user_id}",
                )
            emit_step(
                on_step,
                "select_source",
                "选择归档来源",
                STEP_DONE,
                detail="学习测评" if run_row is not None else "面试复盘",
            )

            emit_step(on_step, "generate_note", "生成笔记", STEP_START)
            if run_row is not None:
                archive = (
                    note_archive_service.NoteArchiveService().archive_from_run(
                        user_id, run_row["run_id"]
                    )
                )
                saved = NoteService().save_learning_quiz_note(
                    user_id, session_id, run_row["run_id"], archive
                )
                run_id = run_row["run_id"]
            else:
                archive = (
                    note_archive_service.NoteArchiveService().archive_from_interview(
                        user_id, interview["id"]
                    )
                )
                saved = NoteService().save_interview_note(
                    user_id, session_id, interview["id"], archive
                )
                run_id = f"interview:{interview['id']}"
            emit_step(
                on_step, "generate_note", "生成笔记", STEP_DONE, detail=archive["title"]
            )

            emit_step(on_step, "save_note", "保存笔记", STEP_START)
            message_id = self._save_note_message(
                user_id, session_id, text, saved["note_id"], archive["title"]
            )
            emit_step(on_step, "save_note", "保存笔记", STEP_DONE)
            result = {
                "run_id": run_id,
                "note_id": saved["note_id"],
                "status": saved["note_status"],
                "title": archive["title"],
                "message_id": message_id,
            }
            session_agent_state.record_dispatch(
                user_id,
                session_id,
                agent=agent.name,
                intent=plan.intent,
                completed_run_id=run_row["run_id"] if run_row is not None else None,
                interview_id=interview["id"] if interview is not None else None,
                message_id=message_id,
            )
            return "note", result

        raise SystemException(
            "智能体配置错误，请联系管理员",
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unsupported agent={agent.name}",
        )

    @staticmethod
    def _question_count(agent: PlannedAgent, payload: AgentChatIn) -> int | None:
        """规划槽位优先；非法值丢弃，交给工作流按原话提取。"""
        value = agent.slots.get("question_count")
        if isinstance(value, int) and 1 <= value <= MAX_QUESTION_COUNT:
            return value
        return payload.question_count

    @staticmethod
    def _save_note_message(
        user_id: int,
        session_id: int,
        request_text: str,
        note_id: int,
        title: str,
    ) -> int:
        """把笔记产物写入会话，历史消息刷新后仍能看到入口；同笔记幂等。"""
        request_id = f"note:{note_id}"
        existing = message_repo.get_by_request_id(request_id, user_id)
        if existing is not None:
            return existing["id"]
        message = message_repo.insert(
            {
                "user_id": user_id,
                "session_id": session_id,
                "select_mode": 0,
                "request_id": request_id,
                "request_text": request_text,
                "response_text": f"已生成笔记「{title}」，可在笔记本中查看。",
                "status": STATUS_MESSAGE_DONE,
            }
        )
        return message["id"]

    @staticmethod
    def _agent_event(plan: AgentPlan, to_agent: str, phase: str) -> str:
        """调度可观测性事件；前端可据此展示「正在调用 xx 智能体」。"""
        return chat_service.sse_event(
            EVENT_AGENT,
            {
                "trace_id": plan.trace_id,
                "from": "flow_controller",
                "to": to_agent,
                "phase": phase,
                "reason": plan.reason,
            },
        )

    @staticmethod
    def _step_data(
        trace_id: str,
        agent: str,
        node: str,
        title: str,
        status: str,
        detail: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """step 事件载荷；同时用作落库快照（状态统一为前端展示态）。"""
        return {
            "trace_id": trace_id,
            "agent": agent,
            "node": node,
            "title": title,
            "status": ACTIVITY_RUNNING if status == STEP_START else status,
            "detail": detail,
            "error": error,
        }

    @classmethod
    def _step_event(
        cls,
        trace_id: str,
        agent: str,
        node: str,
        title: str,
        status: str,
        detail: str | None = None,
        error: str | None = None,
    ) -> str:
        """节点级进度事件；前端按 (agent, node) 更新时间轴。"""
        return chat_service.sse_event(
            EVENT_STEP,
            cls._step_data(trace_id, agent, node, title, status, detail, error),
        )

    @classmethod
    def _record_step(
        cls,
        activity: list[dict[str, Any]],
        trace_id: str,
        agent: str,
        node: str,
        title: str,
        status: str,
        detail: str | None = None,
        error: str | None = None,
    ) -> str:
        """下发 step 并把展示态快照记入本轮时间轴。

        同一 (agent, node) 的 start / done 合并为一条，与前端 upsert 规则一致。
        """
        data = cls._step_data(trace_id, agent, node, title, status, detail, error)
        # 落库载荷去掉仅 SSE 需要的 trace_id，避免消息表存冗余调度信息
        snapshot = {key: value for key, value in data.items() if key != "trace_id"}
        existing = next(
            (
                item
                for item in activity
                if item["agent"] == agent and item["node"] == node
            ),
            None,
        )
        if existing is None:
            activity.append(snapshot)
        else:
            existing.update(snapshot)
        return chat_service.sse_event(EVENT_STEP, data)

    @staticmethod
    def _persist_activity(message_id: int, activity: list[dict[str, Any]]) -> None:
        """时间轴落库失败只记日志，不影响已完成的业务结果与事件流。"""
        if message_id <= NO_MESSAGE_ID or not activity:
            return
        try:
            message_repo.update_activity(message_id, activity)
        except Exception:
            logger.warning(
                "执行时间轴落库失败 | message_id=%s", message_id, exc_info=True
            )

    @staticmethod
    def _sse_error_message(event: str) -> str:
        """从内层 error 事件里取出面向用户的文案，供失败节点展示。"""
        for line in event.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                payload = json.loads(line[len("data: ") :])
            except ValueError:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                return payload["message"]
        return "AI 服务暂时不可用，请稍后重试"

    @staticmethod
    def _error_event(exc: Exception) -> str:
        """把子能力异常转成 SSE error；业务异常保留可读文案。"""
        code = getattr(exc, "http_status", None) or status.HTTP_502_BAD_GATEWAY
        message = getattr(exc, "message", None) or "任务执行失败，请稍后重试"
        return chat_service.sse_event(
            EVENT_ERROR, {"code": int(code), "message": str(message)}
        )

    @staticmethod
    def _chat_payload(payload: AgentChatIn) -> StreamChatIn:
        """总控入参 → 聊天入参；题量 / provider 由聊天分支忽略。"""
        return StreamChatIn(
            request_text=payload.request_text,
            select_mode=payload.select_mode,
            request_id=payload.request_id,
            request_segments=payload.request_segments,
        )

    # ---------- A2A ----------

    def dispatch_a2a_handoff(
        self,
        envelope: dict | None,
        *,
        user_id: int,
        run_id: str,
        session_id: int | None,
        state: dict | None = None,
        background_tasks: BackgroundTasks | None = None,
    ) -> dict:
        """统一 A2A 派发入口：只委托派发服务，不写具体下游业务。"""
        context = {
            "user_id": user_id,
            "run_id": run_id,
            "session_id": session_id,
        }
        if state is not None:
            context["state"] = state

        if (
            background_tasks is not None
            and isinstance(envelope, dict)
            and envelope.get("next_agent")
        ):
            # 后台执行前补齐 trace_id，保证调度回执与真正的派发链路可对账
            envelope = dict(envelope)
            trace_id = envelope.get("trace_id") or uuid.uuid4().hex
            envelope["trace_id"] = trace_id
            background_tasks.add_task(_run_a2a_handoff, envelope, context)
            return {
                "status": STATUS_SCHEDULED,
                "from_agent": envelope.get("from_agent"),
                "next_agent": envelope.get("next_agent"),
                "trace_id": trace_id,
                "hops": int(envelope.get("hops") or 0),
                "result_ref": None,
                "result": None,
                "reason": "A2A 接力已转入后台执行",
                "idempotent": False,
            }

        return A2AHandoffService().dispatch(envelope, context=context)
