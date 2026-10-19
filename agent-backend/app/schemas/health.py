"""校验层：健康检查响应模型。"""

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    """健康检查出参：服务状态与数据库连通性。"""

    status: str = Field(..., description="服务状态，正常为 ok")
    database: str = Field(..., description="数据库连通性，正常为 up")
