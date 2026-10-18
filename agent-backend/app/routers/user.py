"""路由层：用户增删改查接口。

统一前缀 /api（与前端 Vite 代理 /api → http://127.0.0.1:8000 对齐）。
路由函数只做参数透传与状态码声明，业务逻辑全部委托给 user_service。
"""

from fastapi import APIRouter, status

from ..schemas.user import UserCreate, UserOut, UserUpdate
from ..services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])

@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="创建用户")
def create_user(payload: UserCreate) -> dict:
    """新增用户，返回创建后的用户信息（不含密码）。

    status_code=status.HTTP_201_CREATED 的作用：
    - 201 Created 是 HTTP 标准中表示“资源已创建”的状态码。
    - 当接口用于执行新增操作（例如创建用户）时，返回 201 比 200 更准确，语义更符合 REST/HTTP 约定。
    - 客户端可以据此判断：请求成功且服务器已创建了一个新的用户资源，而不是仅仅返回了正常成功结果。
    - 在 FastAPI 中，设置 status_code 后，接口响应会返回对应状态码，并在 OpenAPI/Swagger 文档中正确展示该接口的语义。
    - 这有利于前端、第三方客户端和自动化测试更清晰地识别“创建成功”这一场景。
    """
    return user_service.create_user(payload)


@router.get("", response_model=list[UserOut], summary="查询用户列表")
def list_users() -> list[dict]:
    """查询全部用户。"""
    return user_service.list_users()


@router.get("/{user_id}", response_model=UserOut, summary="查询单个用户")
def get_user(user_id: int) -> dict:
    """按 id 查询用户，不存在返回 404。"""
    return user_service.get_user(user_id)


@router.put("/{user_id}", response_model=UserOut, summary="更新用户")
def update_user(user_id: int, payload: UserUpdate) -> dict:
    """按 id 局部更新用户（只更新传入的字段）。"""
    return user_service.update_user(user_id, payload)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除用户")
def delete_user(user_id: int) -> None:
    """按 id 删除用户，不存在返回 404。"""
    user_service.delete_user(user_id)
