"""路由层：需登录的通用文件上传接口。

POST /api/files（multipart，字段 file）：图片保存并更新头像，文档仅保存。
"""

from fastapi import APIRouter, Depends, File, UploadFile, status

from ..core.config import FILE_MAX_BYTES
from ..schemas.file import FileOut
from ..schemas.response import ResponseModel, ok
from ..services import file_service
from .deps import get_current_user

router = APIRouter(
    prefix="/api/files",
    tags=["files"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "",
    response_model=ResponseModel[FileOut],
    status_code=status.HTTP_200_OK,
    summary="上传文件（图片自动更新头像）",
)
async def upload_file(
    file: UploadFile = File(..., description="图片或文档，最大 10MB（图片 2MB）"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """读取上传内容，交由业务层识别类型、去重落盘并更新头像。"""
    # 多读 1 字节即可判断是否超限，避免把超大文件整体读进内存
    data = await file.read(FILE_MAX_BYTES + 1)
    return ok(file_service.upload(current_user["id"], data, file.filename or ""))
