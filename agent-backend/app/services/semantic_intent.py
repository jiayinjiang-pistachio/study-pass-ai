"""业务层：语义意图判断（向量相似度兜底）。

流程总控在关键词快筛未命中时，用本模块把用户问题与规则里的 intent_examples
逐一比较：与任一示例的余弦相似度达到阈值即视为命中。

模型 / 向量化异常一律降级为「未命中」（走通用聊天），不向主流程抛错；
关键词命中时调用方不会进入这里，避免无谓的模型调用。
"""

import logging
import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import ClassVar

from . import embedding
from .embedding import cosine, embed_texts

logger = logging.getLogger(__name__)

# 与任一示例的余弦相似度达到该值即视为命中
INTENT_THRESHOLD = 0.6
# 单字（「题」「嗯」）与示例几乎没有语义可比性，直接跳过
INTENT_MIN_CHARS = 2

__all__ = ["INTENT_MIN_CHARS", "INTENT_THRESHOLD", "SemanticIntentClassifier"]


@lru_cache(maxsize=8)
def _example_vectors(examples: tuple[str, ...]) -> tuple[list[float], ...]:
    """示例向量按规则缓存：不同规则共用同一份模型，向量只算一次。"""
    return tuple(embed_texts(examples))


def _cache_clear() -> None:
    """清空示例向量缓存；测试替换向量化实现后需要调用。"""
    _example_vectors.cache_clear()


class SemanticIntentClassifier:
    """进程级单例：模型加载成本高，全应用共享一个分类器实例。"""

    _instance: ClassVar["SemanticIntentClassifier | None"] = None
    _instance_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get(cls) -> "SemanticIntentClassifier":
        """双检锁单例：并发首次调用也只创建一个实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def warmup(self) -> None:
        """加载向量模型；失败只记日志，首次判断时会自动重试。"""
        try:
            embedding.warmup()
        except Exception:
            logger.warning("语义意图模型预热失败，首次判断时将重试", exc_info=True)

    def classify_intent(
        self,
        text: str,
        examples: Sequence[str],
        threshold: float = INTENT_THRESHOLD,
    ) -> bool:
        """判断 text 是否与任一示例语义相似（取最大相似度，>= 阈值即命中）。"""
        text = (text or "").strip()
        if len(text) < INTENT_MIN_CHARS or not examples:
            return False

        try:
            query = embed_texts([text])[0]
            vectors = _example_vectors(tuple(examples))
        except Exception:
            logger.warning(
                "语义意图判断失败，按未命中处理 | text=%s", text[:50], exc_info=True
            )
            return False

        return max(cosine(query, vector) for vector in vectors) >= threshold
