"""模型层：provider → 模型实例。

只负责根据配置创建 LangChain ChatModel，不关心提示词、上下文与业务规则。
所有受支持服务商都走 OpenAI 兼容协议，因此统一使用 ChatOpenAI，
差异（base_url / model / 密钥）由配置层消化。
"""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ...core.config import get_llm_config


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    """创建并复用模型实例，避免每次对话重复初始化 HTTP 连接池。

    配置缺失时抛 RuntimeError，由业务层转成 503；不影响其他接口启动。
    """
    config = get_llm_config()
    return ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        timeout=config.timeout,
        max_retries=config.max_retries,
        streaming=True,
    )
