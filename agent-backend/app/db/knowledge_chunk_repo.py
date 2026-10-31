"""数据库层：knowledge_chunks 回查（历史消息重建参考来源）。

消息表只存 [{chunk_id, score}]，原文与文件名按 chunk_id 回查，
避免在 chat_messages 里重复保存知识块全文。
"""

from collections.abc import Sequence

from sqlalchemy import select

from .models import KnowledgeChunk, Resource
from .session import SessionLocal

__all__ = ["fetch_sources_by_vector_ids", "get_text_by_resource"]


def get_text_by_resource(resource_id: int) -> str:
    """按 chunk_index 升序拼接某资源的全部切片原文；没有切片时返回空串。"""
    with SessionLocal() as session:
        texts = session.scalars(
            select(KnowledgeChunk.text)
            .where(KnowledgeChunk.resource_id == resource_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
        ).all()
        return "\n".join(texts)


def fetch_sources_by_vector_ids(vector_ids: Sequence[str]) -> dict[str, dict]:
    """按 vector_id 批量取切片与资源文件名，返回 {chunk_id: 来源字段}。

    关联 resources 取 file_name；资源或切片已删除时不会出现在结果中，
    由调用方按「片段已删除」兜底。
    """
    if not vector_ids:
        return {}

    with SessionLocal() as session:
        rows = session.execute(
            select(KnowledgeChunk, Resource.file_name)
            .join(Resource, Resource.id == KnowledgeChunk.resource_id)
            .where(KnowledgeChunk.vector_id.in_(vector_ids))
        ).all()

    return {
        chunk.vector_id: {
            "chunk_id": chunk.vector_id,
            "resource_id": chunk.resource_id,
            "chunk_index": chunk.chunk_index,
            "file_name": file_name,
            "text": chunk.text,
        }
        for chunk, file_name in rows
    }
