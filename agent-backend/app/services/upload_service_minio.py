"""业务层：通用文件上传（MinIO 存储 + resources 元数据）。

- 原文件落 MinIO，元数据落 MySQL resources 表；
- 按 (file_hash, user_id) 去重：先查库，唯一键冲突时回查兜底；
- storage_scene=2 只写元数据，不落原文件；
- 仅 upload_purpose=1 且识别为图片时更新 users.avatar；
- 文档落库后通过 BackgroundTasks 异步接入 RAG；分类变化时替换旧向量。
"""

import hashlib
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, status
from sqlalchemy.exc import IntegrityError

from ..core import minio_client
from ..core.exceptions import BusinessException
from ..db import resource_repo, user_repo
from . import file_type

logger = logging.getLogger(__name__)

RESOURCE_TYPE_FILE = 0
RESOURCE_TYPE_IMAGE = 1
RESOURCE_TYPE_AUDIO = 2

# 识别出的类型 → resources.resource_type
_RESOURCE_TYPE = {
    file_type.DOCUMENT: RESOURCE_TYPE_FILE,
    file_type.IMAGE: RESOURCE_TYPE_IMAGE,
    file_type.AUDIO: RESOURCE_TYPE_AUDIO,
}

SCENE_LONG = 0
SCENE_SHORT = 1
SCENE_EXTRACT_ONLY = 2

PURPOSE_GENERAL = 0
PURPOSE_AVATAR = 1

# 存储场景对应的有效期；scene=2 与头像用途不设过期时间
SCENE_TTL = {
    SCENE_LONG: timedelta(days=30),
    SCENE_SHORT: timedelta(hours=2),
}


def _classify(data: bytes, filename: str, upload_purpose: int) -> tuple[str, str]:
    """返回 (类型, 扩展名)；文档支持 PDF / DOC / DOCX / TXT，图片仅用于头像。"""
    image_suffix = file_type.detect_image(data)
    if image_suffix:
        if upload_purpose == PURPOSE_AVATAR:
            return file_type.IMAGE, image_suffix
    else:
        document_suffix = file_type.detect_document(data, filename)
        if document_suffix:
            return file_type.DOCUMENT, document_suffix

        audio_suffix = file_type.detect_audio(data, filename)
        if audio_suffix:
            return file_type.AUDIO, audio_suffix

    raise BusinessException(
        "仅支持 PDF / DOC / DOCX / TXT 文档、音频文件（头像仅支持图片）",
        http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"filename={filename or 'unknown'}",
    )


def _expire_time(upload_purpose: int, storage_scene: int) -> datetime | None:
    """头像与「只提取内容」场景永不过期；其余按场景计算。"""
    if upload_purpose == PURPOSE_AVATAR or storage_scene == SCENE_EXTRACT_ONLY:
        return None
    return datetime.now() + SCENE_TTL[storage_scene]


def _to_out(resource: dict, size: int, kind: str, reused: bool) -> dict:
    """组装接口出参；url 暂与 MinIO 内部路径一致。"""
    return {
        "url": resource["storage_path"],
        "md5": resource["file_hash"],
        "size": size,
        "kind": kind,
        "resource_id": resource["id"],
        "storage_path": resource["storage_path"],
        "expire_time": resource["expire_time"],
        "doc_category": resource["doc_category"],
        "reused": reused,
    }


def _ingest_document(
    data: bytes,
    file_name: str,
    user_id: int,
    doc_category: str,
    resource_id: int,
    replace: bool,
) -> None:
    """后台把文档写入 RAG 知识库；失败只记日志，不影响上传结果。"""
    # 延迟导入：避免应用启动时就加载 dashscope / qdrant 等重依赖
    from ..rag import core as rag_core

    suffix = Path(file_name).suffix.lower()
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        rag_core.ingest_file(
            tmp_path,
            user_id,
            doc_category=doc_category,
            file_name=file_name,
            resource_id=resource_id,
            replace=replace,
        )
    except Exception:
        logger.exception(
            "文档 RAG 入库失败：user=%s file=%s resource=%s",
            user_id,
            file_name,
            resource_id,
        )
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def upload(
    user_id: int,
    data: bytes,
    filename: str,
    upload_purpose: int = PURPOSE_GENERAL,
    storage_scene: int = SCENE_LONG,
    *,
    doc_category: str | None = None,
    background_tasks: BackgroundTasks,
) -> dict:
    """识别类型、去重落库（必要时上传 MinIO），按用途更新头像并异步接入 RAG。"""
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

    kind, suffix = _classify(data, filename, upload_purpose)
    limit = file_type.size_limit(kind)
    if len(data) > limit:
        raise BusinessException(
            f"文件不能超过 {limit // (1024 * 1024)}MB",
            http_status=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"size={len(data)}",
        )

    # 文档必须显式选择业务类型；非文档忽略该字段
    category: str | None = None
    if kind == file_type.DOCUMENT:
        if doc_category is None:
            raise BusinessException(
                "请选择文档类型（简历 / 学习资料 / 通用文档）",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"filename={filename or 'unknown'}",
            )
        category = doc_category

    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    resource = resource_repo.find_by_hash(user_id, md5)
    created = False
    reingest = False

    if resource is None:
        object_key = f"users/{user_id}/{md5}{suffix}"
        storage_path = ""
        if storage_scene != SCENE_EXTRACT_ONLY:
            minio_client.put_object(object_key, data, file_type.content_type_for(suffix))
            storage_path = minio_client.build_storage_path(object_key)

        record = {
            "resource_type": _RESOURCE_TYPE[kind],
            "storage_scene": storage_scene,
            "upload_purpose": upload_purpose,
            "file_name": Path(filename).name[:255] or "unknown",
            "file_hash": md5,
            "storage_path": storage_path,
            "user_id": user_id,
            "expire_time": _expire_time(upload_purpose, storage_scene),
            "doc_category": category,
        }
        try:
            resource = resource_repo.insert(record)
            created = True
        except IntegrityError:
            # 并发上传同一内容：唯一键兜底，复用先写入的记录
            resource = resource_repo.find_by_hash(user_id, md5)
            if resource is None:
                raise

    # 已存在同内容：文档分类变化时更新元数据，并替换知识库中的旧向量
    if (
        not created
        and category is not None
        and resource["doc_category"] != category
    ):
        updated = resource_repo.update_doc_category(resource["id"], category)
        if updated is not None:
            resource = updated
            reingest = True

    if kind == file_type.DOCUMENT and (created or reingest):
        background_tasks.add_task(
            _ingest_document,
            data,
            resource["file_name"],
            user_id,
            resource["doc_category"],
            resource["id"],
            reingest,
        )

    # 仅头像用途的图片更新 users.avatar；scene=2 没有对象时不更新
    if (
        upload_purpose == PURPOSE_AVATAR
        and kind == file_type.IMAGE
        and resource["storage_path"]
        and user["avatar"] != resource["storage_path"]
    ):
        user_repo.update(user_id, {"avatar": resource["storage_path"]})

    return _to_out(resource, len(data), kind, not created)
