"""业务层：读取用户头像（把 MinIO 对象还原成可直出的字节流）。"""

from fastapi import status

from ..core import minio_client
from ..core.exceptions import BusinessException
from ..db import user_repo


def get_avatar(user_id: int) -> tuple[bytes, str]:
    """返回头像内容与 Content-Type；用户未设置头像或对象丢失时 404。"""
    user = user_repo.get(user_id)
    storage_path = user["avatar"] if user else None
    if not storage_path:
        raise BusinessException(
            "头像不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"user_id={user_id}",
        )

    object_key = minio_client.object_key_from_storage_path(storage_path)
    if object_key is None:
        raise BusinessException(
            "头像不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"user_id={user_id} avatar={storage_path}",
        )

    result = minio_client.get_object(object_key)
    if result is None:
        raise BusinessException(
            "头像不存在",
            http_status=status.HTTP_404_NOT_FOUND,
            detail=f"user_id={user_id} object_key={object_key}",
        )
    return result
