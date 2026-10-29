"""语义意图分类测试：阈值判断、示例缓存与失败降级。

向量化与余弦相似度用替身替换，不触发 fastembed 模型下载。
"""

import pytest

from app.services import semantic_intent
from app.services.semantic_intent import SemanticIntentClassifier


@pytest.fixture(autouse=True)
def clear_example_cache() -> None:
    """示例向量是进程级缓存：每个用例前后都清理，避免替身互相污染。"""
    semantic_intent._cache_clear()
    yield
    semantic_intent._cache_clear()


def test_singleton_is_shared() -> None:
    """进程内只创建一个分类器实例。"""
    assert SemanticIntentClassifier.get() is SemanticIntentClassifier.get()


def test_short_text_skips_embedding(monkeypatch) -> None:
    """空白 / 单字直接返回 False，不调用向量化。"""

    def _boom(_: object) -> list[list[float]]:
        raise AssertionError("过短文本不应触发向量化")

    monkeypatch.setattr(semantic_intent, "embed_texts", _boom)

    classifier = SemanticIntentClassifier()
    assert classifier.classify_intent("   ", ("出几道练习题",)) is False
    assert classifier.classify_intent("题", ("出几道练习题",)) is False


def test_empty_examples_return_false(monkeypatch) -> None:
    """规则没有示例时不做无意义的向量比较。"""

    def _boom(_: object) -> list[list[float]]:
        raise AssertionError("无示例时不应触发向量化")

    monkeypatch.setattr(semantic_intent, "embed_texts", _boom)

    assert SemanticIntentClassifier().classify_intent("帮我测一下", ()) is False


def test_threshold_is_inclusive(monkeypatch) -> None:
    """相似度 >= 阈值即命中；差一点则未命中。"""
    monkeypatch.setattr(
        semantic_intent, "embed_texts", lambda texts: [[1.0] for _ in texts]
    )
    monkeypatch.setattr(semantic_intent, "cosine", lambda a, b: 0.6)

    classifier = SemanticIntentClassifier()
    assert classifier.classify_intent("测一下", ("小测验",), threshold=0.6) is True

    monkeypatch.setattr(semantic_intent, "cosine", lambda a, b: 0.5999)
    assert classifier.classify_intent("测一下", ("小测验",), threshold=0.6) is False


def test_uses_max_similarity_across_examples(monkeypatch) -> None:
    """取与全部示例的最大相似度，而不是第一条。"""

    def _fake_embed(texts):
        return [[0.1], [0.9]] if len(texts) == 2 else [[1.0]]

    monkeypatch.setattr(semantic_intent, "embed_texts", _fake_embed)
    # 用示例向量本身代表相似度：第一条 0.1 未过阈值，第二条 0.9 命中
    monkeypatch.setattr(semantic_intent, "cosine", lambda a, b: b[0])

    classifier = SemanticIntentClassifier()
    assert classifier.classify_intent("检验掌握程度", ("弱相关", "强相关")) is True


def test_embedding_failure_degrades_to_false(monkeypatch) -> None:
    """模型异常时返回 False，不向主流程抛错。"""

    def _boom(_: object) -> list[list[float]]:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(semantic_intent, "embed_texts", _boom)

    assert SemanticIntentClassifier().classify_intent("测测我的水平", ("小测验",)) is False


def test_warmup_swallows_errors(monkeypatch) -> None:
    """预热失败只记日志，不影响调用方（启动线程 / 首个请求会重试）。"""

    def _boom():
        raise RuntimeError("download failed")

    monkeypatch.setattr(semantic_intent.embedding, "warmup", _boom)

    SemanticIntentClassifier().warmup()  # 不抛异常即通过
