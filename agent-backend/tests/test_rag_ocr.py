"""扫描页判定与 OCR 兜底测试；全部使用假服务，不访问火山引擎 / Qdrant。"""

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

from app.core.exceptions import SystemException
from app.rag import core as rag_core
from app.rag import ocr as ocr_module


class _FakeService:
    """按顺序返回预设响应并记录请求的 OCR 服务替身；最后一个响应会重复使用。"""

    def __init__(self, *responses: dict) -> None:
        self._responses = list(responses)
        self.forms: list[dict] = []

    def ocr_normal(self, form: dict) -> dict:
        self.forms.append(form)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _image_only_pdf(tmp_path: Path, pages: int = 1) -> Path:
    """Pillow 保存的 PDF 没有文本层，正好模拟扫描件。"""
    images = [Image.new("RGB", (60, 30), "white") for _ in range(pages)]
    path = tmp_path / "scan.pdf"
    images[0].save(
        path,
        format="PDF",
        resolution=150,
        save_all=True,
        append_images=images[1:],
    )
    return path


def _success(*line_texts: str) -> dict:
    return {"code": 10000, "data": {"line_texts": list(line_texts)}}


def _gateway_error(code: str) -> dict:
    return {
        "ResponseMetadata": {"Error": {"Code": code, "Message": "gateway error"}}
    }


def _patch_service(monkeypatch, service: _FakeService) -> None:
    monkeypatch.setattr(ocr_module, "_build_service", lambda: service)
    # 重试等待对测试无意义，置零避免拖慢用例
    monkeypatch.setattr(ocr_module, "_OCR_RETRY_DELAY_SECONDS", 0)


def test_ocr_pdf_returns_text_by_page(monkeypatch, tmp_path: Path) -> None:
    service = _FakeService(_success("第一行", "第二行", ""))
    _patch_service(monkeypatch, service)

    result = ocr_module.ocr_pdf(_image_only_pdf(tmp_path))

    assert result == {0: "第一行\n第二行"}
    assert len(service.forms) == 1
    assert service.forms[0]["image_base64"]


def test_ocr_pdf_only_processes_requested_pages(monkeypatch, tmp_path: Path) -> None:
    service = _FakeService(_success("第二页"))
    _patch_service(monkeypatch, service)

    result = ocr_module.ocr_pdf(_image_only_pdf(tmp_path, pages=2), page_indices=[1])

    assert result == {1: "第二页"}
    assert len(service.forms) == 1


def test_ocr_pdf_rejects_out_of_range_page(monkeypatch, tmp_path: Path) -> None:
    service = _FakeService(_success("任意"))
    _patch_service(monkeypatch, service)

    with pytest.raises(ValueError):
        ocr_module.ocr_pdf(_image_only_pdf(tmp_path), page_indices=[3])

    assert service.forms == []


def test_ocr_pdf_does_not_retry_gateway_permission_error(
    monkeypatch, tmp_path: Path
) -> None:
    service = _FakeService(_gateway_error("AccessDenied"), _success("不应使用"))
    _patch_service(monkeypatch, service)

    with pytest.raises(SystemException) as excinfo:
        ocr_module.ocr_pdf(_image_only_pdf(tmp_path))

    assert "AccessDenied" in (excinfo.value.detail or "")
    assert len(service.forms) == 1


def test_ocr_pdf_retries_transient_error_once(monkeypatch, tmp_path: Path) -> None:
    service = _FakeService(_gateway_error("InternalError"), _success("重试成功"))
    _patch_service(monkeypatch, service)

    result = ocr_module.ocr_pdf(_image_only_pdf(tmp_path))

    assert result == {0: "重试成功"}
    assert len(service.forms) == 2


def test_ocr_pdf_fails_after_retry_exhausted(monkeypatch, tmp_path: Path) -> None:
    service = _FakeService(_gateway_error("InternalError"))
    _patch_service(monkeypatch, service)

    with pytest.raises(SystemException) as excinfo:
        ocr_module.ocr_pdf(_image_only_pdf(tmp_path))

    assert "attempts=2" in (excinfo.value.detail or "")
    assert len(service.forms) == 2


def test_text_chars_ignores_page_numbers_and_whitespace() -> None:
    assert rag_core._text_chars("第一行\n- 12 -\n\n  ") == 3


def test_needs_ocr_requires_both_signals() -> None:
    assert rag_core._needs_ocr("页眉", 0.9) is True
    assert rag_core._needs_ocr("字" * 200, 0.9) is False
    assert rag_core._needs_ocr("", 0.1) is False


def test_image_coverage_detects_full_page_image(tmp_path: Path) -> None:
    document = pdfium.PdfDocument(str(_image_only_pdf(tmp_path)))
    try:
        page = document[0]
        try:
            assert rag_core._image_coverage(page) >= 0.5
        finally:
            page.close()
    finally:
        document.close()


def test_parse_pdf_keeps_text_layer_when_no_scan_pages(
    monkeypatch, tmp_path: Path
) -> None:
    pages = ["a" * 19, "b" * 21]
    monkeypatch.setattr(rag_core, "_analyze_pdf", lambda _path: (pages, []))
    monkeypatch.setattr(ocr_module, "ocr_pdf", lambda *_a, **_k: pytest.fail("不应触发 OCR"))

    assert rag_core._parse_pdf(tmp_path / "text.pdf") == "\n".join(pages)


def test_parse_pdf_merges_ocr_pages_in_order(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        rag_core, "_analyze_pdf", lambda _path: (["文本页", "扫描页"], [1])
    )
    calls: list[list[int]] = []

    def _fake_ocr(_path: Path, page_indices: list[int]) -> dict[int, str]:
        calls.append(page_indices)
        return {1: "OCR 文本"}

    monkeypatch.setattr(ocr_module, "ocr_pdf", _fake_ocr)

    assert rag_core._parse_pdf(tmp_path / "mix.pdf") == "文本页\nOCR 文本"
    assert calls == [[1]]
