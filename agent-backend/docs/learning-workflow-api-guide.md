# 学习测评工作流 · Swagger 验证指南

面向本地联调：通过 `http://127.0.0.1:8000/docs` 依次调用鉴权、会话与学习测评接口，
验证「出题 → 作答 → 评分」闭环及各项约束。接口实现见
[`app/services/learning_workflow.py`](../app/services/learning_workflow.py)。

## 0. 前置条件

```bash
cd agent-backend && source .venv/bin/activate
alembic upgrade head          # 确认 workflow_runs 表已存在
uvicorn app.main:app --reload --port 8000
```

- 打开 `http://127.0.0.1:8000/docs`
- `.env` 必须配置 `LLM_API_KEY` / `LLM_MODEL`，否则 `/start` 返回 `503`

## 1. 注册并获取令牌

**POST `/api/auth/register`**（已有账号可跳过）

```json
{"username": "wf_demo_01", "password": "abc12345"}
```

**POST `/api/auth/login`**

```json
{"username": "wf_demo_01", "password": "abc12345"}
```

复制响应中的 `data.access_token` → 点击页面右上角 **Authorize** → 粘贴令牌
（不要加 `Bearer ` 前缀）→ Authorize。

> 访问令牌有效期 30 分钟；过期后重新登录。

## 2. 创建会话

**POST `/api/sessions`**

```json
{"title": "Python 基础测评", "session_mode": 0}
```

记下响应中的 `data.id`（即后续使用的 `session_id`）。

## 3. 发起测评出题

**POST `/api/learning-workflows/start`**

```json
{
  "session_id": 123,
  "request_text": "测一下 Python 基础，包括数据类型、函数和异常处理",
  "question_count": 3
}
```

预期响应（`HTTP 200`）：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "run_id": "6f1c9e3a-2b4d-4c8e-9a10-123456789abc",
    "status": "quiz_ready",
    "quiz": [
      {
        "question_id": 1,
        "type": "single_choice",
        "stem": "以下哪个是 Python 的不可变类型？",
        "options": [
          {"key": "A", "text": "list"},
          {"key": "B", "text": "tuple"}
        ]
      }
    ]
  }
}
```

检查点：

- `status == "quiz_ready"`，`quiz` 长度等于 `question_count`
- `question_id` 从 1 连续递增
- 题型为 `single_choice` / `multiple_choice` / `short_answer`
- **题目中没有 `answer` 字段**（标准答案不落库、不下发）

复制 `run_id`。

## 4. 提交整套作答

**POST `/api/learning-workflows/{run_id}/submit`**

按题型填写 `value`：

| 题型 | value 示例 |
| --- | --- |
| `single_choice` | `"B"` |
| `multiple_choice` | `["A", "C"]` |
| `short_answer` | `"索引用于加速查询定位"` |

必须覆盖**全部题目**：

```json
{
  "answers": [
    {"question_id": 1, "value": "B"},
    {"question_id": 2, "value": ["A", "C"]},
    {"question_id": 3, "value": "用于加速数据检索，减少全表扫描"}
  ]
}
```

预期响应（`HTTP 200`）：

```json
{
  "code": 200,
  "message": "ok",
  "data": {
    "run_id": "6f1c9e3a-2b4d-4c8e-9a10-123456789abc",
    "status": "completed",
    "score": 67,
    "evaluation": [
      {"question_id": 1, "correct": true, "comment": "正确，tuple 不可变"}
    ],
    "weaknesses": ["异常处理"],
    "review": "建议补充 try/except 与自定义异常的知识。"
  }
}
```

## 5. 查询运行详情

**GET `/api/learning-workflows/{run_id}`**

预期返回 `status` 与完整 `state`（含 `quiz`、`answers`、`evaluation`、`score`、`provider` 等）。

## 6. 反向用例（验证约束）

| 操作 | 预期 |
| --- | --- |
| 不点 Authorize 直接调接口 | `401 未提供认证凭证` |
| 用他人会话 `session_id` 发起 | `404 会话不存在` |
| 用他人 `run_id` 提交 / 查询 | `404 测评不存在` |
| 少提交一道题 | `422 还有 N 道题未作答` |
| 单选提交 `"Z"` | `422 第 1 题的选项非法` |
| 同一题重复提交 | `422 同一题目不能重复作答` |
| 对已完成的 `run_id` 再次提交 | `409 该测评已提交，请勿重复提交` |
| 未配置 LLM 密钥时发起 | `503 学习测评服务暂不可用` |
| 模型输出非法 JSON | `502 学习测评生成失败，请稍后重试` |

## 7. 数据库落库核对（可选）

```sql
SELECT run_id, workflow_type, status, completed_at,
       JSON_EXTRACT(state_json, '$.score') AS score,
       error_message
FROM workflow_runs
ORDER BY id DESC
LIMIT 5;
```

预期：

- 出题成功后 `status=quiz_ready`
- 提交成功后 `status=completed` 且 `completed_at` 非空
- 失败时 `status=failed` 且 `error_message` 记录原因
- 删除会话后对应 `workflow_runs` 记录随外键级联清理

## 8. 总控入口（可选）

前端也可以用统一入口 `POST /api/agent/tasks/start`：同一个接口按意图返回两种响应。

```json
{
  "agent_name": "quiz_generate_workflow",
  "session_id": 123,
  "request_text": "帮我出 3 道 Python 基础题",
  "question_count": 3
}
```

判断规则：`agent_name` 未登记 → `404`；问题命中出题关键词（出题 / 刷题 / 练习题 / 测验 …）→ 直接启动工作流；否则用语义相似度对比规则示例句；仍不命中 → 通用流式聊天。

| `request_text` | 预期响应 |
| --- | --- |
| `帮我出 3 道 Python 基础题` | `application/json`，`data.route=workflow`，含 `run_id` / `quiz` |
| `检验一下我对数据库索引的掌握程度` | `application/json`（关键词未命中，语义兜底命中） |
| `你好，介绍一下你自己` | `text/event-stream`，事件 `meta → delta* → done` |

工作流分支返回的 `run_id` 可直接用于 `POST /api/learning-workflows/{run_id}/submit`。

> 工作流分支忽略 `select_mode` / `request_segments`；聊天分支忽略 `question_count` / `provider`。



```
 语义兜底只在「agent_name 合法 + 关键词全部未命中」时触发，位于 app/services/orchestrator_service.py:96：         
 
  1. 把用户问题向量化一次（fastembed BAAI/bge-small-zh-v1.5，模型启动时已预热）                                                       
  2. 与该规则的 intent_examples 向量逐一算余弦相似度（示例向量按规则缓存，只算一次）                                                  
  3. 取最大值 >= 0.6 → 判定为出题意图，走 learning_quiz 工作流；否则返回 None，走通用聊天                                             
  所以它解决的是「说法不同但意思一样」的问题，例如「检验一下我对数据库索引的掌握程度」不含任何关键词，但语义上接近「测测我对这个知识点
  的掌握程度」而命中。模型/向量化异常只记 WARNING 并返回 False，不会阻断请求，也不会凭空升级成工作流。
```



## 9. 实现对照

| 环节 | 代码位置 |
| --- | --- |
| 路由 | `app/routers/learning_workflow.py` |
| 入参 / 出参校验 | `app/schemas/learning_workflow.py` |
| LangGraph 图与业务逻辑 | `app/services/learning_workflow.py` |
| 模型 JSON 解析 | `app/services/ai/json_utils.py` |
| 状态持久化 | `app/db/workflow_run_repo.py`、`workflow_runs` 表 |
| 流程总控 | `app/routers/orchestrator.py`、`app/services/orchestrator_service.py` |
| 语义意图兜底 | `app/services/semantic_intent.py`、`app/services/embedding.py` |
