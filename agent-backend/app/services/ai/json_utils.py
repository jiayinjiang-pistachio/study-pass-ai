"""AI 输出解析工具：把模型返回的文本还原成 JSON 对象。

模型常带 Markdown 代码块或前后解释，这里统一截取第一个 `{` 到最后一个 `}`，
解析失败时抛 ValueError，由业务层转成通用的 AI 服务错误。
"""

import json

__all__ = ["parse_json_object"]


def parse_json_object(raw: str) -> dict:
    """解析模型输出中的 JSON 对象；格式非法时抛 ValueError。"""
    text = (raw or "").strip()
    if not text:
        raise ValueError("模型输出为空")

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型输出中没有 JSON 对象")

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型输出不是合法 JSON：{exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return data
