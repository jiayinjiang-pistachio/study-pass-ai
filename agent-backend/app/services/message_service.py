"""业务层：聊天消息查询。"""

from fastapi import status

from ..core.exceptions import BusinessException
from ..db import message_repo, session_repo


def _segments(value: object) -> list[dict]:
    """附件段只接受数组；历史脏数据统一按空数组返回。"""
    return value if isinstance(value, list) else []


def _to_out(message: dict) -> dict:
    """正文、附件段与状态字段一起返回，供前端渲染面试卡片/附件。"""
    return {
        "id": message["id"],
        "request_text": message["request_text"],
        "response_text": message["response_text"],
        "request_segments": _segments(message.get("request_segments")),
        "response_segments": _segments(message.get("response_segments")),
        "status": message["status"],
        "interview_id": message.get("interview_id"),
        "created_at": message["created_at"],
    }


def list_messages(
    user_id: int, session_id: int, page: int, page_size: int
) -> dict:
    """分页返回会话消息；会话不属于当前用户时 404。"""
    if session_repo.get_for_user(session_id, user_id) is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={session_id} user_id={user_id}",
        )

    offset = (page - 1) * page_size
    return {
        "items": [
            _to_out(row)
            for row in message_repo.list_by_session(session_id, offset, page_size)
        ],
        "total": message_repo.count_by_session(session_id),
        "page": page,
        "page_size": page_size,
    }
