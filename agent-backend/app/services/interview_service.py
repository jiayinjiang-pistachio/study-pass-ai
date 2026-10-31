"""业务层：面试确认与面试详情查询。

确认是两阶段流程的第二阶段：
校验 run 归属 / 类型 / 状态 → 按用户编辑后的 background 重新渲染主考官提示词 →
原子抢占 `pending_confirmation → confirming`（保证同一 run_id 只确认一次）→
创建入口 ChatMessage 与 Interview → 回填消息 interview_id → run 置为 confirmed。
"""

import logging

from fastapi import status

from ..core.exceptions import BusinessException, SystemException
from ..db import interview_repo, message_repo, session_repo, workflow_run_repo
from . import interview_host_workflow

logger = logging.getLogger(__name__)

# 面试入口消息的子模式：4=模拟面试
INTERVIEW_MESSAGE_SELECT_MODE = 4
ERROR_MESSAGE_MAX_CHARS = 2000
DEFAULT_INTERVIEW_TEXT = "面试已准备好，请开始回答。"


def _get_interview(user_id: int, interview_id: int) -> dict:
    """按 interview_id + user_id 查询面试详情，防止越权读取。"""
    interview = interview_repo.get_for_user(interview_id, user_id)
    if interview is None:
        raise BusinessException(
            "面试记录不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"interview_id={interview_id} user_id={user_id}",
        )

    return {
        "id": interview["id"],
        "session_id": interview["session_id"],
        "message_id": interview["message_id"],
        "qa_object": interview["qa_object"],
        "interview_host_prompt": interview["interview_host_prompt"],
        "interview_duration": interview["interview_duration"],
        "status": interview["status"],
        "created_at": interview["created_at"],
        "updated_at": interview["updated_at"],
    }


def get_interview(user_id: int, interview_id: int) -> dict:
    """模块级入口：保持既有调用方式。"""
    return _get_interview(user_id, interview_id)


class InterviewService:
    """确认后创建正式面试，并提供面试详情查询。"""

    def get_interview(self, user_id: int, interview_id: int) -> dict:
        return _get_interview(user_id, interview_id)

    def confirm_interview(self, user_id: int, payload) -> dict:
        """第二阶段：校验待确认 run，落库入口消息与面试记录并返回 interview_id。"""
        row = workflow_run_repo.get_for_user(payload.run_id, user_id)
        if row is None:
            raise BusinessException(
                "面试准备不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"run_id={payload.run_id} user_id={user_id}",
            )
        if row["workflow_type"] != interview_host_workflow.WORKFLOW_TYPE_INTERVIEW_PREPARE:
            raise BusinessException(
                "当前工作流不是面试准备",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"run_id={payload.run_id} workflow_type={row['workflow_type']}",
            )
        if row["status"] == interview_host_workflow.STATUS_CONFIRMED:
            raise BusinessException(
                "该面试已确认，请勿重复确认",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"run_id={payload.run_id}",
            )
        if row["status"] != interview_host_workflow.STATUS_PENDING_CONFIRMATION:
            raise BusinessException(
                "当前面试准备状态不可确认",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"run_id={payload.run_id} status={row['status']}",
            )

        session = session_repo.get_for_user(row["session_id"], user_id)
        if session is None:
            raise BusinessException(
                "会话不存在",
                http_status=status.HTTP_404_NOT_FOUND,
                detail=f"session_id={row['session_id']} user_id={user_id}",
            )

        background = payload.background.model_dump()
        # 先渲染提示词：模板缺失等配置问题在消费 run 之前暴露，便于恢复后重试
        prompt = interview_host_workflow.build_interview_prompt(background, user_id)

        # 条件更新抢占状态：并发确认只有一个请求能把 pending 切到 confirming
        if not workflow_run_repo.claim_status(
            payload.run_id,
            user_id,
            interview_host_workflow.STATUS_PENDING_CONFIRMATION,
            interview_host_workflow.STATUS_CONFIRMING,
        ):
            raise BusinessException(
                "该面试已确认，请勿重复确认",
                http_status=status.HTTP_409_CONFLICT,
                detail=f"run_id={payload.run_id}",
            )

        state = dict(row["state_json"] or {})
        message: dict | None = None
        interview: dict | None = None
        try:
            message = message_repo.insert(
                {
                    "user_id": user_id,
                    "session_id": row["session_id"],
                    "select_mode": INTERVIEW_MESSAGE_SELECT_MODE,
                    "request_id": f"{payload.run_id}:interview",
                    "request_text": state.get("request_text") or "开始面试",
                    "response_text": background.get("opening_question")
                    or DEFAULT_INTERVIEW_TEXT,
                    "status": 1,
                }
            )
            interview = interview_repo.insert(
                {
                    "user_id": user_id,
                    "session_id": row["session_id"],
                    "message_id": message["id"],
                    "qa_object": [],
                    "interview_host_prompt": prompt,
                }
            )
            if not message_repo.set_interview_id(message["id"], interview["id"]):
                raise RuntimeError(f"入口消息不存在 message_id={message['id']}")
        except Exception as exc:
            logger.error(
                "确认面试落库失败 | run_id=%s user_id=%s", payload.run_id, user_id,
                exc_info=True,
            )
            # 补偿：面试记录未建成时删除入口消息，避免留下孤立消息
            if message is not None and interview is None:
                try:
                    message_repo.delete_by_id(message["id"])
                except Exception:
                    logger.warning(
                        "清理入口消息失败 | message_id=%s", message["id"], exc_info=True
                    )
            failed_state = {
                **state,
                "status": interview_host_workflow.STATUS_FAILED,
                "error_message": str(exc)[:ERROR_MESSAGE_MAX_CHARS],
            }
            try:
                workflow_run_repo.update(
                    payload.run_id,
                    {
                        "status": interview_host_workflow.STATUS_FAILED,
                        "state_json": failed_state,
                        "error_message": str(exc)[:ERROR_MESSAGE_MAX_CHARS],
                    },
                )
            except Exception:
                logger.warning(
                    "记录面试确认失败状态出错 | run_id=%s",
                    payload.run_id,
                    exc_info=True,
                )
            raise SystemException(
                "确认面试失败，请稍后重试",
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"run_id={payload.run_id}",
            ) from exc

        confirmed_state = {
            **state,
            "status": interview_host_workflow.STATUS_CONFIRMED,
            "confirmed_background": background,
            "interview_id": interview["id"],
            "message_id": message["id"],
        }
        workflow_run_repo.update(
            payload.run_id,
            {
                "status": interview_host_workflow.STATUS_CONFIRMED,
                "state_json": confirmed_state,
                "error_message": None,
            },
        )

        logger.info(
            "面试已确认 | run_id=%s user_id=%s session_id=%s interview_id=%s "
            "message_id=%s",
            payload.run_id,
            user_id,
            row["session_id"],
            interview["id"],
            message["id"],
        )
        return {
            "run_id": payload.run_id,
            "interview_id": interview["id"],
            "session_id": row["session_id"],
            "message_id": message["id"],
            "status": interview_host_workflow.STATUS_CONFIRMED,
        }
