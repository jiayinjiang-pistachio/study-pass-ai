"""MinIO 客户端：桶初始化、对象读写与 storage_path 格式转换。

业务层只调用本模块，不直接接触 minio SDK；存储故障统一转 SystemException(503)。
"""

import io
import logging
from functools import lru_cache

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import HTTPError

from .config import MinioConfig, get_minio_config
from .exceptions import SystemException

logger = logging.getLogger(__name__)

STORAGE_PREFIX = "minio:/"
DEFAULT_CONTENT_TYPE = "application/octet-stream"


@lru_cache
def _config() -> MinioConfig:
    """连接配置只读取一次；缺失时在首次使用处报错，避免导入即失败。"""
    return get_minio_config()


@lru_cache
def get_client() -> Minio:
    """返回进程内复用的 MinIO 客户端。"""
    cfg = _config()
    return Minio(
        cfg.endpoint,
        access_key=cfg.access_key,
        secret_key=cfg.secret_key,
        secure=cfg.secure,
    )


@lru_cache
def _bucket_ready() -> bool:
    """确保桶存在；结果缓存，避免每次上传都 head_bucket。"""
    cfg = _config()
    client = get_client()
    if not client.bucket_exists(cfg.bucket):
        client.make_bucket(cfg.bucket)
        logger.info("MinIO 桶已创建：%s", cfg.bucket)
    return True


def _storage_failure(action: str, exc: Exception) -> SystemException:
    """把存储层异常转成统一的系统异常，原始信息只进日志与 detail。"""
    logger.error("MinIO %s 失败：%s", action, exc)
    return SystemException(
        "文件存储服务不可用，请稍后重试",
        http_status=503,
        detail=f"minio {action}: {exc}",
    )


def ensure_bucket() -> None:
    """确保配置的桶存在（启动时调用；失败由调用方决定是否阻断）。"""
    try:
        _bucket_ready()
    except (S3Error, HTTPError, OSError) as exc:
        raise _storage_failure("ensure bucket", exc) from exc


def put_object(object_key: str, data: bytes, content_type: str) -> None:
    """上传对象；同 key 覆盖写，天然幂等。"""
    ensure_bucket()
    cfg = _config()
    try:
        get_client().put_object(
            cfg.bucket,
            object_key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except (S3Error, HTTPError, OSError) as exc:
        raise _storage_failure("put object", exc) from exc


def get_object(object_key: str) -> tuple[bytes, str] | None:
    """读取对象内容与 Content-Type；对象不存在返回 None。"""
    ensure_bucket()
    try:
        response = get_client().get_object(_config().bucket, object_key)
        try:
            data = response.read()
            content_type = response.headers.get("Content-Type") or DEFAULT_CONTENT_TYPE
        finally:
            response.close()
            response.release_conn()
        return data, content_type
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return None
        raise _storage_failure("get object", exc) from exc
    except (HTTPError, OSError) as exc:
        raise _storage_failure("get object", exc) from exc


def remove_object(object_key: str) -> None:
    """删除对象；对象不存在时 MinIO 视为成功（幂等）。"""
    try:
        get_client().remove_object(_config().bucket, object_key)
    except (S3Error, HTTPError, OSError) as exc:
        raise _storage_failure("remove object", exc) from exc


def object_exists(object_key: str) -> bool:
    """判断对象是否存在，供测试与排查使用。"""
    try:
        get_client().stat_object(_config().bucket, object_key)
        return True
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return False
        raise _storage_failure("stat object", exc) from exc
    except (HTTPError, OSError) as exc:
        raise _storage_failure("stat object", exc) from exc


def build_storage_path(object_key: str) -> str:
    """生成入库格式：minio:/{bucket}/{object_key}。"""
    return f"{STORAGE_PREFIX}{_config().bucket}/{object_key}"


def object_key_from_storage_path(storage_path: str) -> str | None:
    """从 storage_path 还原 object_key；非本桶 / 空路径返回 None。"""
    prefix = f"{STORAGE_PREFIX}{_config().bucket}/"
    if not storage_path.startswith(prefix):
        return None
    key = storage_path.removeprefix(prefix)
    return key or None
