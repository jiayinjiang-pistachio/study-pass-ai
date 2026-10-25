"""路由层：需登录的通用文件上传接口。

POST /api/files（multipart，字段 file）：原文件落 MinIO，元数据落 resources；
upload_purpose=1 且图片类型时更新头像。
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Response,
    UploadFile,
    status,
)

from ..core.config import FILE_MAX_BYTES
from ..schemas.file import DocCategory, FileOut
from ..schemas.response import ResponseModel, ok
from ..services import avatar_service
from ..services import upload_service_minio as upload_service
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
    summary="上传文件（文档 PDF / DOC / DOCX / TXT、音频；图片仅头像）",
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="PDF / DOC / DOCX / TXT 文档或音频，最大 10MB；头像图片 2MB",
    ),
    upload_purpose: Annotated[
        int, Form(ge=0, le=1, description="上传用途：0=普通资源，1=用户头像")
    ] = 0,
    storage_scene: Annotated[
        int, Form(ge=0, le=2, description="存储场景：0=长期，1=短期，2=只提取内容")
    ] = 0,
    doc_category: Annotated[
        DocCategory | None,
        Form(description="文档业务类型：resume / study_material / general"),
    ] = None,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """读取上传内容，交由业务层识别类型、去重落库、更新头像并异步接入 RAG。"""
    # 多读 1 字节即可判断是否超限，避免把超大文件整体读进内存
    data = await file.read(FILE_MAX_BYTES + 1)
    return ok(
        upload_service.upload(
            current_user["id"],
            data,
            file.filename or "",
            upload_purpose=upload_purpose,
            storage_scene=storage_scene,
            doc_category=doc_category,
            background_tasks=background_tasks,
        )
    )


# 头像读取单独走公开路由：浏览器 <img src> 无法携带 Authorization 头
public_router = APIRouter(prefix="/api/files", tags=["files"])


@public_router.get(
    "/avatar/{user_id}",
    response_model=None,
    response_class=Response,
    summary="读取用户头像（公开，供 img 标签直接访问）",
)
def read_avatar(user_id: int) -> Response:
    """返回头像二进制内容；URL 带 ?v= 版本号，头像更新后自动失效缓存。"""
    data, content_type = avatar_service.get_avatar(user_id)
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
