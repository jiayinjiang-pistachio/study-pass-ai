"""路由层：面试确认与面试详情接口（均按当前用户隔离）。"""

from fastapi import APIRouter, Depends

from ..schemas.interview import InterviewConfirmIn, InterviewConfirmOut, InterviewOut
from ..schemas.response import ResponseModel, ok
from ..services.interview_service import InterviewService
from .deps import get_current_user

router = APIRouter(
    prefix="/api/interviews",
    tags=["interviews"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/confirm",
    response_model=ResponseModel[InterviewConfirmOut],
    summary="确认面试背景并创建面试",
)
def confirm_interview(
    payload: InterviewConfirmIn,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """接收第一阶段 run_id 与用户编辑后的 background，创建入口消息与正式面试。"""
    return ok(InterviewService().confirm_interview(current_user["id"], payload))


@router.get(
    "/{interview_id}",
    response_model=ResponseModel[InterviewOut],
    summary="获取面试详情",
)
def get_interview(
    interview_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """按 interview_id + user_id 查询，返回含 qa_object 的面试详情。"""
    return ok(InterviewService().get_interview(current_user["id"], interview_id))
