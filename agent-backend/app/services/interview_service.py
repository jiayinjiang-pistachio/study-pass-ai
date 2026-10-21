"""业务层：面试详情查询。"""

from fastapi import status

from ..core.exceptions import BusinessException
from ..db import interview_repo


def get_interview(user_id: int, interview_id: int) -> dict:
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
        "interview_duration": interview["interview_duration"],
        "status": interview["status"],
        "created_at": interview["created_at"],
        "updated_at": interview["updated_at"],
    }
