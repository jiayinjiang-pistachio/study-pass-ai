"""RAG 检索：问题向量化 → Qdrant 近邻检索 → 按 vector_id 回表取原文。

Qdrant 只存向量与过滤字段，命中后从 MySQL knowledge_chunks 取切片原文；
检索始终按 user_id 隔离，避免跨用户召回；可按 doc_category 进一步收窄范围。
对外只暴露 search_similar_chunks。
"""

import logging

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from ..core import config
from ..core.exceptions import BusinessException, SystemException
from ..db.session import SessionLocal
from .chunk_store import fetch_chunks_by_vector_ids
from .core import CATEGORIES, COLLECTION_NAME, _embed

logger = logging.getLogger(__name__)

__all__ = ["search_similar_chunks"]

DEFAULT_TOP_K = 5

# 余弦相似度阈值：低于该值的片段与问题相关性太弱，直接丢弃
SCORE_THRESHOLD = 0.4

# 单条切片回传上限：过长片段会挤占模型上下文，按字符截断
MAX_TEXT_CHARS = 800


def search_similar_chunks(
    query: str,
    user_id: int,
    top_k: int = DEFAULT_TOP_K,
    doc_category: str | None = None,
) -> list[dict]:
    """检索当前用户最相关的知识库切片，按相似度从高到低返回。

    doc_category 传入时只在该分类内检索（resume / study_material / general），
    可在向量检索阶段直接收窄候选集；为 None 时检索用户全部知识库。

    返回项包含 vector_id / resource_id / file_name / doc_category /
    chunk_index / score / text；text 超过 MAX_TEXT_CHARS 会被截断，
    char_count 仍为原文长度。未命中返回空列表。
    """
    question = query.strip()
    if not question:
        raise BusinessException("检索问题不能为空", http_status=422)
    if top_k <= 0:
        raise ValueError("top_k 必须为正整数")
    if doc_category is not None and doc_category not in CATEGORIES:
        raise BusinessException(
            "不支持的文档分类",
            http_status=422,
            detail=f"doc_category={doc_category}",
        )

    # 与入库共用同一套向量化逻辑，保证查询与切片在同一向量空间
    vector = _embed([question])[0]

    try:
        client = QdrantClient(
            host=config.QDRANT_HOST, port=config.QDRANT_PORT, timeout=30
        )
        try:
            # 尚未有任何文档入库时集合不存在，直接视为无结果
            if not client.collection_exists(COLLECTION_NAME):
                return []

            conditions = [
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id),
                )
            ]
            if doc_category is not None:
                conditions.append(
                    FieldCondition(
                        key="doc_category",
                        match=MatchValue(value=doc_category),
                    )
                )

            response = client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                query_filter=Filter(must=conditions),
                limit=top_k,
                score_threshold=SCORE_THRESHOLD,
                with_payload=True,
            )
        finally:
            client.close()
    except Exception as exc:
        raise SystemException("知识库检索失败", detail=str(exc)) from exc

    points = response.points
    if not points:
        return []

    with SessionLocal() as db:
        chunks = fetch_chunks_by_vector_ids(
            db, [str(point.id) for point in points]
        )

    results: list[dict] = []
    for point in points:
        vector_id = str(point.id)
        chunk = chunks.get(vector_id)
        if chunk is None:
            # 向量已写入但原文缺失，跳过以免返回空片段污染上下文
            logger.warning("检索命中但原文缺失：vector_id=%s", vector_id)
            continue

        payload = point.payload or {}
        results.append(
            {
                "vector_id": vector_id,
                "resource_id": chunk["resource_id"],
                "file_name": payload.get("file_name"),
                "doc_category": payload.get("doc_category"),
                "chunk_index": chunk["chunk_index"],
                "score": point.score,
                "text": chunk["text"][:MAX_TEXT_CHARS],
            }
        )
    return results
