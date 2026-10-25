"""校验层：通用文件上传的出参模型。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FileOut(BaseModel):
    """上传结果：图片可能同时更新了用户头像。"""

    url: str = Field(..., description="资源路径（MinIO 内部格式 minio:/{bucket}/{key}）")
    md5: str = Field(..., description="文件内容的 MD5（用户级去重键）")
    size: int = Field(..., description="文件字节数")
    kind: Literal["image", "document", "audio"] = Field(
        ..., description="识别出的文件类型：文档为 PDF / DOCX / TXT，图片仅头像"
    )
    resource_id: int = Field(..., description="resources 表主键")
    storage_path: str = Field(..., description="MinIO 路径；只提取内容场景为空串")
    expire_time: datetime | None = Field(None, description="资源过期时间，空表示不过期")
