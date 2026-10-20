"""业务层：上传文件的类型识别与大小上限。

图片以文件头为准（不信任客户端 MIME / 扩展名）；文档与音频按扩展名白名单 + 文件头校验。
"""

import mimetypes
from pathlib import Path

from ..core.config import AVATAR_MAX_BYTES, FILE_MAX_BYTES

IMAGE = "image"
DOCUMENT = "document"
AUDIO = "audio"

DEFAULT_CONTENT_TYPE = "application/octet-stream"

# 图片以文件头为准，服务端决定扩展名，避免伪造扩展名
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)

# 文档扩展名白名单；带固定文件头的类型额外校验，防止伪造
_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".rtf",
    ".json",
}
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_DOCUMENT_SIGNATURES = {
    ".pdf": (_PDF_MAGIC,),
    ".docx": _ZIP_MAGICS,
    ".xlsx": _ZIP_MAGICS,
    ".pptx": _ZIP_MAGICS,
    ".doc": (_OLE_MAGIC,),
    ".xls": (_OLE_MAGIC,),
    ".ppt": (_OLE_MAGIC,),
}

# 音频扩展名白名单；同样校验文件头，避免伪装成音频的任意文件落桶
_AUDIO_SUFFIXES = {
    ".mp3",
    ".wav",
    ".ogg",
    ".opus",
    ".m4a",
    ".aac",
    ".flac",
    ".webm",
}
# 有固定文件头的音频类型；wav / m4a 需要按偏移校验，单独处理
_AUDIO_MAGICS = {
    ".ogg": (b"OggS",),
    ".opus": (b"OggS",),
    ".flac": (b"fLaC",),
    ".webm": (b"\x1a\x45\xdf\xa3",),
}

# 显式声明音频 Content-Type：mimetypes 在不同系统对 .m4a / .opus 的推断不一致
_AUDIO_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}


def detect_image(data: bytes) -> str | None:
    """返回图片扩展名；识别不出返回 None。"""
    for signature, suffix in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return suffix
    # WebP：RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def detect_document(data: bytes, filename: str) -> str | None:
    """返回文档扩展名；扩展名不在白名单或文件头不符时返回 None。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in _DOCUMENT_SUFFIXES:
        return None
    signatures = _DOCUMENT_SIGNATURES.get(suffix)
    if signatures and not any(data.startswith(signature) for signature in signatures):
        return None
    return suffix


def _has_audio_header(data: bytes, suffix: str) -> bool:
    """校验音频文件头；扩展名与内容不符时返回 False。"""
    if suffix == ".wav":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if suffix == ".m4a":
        # MP4 容器：第 4~8 字节固定为 ftyp
        return len(data) >= 8 and data[4:8] == b"ftyp"
    if suffix in {".mp3", ".aac"}:
        # ID3v2 标签开头，或 MPEG 音频帧同步（前 11 位全 1）
        return data.startswith(b"ID3") or (
            len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0
        )
    return any(data.startswith(magic) for magic in _AUDIO_MAGICS[suffix])


def detect_audio(data: bytes, filename: str) -> str | None:
    """返回音频扩展名；扩展名不在白名单或文件头不符时返回 None。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in _AUDIO_SUFFIXES or not _has_audio_header(data, suffix):
        return None
    return suffix


def size_limit(kind: str) -> int:
    """图片用于头像，沿用更严格的 2MB 上限；文档与音频 10MB。"""
    return AVATAR_MAX_BYTES if kind == IMAGE else FILE_MAX_BYTES


def content_type_for(suffix: str) -> str:
    """按扩展名推断 Content-Type，未知类型回退 octet-stream。"""
    return _AUDIO_CONTENT_TYPES.get(
        suffix, mimetypes.types_map.get(suffix, DEFAULT_CONTENT_TYPE)
    )
