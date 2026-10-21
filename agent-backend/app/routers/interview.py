"""路由层：面试详情接口（按 interview_id + 当前用户查询）。"""

from fastapi import APIRouter, Depends

from ..schemas.interview import InterviewOut
from ..schemas.response import ResponseModel, ok
from ..services import interview_service
from .deps import get_current_user

router = APIRouter(
    prefix="/api/interviews",
    tags=["interviews"],
    dependencies=[Depends(get_current_user)],
)


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
    return ok(interview_service.get_interview(current_user["id"], interview_id))
