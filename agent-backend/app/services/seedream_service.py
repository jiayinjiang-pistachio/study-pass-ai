"""业务层：Seedream 文生图。

只负责「提示词 → 图片字节」：请求火山方舟图片生成接口、下载结果并做基础
校验；落库、消息回显与失败状态持久化由知识卡工作流编排。
"""

import base64
import binascii
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from ..core.config import SeedreamConfig, get_seedream_config
from ..core.exceptions import SystemException
from ..core.retry import RetryExhaustedError, RetryPolicy

logger = logging.getLogger(__name__)

NODE_NAME = "seedream_generate"
MAX_ATTEMPTS = 2
MAX_IMAGE_BYTES = 20 * 1024 * 1024
ERROR_BODY_MAX_CHARS = 500

# 合法尺寸：WIDTHxHEIGHT 或 2k / 3k / 4k
_SIZE_PATTERN = re.compile(r"^(?:\d{2,5}x\d{2,5}|[234][kK])$")


def _normalize_size(size: str) -> str:
    """校验并规范化尺寸；非法值直接暴露为配置错误。"""
    value = (size or "").strip()
    if not _SIZE_PATTERN.fullmatch(value):
        raise RuntimeError(
            f"SEEDREAM_IMAGE_SIZE 非法：{size!r}，应为 WIDTHxHEIGHT 或 2k/3k/4k"
        )
    return value.upper() if value[-1].lower() == "k" else value.lower()


def _post_json(url: str, body: dict, api_key: str, timeout: float) -> dict:
    """调用图片生成接口；网络 / HTTP / JSON 错误统一转成可重试的系统异常。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(ERROR_BODY_MAX_CHARS).decode("utf-8", errors="replace")
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail=f"seedream http {exc.code}: {detail}",
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail=f"seedream request: {exc}",
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail=f"seedream invalid json: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail="seedream response is not an object",
        )
    return payload


def _download(url: str, timeout: float) -> bytes:
    """下载生成结果；限制协议与体积，避免异常响应拖垮进程。"""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in {"http", "https"}:
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail=f"seedream image url scheme={scheme}",
        )

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail=f"seedream download: {exc}",
        ) from exc

    if not data:
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail="seedream empty image",
        )
    if len(data) > MAX_IMAGE_BYTES:
        raise SystemException(
            "生成图片过大，已取消保存",
            http_status=502,
            detail=f"seedream image > {MAX_IMAGE_BYTES} bytes",
        )
    return data


def _decode_first_image(payload: dict, timeout: float) -> bytes:
    """从接口响应中取第一张图：优先 base64，其次下载 URL。"""
    items = payload.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail="seedream response missing data[0]",
        )

    item = items[0]
    encoded = item.get("b64_json")
    if isinstance(encoded, str) and encoded.strip():
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SystemException(
                "知识卡出图失败，请稍后重试",
                http_status=502,
                detail=f"seedream invalid b64: {exc}",
            ) from exc

    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail="seedream response missing image url",
        )
    return _download(url, timeout)


def _generate_once(prompt: str, config: SeedreamConfig) -> bytes:
    """一次完整生成：请求接口并取回图片字节。"""
    endpoint = f"{config.base_url}/images/generations"
    payload = _post_json(
        endpoint,
        {
            "model": config.model,
            "prompt": prompt,
            "size": _normalize_size(config.image_size),
            "response_format": "url",
            "watermark": False,
        },
        config.api_key,
        config.timeout,
    )
    return _decode_first_image(payload, config.timeout)


def generate_image(prompt: str) -> bytes:
    """生成知识卡图片；配置缺失抛 RuntimeError，接口失败抛 SystemException(502)。"""
    config = get_seedream_config()
    try:
        return RetryPolicy(max_attempts=MAX_ATTEMPTS).run(
            lambda: _generate_once(prompt, config),
            node=NODE_NAME,
        )
    except RetryExhaustedError as exc:
        last = exc.last_error
        if isinstance(last, SystemException):
            raise last from exc
        logger.error(
            "Seedream 出图重试耗尽 | attempts=%s error=%s",
            exc.attempts,
            last,
            exc_info=True,
        )
        raise SystemException(
            "知识卡出图失败，请稍后重试",
            http_status=502,
            detail=f"seedream: {last}",
        ) from exc
