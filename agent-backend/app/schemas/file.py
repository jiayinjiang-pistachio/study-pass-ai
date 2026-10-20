"""校验层：通用文件上传的出参模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class FileOut(BaseModel):
    """上传结果：kind=image 时同时更新了用户头像。"""

    url: str = Field(..., description="静态访问 URL")
    md5: str = Field(..., description="文件内容的 MD5（文件名即由此生成）")
    size: int = Field(..., description="文件字节数")
    kind: Literal["image", "document"] = Field(..., description="识别出的文件类型")
