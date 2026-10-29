"""业务层：本地向量模型（fastembed）的共享能力。

长期记忆的画像写入意图、流程总控的语义意图兜底都依赖同一份中文向量模型，
集中在这里加载可避免重复初始化；模型初始化与推理共用一把锁串行化，
防止启动预热线程与首个请求并发初始化。

本模块不导入其他业务模块，任何依赖方都可以安全引用，不会形成循环依赖。
"""

import math
import threading
from collections.abc import Sequence

# 本地小模型：中文语义相似度，首次使用时由 fastembed 下载并缓存
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"

_embedder = None
# 同时保护「首次初始化」与「模型推理」：fastembed 实例不保证并发安全
_lock = threading.Lock()


def get_embedder():
    """懒加载模型（双检锁）：`import app.main` 阶段不会触发模型下载。"""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is None:
            # 延迟导入：fastembed 依赖较重，只有真正需要向量时才加载
            from fastembed import TextEmbedding

            _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return _embedder


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """批量向量化；模型返回 numpy 数组，统一转成普通 list 便于比较。"""
    embedder = get_embedder()
    with _lock:
        return [list(map(float, vector)) for vector in embedder.embed(list(texts))]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """纯 Python 余弦相似度，避免为一次比较引入额外数值依赖。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def warmup() -> None:
    """只加载模型，供启动预热线程调用；失败由调用方决定是否降级。"""
    get_embedder()
