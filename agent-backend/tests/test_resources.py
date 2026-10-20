"""资源过期清理测试：必须先删 MinIO 对象，成功后再删元数据。"""

import hashlib
from datetime import datetime, timedelta

from app.core import minio_client
from app.core.exceptions import SystemException
from app.db import resource_repo
from app.services import resource_cleanup

PDF_DATA = b"%PDF-1.4\nexpired-resource"


def _insert_expired_resource(user_id: int) -> tuple[dict, str]:
    """造一条已过期的资源记录，并在 MinIO 写入对应对象。"""
    md5 = hashlib.md5(PDF_DATA, usedforsecurity=False).hexdigest()
    key = f"users/{user_id}/{md5}.pdf"
    minio_client.put_object(key, PDF_DATA, "application/pdf")
    resource = resource_repo.insert(
        {
            "resource_type": 0,
            "storage_scene": 0,
            "upload_purpose": 0,
            "file_name": "expired.pdf",
            "file_hash": md5,
            "storage_path": minio_client.build_storage_path(key),
            "user_id": user_id,
            "expire_time": datetime.now() - timedelta(minutes=1),
        }
    )
    return resource, key


def test_cleanup_deletes_object_then_metadata(
    auth_user: dict, minio_ready: None
) -> None:
    """过期资源 → MinIO 对象与元数据都被删除。"""
    resource, key = _insert_expired_resource(auth_user["id"])
    assert minio_client.object_exists(key)

    deleted = resource_cleanup.cleanup_expired()

    assert deleted >= 1
    assert resource_repo.get(resource["id"]) is None
    assert not minio_client.object_exists(key)


def test_cleanup_keeps_metadata_when_object_delete_fails(
    auth_user: dict, minio_ready: None, monkeypatch
) -> None:
    """对象删除失败 → 保留元数据，等待下一轮重试。"""
    resource, _ = _insert_expired_resource(auth_user["id"])

    def _raise(_: str) -> None:
        raise SystemException("存储不可用")

    monkeypatch.setattr(minio_client, "remove_object", _raise)

    assert resource_cleanup.cleanup_expired() == 0
    assert resource_repo.get(resource["id"]) is not None
