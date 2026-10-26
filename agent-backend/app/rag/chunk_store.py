"""切片原文存储：Qdrant 只存向量与过滤字段，原文写入 MySQL knowledge_chunks。

vector_id 与 Qdrant Point id 相同，检索命中向量后按它回表取原文。
本模块只负责写库，commit / rollback 由调用方控制。
"""

import logging
from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db.models import KnowledgeChunk

logger = logging.getLogger(__name__)

__all__ = ["save_chunks"]


def save_chunks(
    db: Session,
    resource_id: int,
    chunks: Sequence[str],
    vector_ids: Sequence[str],
) -> int:
    """用本次切片整体替换某资源的原文记录，返回写入条数。

    先删后插保证重灌幂等：同一事务内失败会回滚到旧数据；
    调用方负责 commit，使原文与后续业务状态落在同一事务里。
    """
    if len(chunks) != len(vector_ids):
        raise ValueError("chunks 与 vector_ids 数量不一致")

    db.execute(
        delete(KnowledgeChunk).where(KnowledgeChunk.resource_id == resource_id)
    )
    db.add_all(
        [
            KnowledgeChunk(
                vector_id=vector_id,
                resource_id=resource_id,
                chunk_index=index,
                text=text,
                char_count=len(text),
            )
            for index, (text, vector_id) in enumerate(zip(chunks, vector_ids))
        ]
    )
    # 提前 flush，让唯一键 / 外键等数据库错误在调用方 commit 前暴露
    db.flush()
    return len(chunks)
