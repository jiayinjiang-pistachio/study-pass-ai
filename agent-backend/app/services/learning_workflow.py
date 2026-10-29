"""业务层：学习测评工作流编排（interrupt + checkpoint + workflow_runs 持久化）。

单图跨两次 HTTP 请求执行：
1. start：run_id 既是 workflow_runs.run_id，也是 LangGraph thread_id；图跑到
   `wait_user_answer` 的 interrupt() 暂停，题目从 get_state 快照读取；
2. submit：校验 checkpoint 仍在等待作答后，用 Command(resume=answers) 恢复同一线程，
   图继续评分并完成。

checkpoint 保存执行现场，state_json 只保存业务快照。MemorySaver 是进程内存储，
服务重启 / 多进程部署后旧 run_id 无法恢复，提交时返回 409 并要求重新发起。
"""

import logging
import time
import uuid

from fastapi import status
from langgraph.types import Command

from ..agent.workflows import learning_quiz
from ..agent.workflows.checkpoint import (
    build_thread_config,
    get_workflow_checkpointer,
)
from ..agent.workflows.learning_quiz import (
    WORKFLOW_TYPE_LEARNING_QUIZ,
    LearningWorkflowState,
    STATUS_COMPLETED,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_GRADING,
    STATUS_WAITING_ANSWER,
    normalize_answers,
)
from ..core.config import LLM_PROVIDER
from ..core.exceptions import BusinessException, SystemException
from ..db import session_repo, workflow_run_repo
from ..schemas.learning_workflow import LearningWorkflowSubmitIn

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX_CHARS = 2000

__all__ = [
    "STATUS_COMPLETED",
    "STATUS_CREATED",
    "STATUS_FAILED",
    "STATUS_GRADING",
    "STATUS_WAITING_ANSWER",
    "WORKFLOW_TYPE_LEARNING_QUIZ",
    "get_learning_workflow",
    "start_learning_workflow",
    "submit_learning_workflow",
]


def _delete_thread(run_id: str) -> None:
    """释放 checkpoint；删除失败只记日志，不影响已完成的结果。"""
    try:
        get_workflow_checkpointer().delete_thread(run_id)
    except Exception:
        logger.warning("释放工作流 checkpoint 失败 | run_id=%s", run_id, exc_info=True)


def _mark_failed(run_id: str, state: LearningWorkflowState, exc: Exception) -> None:
    """把失败状态与原因写回数据库；写库失败不能掩盖原始异常。"""
    failed_state = {**state, "status": STATUS_FAILED}
    try:
        workflow_run_repo.update(
            run_id,
            {
                "status": STATUS_FAILED,
                "state_json": failed_state,
                "error_message": str(exc)[:ERROR_MESSAGE_MAX_CHARS],
            },
        )
    except Exception:
        logger.warning("记录工作流失败状态出错 | run_id=%s", run_id, exc_info=True)


def _raise_workflow_error(
    run_id: str, state: LearningWorkflowState, exc: Exception, action: str
) -> None:
    """按错误类型转成 503（配置缺失）或 502（模型 / 解析失败）。"""
    _mark_failed(run_id, state, exc)
    _delete_thread(run_id)
    if isinstance(exc, RuntimeError):
        raise SystemException(
            "学习测评服务暂不可用",
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    logger.error("学习测评%s失败 | run_id=%s", action, run_id, exc_info=True)
    raise SystemException(
        f"学习测评{action}失败，请稍后重试",
        http_status=status.HTTP_502_BAD_GATEWAY,
        detail=f"run_id={run_id} error={exc}",
    ) from exc


def start_learning_workflow(user_id: int, payload) -> dict:
    """校验会话归属 → 执行图到 interrupt → 持久化题目并返回 waiting_answer。"""
    session = session_repo.get_for_user(payload.session_id, user_id)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={payload.session_id} user_id={user_id}",
        )

    run_id = str(uuid.uuid4())
    config = build_thread_config(run_id)
    state: LearningWorkflowState = {
        "run_id": run_id,
        "user_id": user_id,
        "session_id": payload.session_id,
        "request_text": payload.request_text,
        "provider": payload.provider or LLM_PROVIDER,
        "question_count": payload.question_count,
        "quiz": [],
        "answers": [],
        "evaluation": [],
        "score": 0,
        "weaknesses": [],
        "review": "",
        "status": STATUS_CREATED,
    }
    workflow_run_repo.insert(
        {
            "run_id": run_id,
            "user_id": user_id,
            "session_id": payload.session_id,
            "workflow_type": WORKFLOW_TYPE_LEARNING_QUIZ,
            "status": STATUS_CREATED,
            "state_json": state,
        }
    )

    graph = learning_quiz.build_learning_quiz_graph()
    try:
        graph.invoke(state, config)
        snapshot = graph.get_state(config)
    except Exception as exc:
        _raise_workflow_error(run_id, state, exc, "生成")

    # 图应停在等待作答节点；停在其他地方说明编排异常，尽早暴露
    if "wait_user_answer" not in snapshot.next:
        _raise_workflow_error(
            run_id, state, ValueError(f"图未停在等待作答：next={snapshot.next}"), "生成"
        )

    quiz = snapshot.values.get("quiz") or []
    saved_state = {**snapshot.values, "status": STATUS_WAITING_ANSWER}
    workflow_run_repo.update(
        run_id,
        {
            "status": STATUS_WAITING_ANSWER,
            "state_json": saved_state,
            "error_message": None,
        },
    )
    logger.info(
        "学习测评已出题 | run_id=%s user_id=%s question_count=%s",
        run_id,
        user_id,
        len(quiz),
    )
    return {"run_id": run_id, "status": STATUS_WAITING_ANSWER, "quiz": quiz}


def submit_learning_workflow(
    user_id: int, run_id: str, payload: LearningWorkflowSubmitIn
) -> dict:
    """校验 checkpoint → 校验作答 → 恢复图完成评分 → 持久化结果。"""
    row = workflow_run_repo.get_for_user(run_id, user_id)
    if row is None:
        raise BusinessException(
            "测评不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"run_id={run_id} user_id={user_id}",
        )
    if row["workflow_type"] != WORKFLOW_TYPE_LEARNING_QUIZ:
        raise BusinessException(
            "当前工作流不支持提交作答",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id} workflow_type={row['workflow_type']}",
        )
    if row["status"] == STATUS_COMPLETED:
        raise BusinessException(
            "该测评已提交，请勿重复提交",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id}",
        )
    if row["status"] != STATUS_WAITING_ANSWER:
        raise BusinessException(
            "当前测评状态不可提交",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id} status={row['status']}",
        )

    graph = learning_quiz.build_learning_quiz_graph()
    config = build_thread_config(run_id)
    try:
        snapshot = graph.get_state(config)
    except Exception:
        snapshot = None
        logger.warning("读取工作流 checkpoint 失败 | run_id=%s", run_id, exc_info=True)

    if snapshot is None or snapshot.next != ("wait_user_answer",) or not snapshot.values.get("quiz"):
        # MemorySaver 随进程消失：重启 / 多进程 / 记录被手工改动都会走到这里，
        # 不能直接 resume（LangGraph 会从 START 重新出题并再调用一次模型）。
        _mark_failed(run_id, dict(row["state_json"] or {}), RuntimeError("checkpoint 丢失"))
        _delete_thread(run_id)
        raise BusinessException(
            "测评流程已失效，请重新发起测评",
            http_status=status.HTTP_409_CONFLICT,
            detail=f"run_id={run_id}",
        )

    quiz = snapshot.values.get("quiz") or []
    answers = normalize_answers(quiz, payload.answers)

    grading_state: LearningWorkflowState = {
        **snapshot.values,
        "answers": answers,
        "status": STATUS_GRADING,
    }
    workflow_run_repo.update(
        run_id,
        {
            "status": STATUS_GRADING,
            "state_json": grading_state,
            "error_message": None,
        },
    )

    try:
        result = graph.invoke(Command(resume=answers), config)
    except Exception as exc:
        _raise_workflow_error(run_id, grading_state, exc, "评测")

    completed_state = {**grading_state, **result, "status": STATUS_COMPLETED}
    workflow_run_repo.update(
        run_id,
        {
            "status": STATUS_COMPLETED,
            "state_json": completed_state,
            "error_message": None,
            "completed_at": int(time.time()),
        },
    )
    _delete_thread(run_id)
    logger.info(
        "学习测评已完成 | run_id=%s user_id=%s score=%s",
        run_id,
        user_id,
        completed_state.get("score"),
    )
    return {
        "run_id": run_id,
        "status": STATUS_COMPLETED,
        "score": completed_state.get("score", 0),
        "evaluation": completed_state.get("evaluation", []),
        "weaknesses": completed_state.get("weaknesses", []),
        "review": completed_state.get("review", ""),
    }


def get_learning_workflow(user_id: int, run_id: str) -> dict:
    """按 run_id + user_id 查询运行详情；状态与完整 state 一并返回。"""
    row = workflow_run_repo.get_for_user(run_id, user_id)
    if row is None:
        raise BusinessException(
            "测评不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"run_id={run_id} user_id={user_id}",
        )
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "state": row["state_json"] or {},
    }
