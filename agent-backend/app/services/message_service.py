"""业务层：聊天消息查询。

消息表只存来源索引 [{chunk_id, score}]，查询时回查知识片段原文；
知识块已删除时返回提示文案，保证前端历史回显不中断。
附件段只存 resource_id，读取时重新预签名，避免历史图片链接过期。
"""

import logging

from fastapi import status

from ..core import minio_client
from ..core.exceptions import BusinessException
from ..db import knowledge_chunk_repo, message_repo, resource_repo, session_repo

logger = logging.getLogger(__name__)

DELETED_SOURCE_TEXT = "该参考片段已被删除"


def _segments(value: object) -> list[dict]:
    """附件段只接受数组；历史脏数据统一按空数组返回。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _segment_resource_ids(rows: list[dict]) -> list[int]:
    """收集本页消息附件引用的资源 ID，批量回表避免逐条查询。"""
    ids: set[int] = set()
    for row in rows:
        for key in ("request_segments", "response_segments"):
            for segment in _segments(row.get(key)):
                resource_id = segment.get("resource_id")
                if isinstance(resource_id, int):
                    ids.add(resource_id)
    return list(ids)


def _signed_url(resource: dict) -> str | None:
    """按资源存储路径生成预签名地址；失败只记日志，不阻断消息列表。"""
    storage_path = resource.get("storage_path")
    if not isinstance(storage_path, str) or not storage_path:
        return None
    try:
        return minio_client.presigned_url_for_storage_path(storage_path)
    except Exception:
        logger.warning(
            "消息附件预签名失败 | resource_id=%s", resource.get("id"), exc_info=True
        )
        return None


def _enrich_segments(
    value: object, resources: dict[int, dict]
) -> list[dict]:
    """补全附件段：资源存在时刷新 url 与文件名，实现历史链接自动续签。"""
    segments: list[dict] = []
    for segment in _segments(value):
        item = dict(segment)
        resource = resources.get(item.get("resource_id"))
        if resource is not None:
            if not item.get("file_name"):
                item["file_name"] = resource.get("file_name")
            url = _signed_url(resource)
            if url:
                item["url"] = url
            else:
                item.pop("url", None)
        segments.append(item)
    return segments


def _reference_refs(value: object) -> list[dict]:
    """reference_sources 只接受 [{chunk_id, score}]；无有效 chunk_id 的项跳过。"""
    if not isinstance(value, list):
        return []
    return [
        ref
        for ref in value
        if isinstance(ref, dict) and isinstance(ref.get("chunk_id"), str) and ref["chunk_id"]
    ]


def _build_sources(rows: list[dict]) -> dict[int, list[dict]]:
    """按消息批量回查切片原文，返回 {message_id: sources}。

    知识块已删除（或资源被清理）时仍保留该来源，text 换成提示文案。
    """
    refs_by_message: dict[int, list[dict]] = {}
    vector_ids: list[str] = []
    for row in rows:
        refs = _reference_refs(row.get("reference_sources"))
        if not refs:
            continue
        refs_by_message[row["id"]] = refs
        vector_ids.extend(ref["chunk_id"] for ref in refs)

    chunks = knowledge_chunk_repo.fetch_sources_by_vector_ids(vector_ids)
    sources: dict[int, list[dict]] = {}
    for message_id, refs in refs_by_message.items():
        items: list[dict] = []
        for ref in refs:
            chunk_id = ref["chunk_id"]
            chunk = chunks.get(chunk_id)
            if chunk is None:
                items.append(
                    {
                        "chunk_id": chunk_id,
                        "resource_id": None,
                        "chunk_index": None,
                        "file_name": None,
                        "score": ref.get("score"),
                        "text": DELETED_SOURCE_TEXT,
                    }
                )
            else:
                items.append({**chunk, "score": ref.get("score")})
        sources[message_id] = items
    return sources


def _to_out(
    message: dict, sources: list[dict], resources: dict[int, dict]
) -> dict:
    """正文、附件段、状态与参考来源一起返回，供前端渲染消息与来源卡片。"""
    return {
        "id": message["id"],
        "request_id": message.get("request_id"),
        "request_text": message["request_text"],
        "response_text": message["response_text"],
        "request_segments": _enrich_segments(
            message.get("request_segments"), resources
        ),
        "response_segments": _enrich_segments(
            message.get("response_segments"), resources
        ),
        "response_payload": message.get("response_payload"),
        "status": message["status"],
        "interview_id": message.get("interview_id"),
        "created_at": message["created_at"],
        "sources": sources,
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
    rows = message_repo.list_by_session(session_id, offset, page_size)
    sources = _build_sources(rows)
    resources = resource_repo.get_many(_segment_resource_ids(rows))
    return {
        "items": [
            _to_out(row, sources.get(row["id"], []), resources) for row in rows
        ],
        "total": message_repo.count_by_session(session_id),
        "page": page,
        "page_size": page_size,
    }
