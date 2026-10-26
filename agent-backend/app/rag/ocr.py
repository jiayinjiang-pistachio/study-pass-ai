"""扫描版 PDF 的 OCR 兜底：按需渲染指定页为 PNG，调用火山引擎 OCRNormal。

对外只暴露 ocr_pdf(path, page_indices=None)；渲染、编码、请求与响应解析均为内部步骤。
"""

import base64
import io
import logging
import threading
import time
from collections.abc import Iterable
from pathlib import Path

import pypdfium2 as pdfium
from volcengine.visual.VisualService import VisualService

from ..core import config
from ..core.exceptions import SystemException

logger = logging.getLogger(__name__)

__all__ = ["ocr_pdf"]

# PDF 坐标默认 72 DPI，按目标 DPI 换算渲染缩放比例；
# 200 DPI 是 OCR 精度与上送体积的折中（150 对小字号偏糊，300 体积翻倍收益有限）。
_PDF_BASE_DPI = 72
RENDER_DPI = 200

_OCR_SUCCESS_CODE = "10000"

# 网络抖动 / 服务端临时故障值得重试；鉴权、参数错误重试也不会成功，立即失败。
_OCR_MAX_ATTEMPTS = 2
_OCR_RETRY_DELAY_SECONDS = 0.5
_RETRYABLE_CODES = frozenset(
    {
        "InternalError",
        "ServerError",
        "ServiceUnavailable",
        "Throttling",
        "RequestTimeout",
        "FlowLimitExceeded",
    }
)

# VisualService 是进程内单例，且内部复用一个 requests.Session；
# 后台入库可能并发，串行化调用避免共享会话状态竞争（OCR 单页耗时很短）。
_OCR_LOCK = threading.Lock()


class _RetryableOcrError(Exception):
    """网络 / 服务端临时故障：可重试。"""


def _build_service() -> VisualService:
    """按配置初始化 SDK 凭证；缺失时直接失败，避免发出无效请求。"""
    if not config.VOLC_ACCESS_KEY or not config.VOLC_SECRET_KEY:
        raise SystemException(
            "OCR 服务未配置",
            detail="缺少 VOLC_ACCESS_KEY / VOLC_SECRET_KEY",
        )

    service = VisualService()
    service.set_ak(config.VOLC_ACCESS_KEY)
    service.set_sk(config.VOLC_SECRET_KEY)
    # VisualService 未提供 set_region，地区保存在 credentials 上
    service.service_info.credentials.region = config.VOLC_REGION
    return service


def _render_png(page: pdfium.PdfPage) -> bytes:
    """按 200 DPI 渲染一页并编码为 PNG 字节。"""
    bitmap = page.render(scale=RENDER_DPI / _PDF_BASE_DPI)
    try:
        buffer = io.BytesIO()
        bitmap.to_pil().save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        bitmap.close()


def _request(service: VisualService, png: bytes) -> dict:
    """上送单页 PNG；传输层异常转成可重试错误。"""
    form = {"image_base64": base64.b64encode(png).decode("ascii")}
    try:
        with _OCR_LOCK:
            return service.ocr_normal(form)
    except Exception as exc:
        raise _RetryableOcrError(f"request error={exc}") from exc


def _parse_response(response: dict, page_index: int) -> list[str]:
    """校验响应并返回行文本；可重试错误抛 _RetryableOcrError，其余抛 SystemException。"""
    if not isinstance(response, dict):
        raise _RetryableOcrError(f"type={type(response).__name__}")

    # 网关级错误（鉴权 / 权限 / 限流）走 ResponseMetadata.Error，业务错误走顶层 code
    error = (response.get("ResponseMetadata") or {}).get("Error") or {}
    code = error.get("Code")
    if code and str(code) in _RETRYABLE_CODES:
        raise _RetryableOcrError(
            f"code={code} message={error.get('Message')}"
        )
    if error:
        raise SystemException(
            "OCR 识别失败",
            detail=(
                f"page={page_index + 1} code={code} "
                f"message={error.get('Message')}"
            ),
        )

    code = response.get("code")
    if code is not None and str(code) != _OCR_SUCCESS_CODE:
        detail = (
            f"page={page_index + 1} code={code} "
            f"message={response.get('message')}"
        )
        if str(code) in _RETRYABLE_CODES:
            raise _RetryableOcrError(detail)
        raise SystemException("OCR 识别失败", detail=detail)

    data = response.get("data") or response.get("Result") or {}
    line_texts = data.get("line_texts") or data.get("LineTexts") or []
    return [line for line in line_texts if isinstance(line, str) and line.strip()]


def _recognize(service: VisualService, png: bytes, page_index: int) -> list[str]:
    """识别单页，网络 / 临时故障重试一次；最终失败抛 SystemException 中止整份文档。"""
    last_error = ""
    for attempt in range(1, _OCR_MAX_ATTEMPTS + 1):
        try:
            return _parse_response(_request(service, png), page_index)
        except _RetryableOcrError as exc:
            last_error = str(exc)
            if attempt >= _OCR_MAX_ATTEMPTS:
                break
            logger.warning(
                "OCR 第 %s 次失败，准备重试：page=%s error=%s",
                attempt,
                page_index + 1,
                exc,
            )
            time.sleep(_OCR_RETRY_DELAY_SECONDS)

    raise SystemException(
        "OCR 识别失败",
        detail=(
            f"page={page_index + 1} attempts={_OCR_MAX_ATTEMPTS} "
            f"error={last_error}"
        ),
    )


def ocr_pdf(
    path: str | Path, page_indices: Iterable[int] | None = None
) -> dict[int, str]:
    """OCR 指定页（默认全部页），返回 `{页下标: 全文}`。

    只识别扫描页，避免对可搜索 PDF 重复调用付费 OCR；
    页下标从 0 开始，越界或未给出任何页时按调用方错误处理。
    """
    document = pdfium.PdfDocument(str(path))
    try:
        total = len(document)
        if page_indices is None:
            targets = list(range(total))
        else:
            targets = sorted(set(page_indices))
            for index in targets:
                if not 0 <= index < total:
                    raise ValueError(f"页码越界：{index}（共 {total} 页）")
        if not targets:
            return {}

        service = _build_service()
        recognized: dict[int, str] = {}
        for index in targets:
            page = document[index]
            try:
                png = _render_png(page)
            finally:
                page.close()
            recognized[index] = "\n".join(_recognize(service, png, index))
        return recognized
    finally:
        document.close()
