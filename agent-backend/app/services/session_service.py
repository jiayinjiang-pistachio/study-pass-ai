"""业务层：会话管理（分页、创建、编辑、级联删除）。

删除会话时按依赖顺序清理：interviews → chat_messages → session，
再根据消息附件段收集 resource_id，删除资源元数据与 MinIO 对象。
"""

import logging

from fastapi import status

from ..core import minio_client
from ..core.exceptions import BusinessException, SystemException
from ..db import interview_repo, message_repo, resource_repo, session_repo
from ..schemas.session import SessionCreate, SessionUpdate

logger = logging.getLogger(__name__)


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


def _to_out(session: dict) -> dict:
    """裁剪出参字段，避免把 user_id 暴露给前端。"""
    return {
        "id": session["id"],
        "title": session["title"],
        "session_mode": session["session_mode"],
        "created_at": session["created_at"],
    }


def list_sessions(
    user_id: int,
    page: int,
    page_size: int,
    session_mode: int | None = None,
) -> dict:
    """分页返回当前用户的会话，最近创建的在前；可按会话模式过滤。"""
    offset = (page - 1) * page_size
    return {
        "items": [
            _to_out(row)
            for row in session_repo.list_for_user(
                user_id, offset, page_size, session_mode
            )
        ],
        "total": session_repo.count_for_user(user_id, session_mode),
        "page": page,
        "page_size": page_size,
    }


def create_session(user_id: int, payload: SessionCreate) -> dict:
    """创建会话：归属当前用户。"""
    session = session_repo.insert(
        {
            "user_id": user_id,
            "title": payload.title,
            "session_mode": payload.session_mode,
        }
    )
    return _to_out(session)


def update_session(user_id: int, session_id: int, payload: SessionUpdate) -> dict:
    """修改会话标题；只能修改自己的会话。"""
    _get_owned_session(user_id, session_id)
    session = session_repo.update_title(session_id, payload.title)
    if session is None:
        raise BusinessException(
            "会话不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"session_id={session_id}",
        )
    return _to_out(session)


def _collect_resource_ids(messages: list[dict]) -> set[int]:
    """从消息的附件段中收集 resource_id（只认附件段，忽略正文）。"""
    resource_ids: set[int] = set()
    for message in messages:
        for field in ("request_segments", "response_segments"):
            segments = message.get(field)
            if not isinstance(segments, list):
                continue
            for segment in segments:
                if not isinstance(segment, dict):
                    continue
                resource_id = segment.get("resource_id")
                if isinstance(resource_id, int):
                    resource_ids.add(resource_id)
                elif isinstance(resource_id, str) and resource_id.isdigit():
                    resource_ids.add(int(resource_id))
    return resource_ids


def _delete_resources(user_id: int, resource_ids: set[int]) -> None:
    """删除当前用户自己的资源：先删 MinIO 对象，再删元数据。

    对象删除失败时保留元数据，交给过期清理任务重试，避免产生无法追溯的孤儿对象。
    """
    for resource_id in sorted(resource_ids):
        resource = resource_repo.get(resource_id)
        if resource is None or resource["user_id"] != user_id:
            continue

        object_key = (
            minio_client.object_key_from_storage_path(resource["storage_path"])
            if resource["storage_path"]
            else None
        )
        if object_key is not None:
            try:
                minio_client.remove_object(object_key)
            except (SystemException, RuntimeError):
                logger.warning(
                    "会话删除时资源对象删除失败，保留元数据：resource_id=%s",
                    resource_id,
                )
                continue

        resource_repo.delete(resource_id)


def delete_session(user_id: int, session_id: int) -> None:
    """级联删除会话及其消息、面试记录、附件资源。"""
    _get_owned_session(user_id, session_id)

    # 先收集 resource_id：消息删除后就无法再解析附件段
    messages = message_repo.list_all_by_session(session_id)
    resource_ids = _collect_resource_ids(messages)

    # interviews 依赖 chat_messages.message_id，必须先删
    interview_repo.delete_by_session(session_id)
    message_repo.delete_by_session(session_id)
    session_repo.delete(session_id)

    _delete_resources(user_id, resource_ids)
