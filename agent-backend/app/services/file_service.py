"""业务层：通用文件上传（类型识别、按用户分目录、MD5 去重）。

- 图片按文件头识别（不信任客户端 MIME / 扩展名），保存后同步更新 users.avatar；
- 文档按扩展名 + 文件头识别，只保存，不写用户表；
- 存储路径：uploads/users/{user_id}/{md5}{扩展名}，同内容重复上传直接复用。
"""

import hashlib
import logging
from pathlib import Path

from fastapi import status

from ..core.config import AVATAR_MAX_BYTES, FILE_MAX_BYTES, UPLOAD_DIR
from ..core.exceptions import BusinessException
from ..db import user_repo

logger = logging.getLogger(__name__)

USERS_SUBDIR = "users"
UPLOAD_URL_PREFIX = "/uploads"

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


def _detect_image(data: bytes) -> str | None:
    """返回图片扩展名；识别不出返回 None。"""
    for signature, suffix in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return suffix
    # WebP：RIFF....WEBP
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _detect_document(data: bytes, filename: str) -> str | None:
    """返回文档扩展名；扩展名不在白名单或文件头不符时返回 None。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in _DOCUMENT_SUFFIXES:
        return None
    signatures = _DOCUMENT_SIGNATURES.get(suffix)
    if signatures and not any(data.startswith(signature) for signature in signatures):
        return None
    return suffix


def _user_dir(user_id: int) -> Path:
    path = UPLOAD_DIR / USERS_SUBDIR / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_old_avatar(avatar_url: str | None, keep: Path) -> None:
    """替换头像时删除旧文件；只处理 uploads 目录内、且不是本次新文件的路径。"""
    if not avatar_url:
        return

    root = UPLOAD_DIR.resolve()
    candidate = (UPLOAD_DIR / avatar_url.removeprefix(UPLOAD_URL_PREFIX).lstrip("/")).resolve()
    if candidate == keep or not candidate.is_relative_to(root) or not candidate.is_file():
        return

    try:
        candidate.unlink()
    except OSError:
        # 清理失败不影响本次上传结果，仅记录供排查
        logger.warning("旧头像删除失败：%s", candidate)


def upload(user_id: int, data: bytes, filename: str) -> dict:
    """识别文件类型并保存，图片同时更新用户头像。"""
    if not data:
        raise BusinessException(
            "文件内容为空",
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="empty file",
        )

    user = user_repo.get(user_id)
    if user is None:
        raise BusinessException(
            "用户不存在",
            http_status=status.HTTP_401_UNAUTHORIZED,
            detail=f"user_id={user_id}",
        )

    image_suffix = _detect_image(data)
    document_suffix = None if image_suffix else _detect_document(data, filename)
    if not image_suffix and not document_suffix:
        raise BusinessException(
            "不支持的文件类型",
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"filename={filename or 'unknown'}",
        )

    suffix = image_suffix or document_suffix
    limit = AVATAR_MAX_BYTES if image_suffix else FILE_MAX_BYTES
    if len(data) > limit:
        raise BusinessException(
            f"文件不能超过 {limit // (1024 * 1024)}MB",
            http_status=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"size={len(data)}",
        )

    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    target = _user_dir(user_id) / f"{md5}{suffix}"
    # 内容相同则直接复用已有文件（按 MD5 去重）
    if not target.is_file():
        target.write_bytes(data)

    url = f"{UPLOAD_URL_PREFIX}/{USERS_SUBDIR}/{user_id}/{target.name}"
    if image_suffix:
        if user["avatar"] != url:
            user_repo.update(user_id, {"avatar": url})
            _remove_old_avatar(user["avatar"], target)
        kind = "image"
    else:
        kind = "document"

    return {"url": url, "md5": md5, "size": len(data), "kind": kind}
