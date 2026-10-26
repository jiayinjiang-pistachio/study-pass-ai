"""RAG 上下文：检索意图判断与命中片段格式化。

只做纯文本处理，不访问数据库 / 向量库；由业务层决定是否调用检索。
"""

import re
from collections.abc import Sequence

__all__ = ["format_retrieved_chunks", "should_retrieve"]

# 去空白与标点后的最小长度：低于该值基本是寒暄 / 确认，不值得付出检索成本
MIN_QUERY_CHARS = 5

# 无需检索的整句：确认语、礼貌语、推进语。命中（含组合，如「好的谢谢」）即跳过
_SKIP_PHRASES = frozenset(
    {
        "好",
        "好的",
        "好吧",
        "行",
        "行吧",
        "可以",
        "没问题",
        "嗯",
        "嗯嗯",
        "是",
        "是的",
        "对",
        "对的",
        "明白",
        "明白了",
        "收到",
        "了解",
        "知道了",
        "谢谢",
        "感谢",
        "多谢",
        "辛苦了",
        "麻烦了",
        "你好",
        "您好",
        "在吗",
        "继续",
        "继续吧",
        "继续讲",
        "继续讲一下",
        "继续说说",
        "继续说",
        "接着说",
        "下一步",
        "下一步呢",
        "然后呢",
        "往下讲",
        "开始吧",
        "ok",
        "okay",
        "yes",
        "yep",
        "hi",
        "hello",
        "thanks",
        "thankyou",
    }
)
# 按长度倒序删除，保证「好的」先于「好」被匹配，避免把组合语拆错
_SKIP_PHRASES_BY_LENGTH = tuple(sorted(_SKIP_PHRASES, key=len, reverse=True))

# \W 在 Unicode 下不会吞掉中文，因此可安全去掉空白、标点与符号
_PUNCTUATION_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def _normalize(text: str) -> str:
    """去空白 / 标点并转小写，便于整句匹配寒暄语。"""
    return _PUNCTUATION_RE.sub("", (text or "").strip()).lower()


def should_retrieve(request_text: str) -> bool:
    """轻量判断本轮是否需要检索知识库。

    跳过空输入、sentence 级极短输入，以及确认 / 礼貌 / 推进类整句；
    只要还包含实质内容（如「继续讲讲项目经历」）就照常检索。
    """
    normalized = _normalize(request_text)
    if len(normalized) < MIN_QUERY_CHARS:
        return False

    remainder = normalized
    for phrase in _SKIP_PHRASES_BY_LENGTH:
        remainder = remainder.replace(phrase, "")
    return bool(remainder)


def format_retrieved_chunks(chunks: Sequence[dict]) -> str:
    """把命中片段拼成注入本轮问题的参考文本；无命中返回空串。

    chunks 来自 retriever.search_similar_chunks，编号与 SSE sources 顺序一致，
    系统提示词据此要求模型用 [1] [2] 标注来源。
    """
    if not chunks:
        return ""

    lines = ["【知识库参考资料】"]
    for index, chunk in enumerate(chunks, start=1):
        file_name = chunk.get("file_name") or "未知文件"
        score = chunk.get("score")
        score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "-"
        chunk_index = chunk.get("chunk_index")
        lines.append(
            f"[{index}] 来源：{file_name}"
            f"（片段 {chunk_index if chunk_index is not None else '-'}，"
            f"相似度 {score_text}）"
        )
        lines.append((chunk.get("text") or "").strip())

    lines.append(
        "以上内容来自用户自己的知识库，回答时请优先依据这些资料；"
        "资料未覆盖的部分请明确说明，不要编造。"
    )
    return "\n".join(lines)
