"""路由层：学习测评工作流接口。

统一前缀 /api/learning-workflows，整组需登录；run_id 归属按令牌中的 user_id 校验。
"""

from fastapi import APIRouter, BackgroundTasks, Depends

from ..schemas.learning_workflow import (
    LearningWorkflowDetailOut,
    LearningWorkflowStartIn,
    LearningWorkflowStartOut,
    LearningWorkflowSubmitIn,
    LearningWorkflowSubmitOut,
)
from ..schemas.response import ResponseModel, ok
from ..services import learning_workflow
from .deps import get_current_user

router = APIRouter(
    prefix="/api/learning-workflows",
    tags=["learning-workflows"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/start",
    response_model=ResponseModel[LearningWorkflowStartOut],
    summary="发起学习测评并生成题目",
)
def start_learning_workflow(
    payload: LearningWorkflowStartIn,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """执行启动图（准备 → 出题），返回结构化 quiz 供前端表单渲染。"""
    return ok(learning_workflow.start_learning_workflow(current_user["id"], payload))


@router.post(
    "/{run_id}/submit",
    response_model=ResponseModel[LearningWorkflowSubmitOut],
    summary="提交学习测评作答并获取评分",
)
def submit_learning_workflow(
    run_id: str,
    payload: LearningWorkflowSubmitIn,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """按 run_id 恢复题目，执行评测图：评分、逐题点评、薄弱点与建议。

    笔记归档交由后台任务执行，避免下游模型调用拖慢提交接口。
    """
    return ok(
        learning_workflow.submit_learning_workflow(
            current_user["id"],
            run_id,
            payload,
            background_tasks=background_tasks,
        )
    )


@router.get(
    "/{run_id}",
    response_model=ResponseModel[LearningWorkflowDetailOut],
    summary="查询学习测评运行详情",
)
def get_learning_workflow(
    run_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """返回流程状态与完整 state（题目、作答、评分等）。"""
    return ok(learning_workflow.get_learning_workflow(current_user["id"], run_id))
