"""路由层：用户增删改查接口。

统一前缀 /api（与前端 Vite 代理 /api → http://127.0.0.1:8000 对齐）。
路由函数只做参数透传与状态码声明，业务逻辑全部委托给 user_service；
返回值统一用 ok() 包成响应信封 {code, message, data}。
"""

from fastapi import APIRouter, status

from ..schemas.response import ResponseModel, ok
from ..schemas.user import UserCreate, UserOut, UserUpdate
from ..services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", response_model=ResponseModel[UserOut], status_code=status.HTTP_200_OK, summary="创建用户")
def create_user(payload: UserCreate) -> dict:
    """新增用户，返回创建后的用户信息（不含密码）。"""
    return ok(user_service.create_user(payload))


@router.get("", response_model=ResponseModel[list[UserOut]], summary="查询用户列表")
def list_users() -> dict:
    """查询全部用户。"""
    return ok(user_service.list_users())


@router.get("/{user_id}", response_model=ResponseModel[UserOut], summary="查询单个用户")
def get_user(user_id: int) -> dict:
    """按 id 查询用户，不存在返回 404。"""
    return ok(user_service.get_user(user_id))


@router.put("/{user_id}", response_model=ResponseModel[UserOut], summary="更新用户")
def update_user(user_id: int, payload: UserUpdate) -> dict:
    """按 id 局部更新用户（只更新传入的字段）。"""
    return ok(user_service.update_user(user_id, payload))


@router.delete("/{user_id}", response_model=ResponseModel[None], status_code=status.HTTP_200_OK, summary="删除用户")
def delete_user(user_id: int) -> dict:
    """按 id 删除用户，不存在返回 404。

    删除成功返回 200 + 信封（data 为 null）；不使用 204，因为 204 无响应体，
    前端无法解析统一信封。
    """
    user_service.delete_user(user_id)
    return ok(None)
