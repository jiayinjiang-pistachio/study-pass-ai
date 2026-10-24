"""路由层：当前用户的背景资料 CRUD（供提示词变量注入使用）。

统一前缀 /api/profiles，整组需登录；user_id 一律取自令牌，不接受客户端传入，
避免读写他人资料。
"""

from fastapi import APIRouter, Depends, status

from ..schemas.profile import ProfileCreate, ProfileOut, ProfileUpdate
from ..schemas.response import ResponseModel, ok
from ..services import profile_service
from .deps import get_current_user

router = APIRouter(
    prefix="/api/profiles",
    tags=["profiles"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "",
    response_model=ResponseModel[ProfileOut],
    status_code=status.HTTP_200_OK,
    summary="创建当前用户背景资料",
)
def create_profile(
    payload: ProfileCreate, current_user: dict = Depends(get_current_user)
) -> dict:
    """一人一份资料；已存在时返回 409。"""
    return ok(profile_service.create_profile(current_user["id"], payload))


@router.get(
    "/me",
    response_model=ResponseModel[ProfileOut],
    summary="查询当前用户背景资料",
)
def get_profile(current_user: dict = Depends(get_current_user)) -> dict:
    """未填写资料时返回 404。"""
    return ok(profile_service.get_profile(current_user["id"]))


@router.put(
    "/me",
    response_model=ResponseModel[ProfileOut],
    summary="更新当前用户背景资料",
)
def update_profile(
    payload: ProfileUpdate, current_user: dict = Depends(get_current_user)
) -> dict:
    """局部更新，只更新显式传入且非空的字段；未填写资料时返回 404。"""
    return ok(profile_service.update_profile(current_user["id"], payload))


@router.delete(
    "/me",
    response_model=ResponseModel[None],
    status_code=status.HTTP_200_OK,
    summary="删除当前用户背景资料",
)
def delete_profile(current_user: dict = Depends(get_current_user)) -> dict:
    """删除成功返回 200 + 信封（data 为 null）；未填写资料时返回 404。"""
    profile_service.delete_profile(current_user["id"])
    return ok(None)
