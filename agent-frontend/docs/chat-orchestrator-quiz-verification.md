# 聊天总控 + 学习测评 · 前端页面验证指南

> **状态**：已实现（对应当前代码）
> **范围**：学习室 / 面试间的聊天发送（统一走总控）、智能体按钮、学习测评入口与答题弹窗
> **前置文档**：后端接口契约见 [`learning-workflow-api-guide.md`](../../agent-backend/docs/learning-workflow-api-guide.md)、
> 总控设计见 [`orchestrator-workflow-design.md`](../../agent-backend/docs/orchestrator-workflow-design.md)
> **最后更新**：2026-10-29

本文只描述**如何通过前端页面操作**验证功能，不重复接口细节。

---

## 1. 启动环境

### 1.1 后端（端口 18000，避免与默认 8000 冲突）

```bash
cd agent-backend
source .venv/bin/activate
alembic upgrade head                 # 确认 workflow_runs / chat_messages 表存在
uvicorn app.main:app --port 18000
```

`.env` 需配置：

| 变量 | 必需 | 用途 |
| --- | --- | --- |
| `MYSQL_URL` | 是 | 会话、消息、工作流记录 |
| `JWT_SECRET` | 是 | 登录令牌 |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | 是 | 出题与评分；缺失时工作流接口返回 `503` |
| Redis | 否 | 不可用时自动回源 MySQL，不影响验证 |

### 1.2 前端（Vite 代理指向 18000）

```bash
cd agent-frontend
pnpm install
API_PROXY_TARGET=http://127.0.0.1:18000 pnpm dev
```

打开 `http://localhost:5173/login`，注册或登录一个测试账号。

> 开发环境会自动加载 `src/mock/`，但会话 / 聊天 / 测评均走真实后端接口，无需关闭 Mock。

---

## 2. 验证项清单

### 2.1 智能体按钮

| # | 操作 | 预期 |
| --- | --- | --- |
| 1 | 进入「学习室」，查看输入框上方 | 显示 3 个按钮：出题测评 / 难点学习 / 笔记归档 |
| 2 | 进入「面试间」，查看输入框上方 | 显示 4 个按钮：面试主考官 / 面试评测 / 难点学习 / 笔记归档 |
| 3 | 点击「笔记归档」 | 按钮高亮（金色底），表示已选中 |
| 4 | 再次点击同一按钮 | 取消选中，回到房间默认智能体 |
| 5 | 切换到另一个房间 | 两个房间的选择互不影响（按房间各记一份） |
| 6 | 发送过程中观察按钮 | 发送期间按钮置灰禁用 |

> 未选中任何按钮时使用房间默认智能体：学习室 → `quiz_generate_workflow`，面试间 → `interview_host`。
> 学习室默认智能体只负责路由判断：普通问题在关键词 / 语义未命中时仍走聊天分支。

### 2.2 聊天统一走总控（SSE 分支）

| # | 操作 | 预期 |
| --- | --- | --- |
| 7 | 学习室选中「笔记归档」，发送「用三句话总结一下 REST 的核心约束」 | AI 逐字流式回复，无 404 |
| 8 | 同一操作下查看 DevTools → Network | `POST /api/agent/tasks/start`，响应 `Content-Type: text/event-stream`，事件顺序 `meta → delta* → done` |
| 9 | 选中「出题测评」但发送普通问题（如「你好」） | 仍为流式聊天（关键词与语义均未命中，回落聊天分支） |
| 10 | 面试间不选按钮，发送「帮我做一次后端面试开场」 | 默认 `interview_host`，流式回复 |
| 11 | 刷新页面后查看历史 | 上述问答正常回显，无重复消息 |

### 2.3 学习测评：出题

| # | 操作 | 预期 |
| --- | --- | --- |
| 12 | 学习室（不选或选中「出题测评」）发送「帮我出 3 道 Python 基础题」 | 输入框占位提示变为「正在处理，请稍候…」；消息区先显示「正在生成…」 |
| 13 | 等待出题完成 | Network 中该请求返回 `application/json`（统一信封，`data.route = "workflow"`，含 `run_id` 与 `quiz`）；会话自动刷新 |
| 14 | 出题消息渲染 | 出现「查看并填写测评题目」入口卡片，并**自动弹出**「学习测评」弹窗 |
| 15 | 弹窗内容 | 题目数量与请求一致（3 道）；单选为 radio、多选为 checkbox、简答为 textarea；简答题无选项 |
| 16 | 关闭弹窗，再点击入口卡片 | 弹窗重新打开，入口按钮始终可用 |

> 自动弹窗每个测评只触发一次（同一页面生命周期内以 `request_id` 去重）；刷新页面后会重新自动弹出。
> 若后端重启导致 checkpoint 丢失，已出题的旧测评在提交时会返回 `409 测评流程已失效`，重新发送出题即可。

### 2.4 学习测评：答题与评分

| # | 操作 | 预期 |
| --- | --- | --- |
| 17 | 只完成部分题目，点击「提交答案」 | 弹出警告「请完成所有题目后再提交」，页面滚动定位到第一道未答题；不发起请求 |
| 18 | 全部作答后提交 | 主按钮显示加载中，文案变为「正在提交答案并生成评分...」；所有控件禁用 |
| 19 | 提交成功 | 弹窗关闭，测评入口卡片消失；原消息正文变为评分文本（得分 + 逐题点评 + 薄弱点 + 建议） |
| 20 | 刷新页面 | 原消息仍为评分文本，无测评入口；**不新增**一条消息 |
| 21 | 再次提交同一测评（模拟并发 / 旧页面） | 后端返回 `409 已提交`，请求层提示错误，弹窗保持打开 |
| 22 | 出题后不提交，直接刷新页面 | 测评入口仍在，弹窗再次自动弹出，可继续作答 |

### 2.5 历史接口字段（可选）

DevTools 中查看 `GET /api/sessions/{session_id}/messages?page=1&page_size=20` 的响应：

- 测评题目消息：`request_id = "{run_id}:quiz"`，`response_payload` 为题目数组，`response_text = "已完成出题，请完成后提交答案。"`
- 评分后同一消息：`response_payload = null`，`response_text` 为点评文本
- 普通聊天消息：`request_id` 一般为 `null`，`response_payload = null`

前端仅当 `request_id` 含 `quiz` 且 `response_payload` 非空时展示测评入口。

---

## 3. 请求链路速查

| 场景 | 请求 | 响应 |
| --- | --- | --- |
| 任意发送 | `POST /api/agent/tasks/start`，body `{agent_name, session_id, request_text}` | 聊天：`text/event-stream`；工作流：JSON 信封 |
| 工作流完成后刷新 | `GET /api/sessions/{id}/messages?page=1&page_size=20` → 最后一页 | 用服务端消息替换本地临时行 |
| 提交测评 | `POST /api/learning-workflows/{run_id}/submit`，body `{answers:[{question_id, value}]}` | 统一信封，含 `score / evaluation / weaknesses / review` |
| 提交后刷新 | 同「工作流完成后刷新」 | 原消息更新为点评文本、载荷清空 |

`run_id` 由 `request_id` 冒号前半段解析；旧接口 `POST /api/sessions/{id}/stream-chat` 仍保留，但页面已不再调用。

---

## 4. 数据库核对（可选）

```sql
-- 出题后：应有一行 request_id 以 :quiz 结尾、response_payload 非空
SELECT id, request_id, status, response_text, response_payload
FROM chat_messages
WHERE session_id = <会话 ID>
ORDER BY id;

-- 评分后：同一行 response_text 变为点评、response_payload 为 NULL，行数不变
```

```sql
-- 工作流状态：出题后 waiting_answer，评分后 completed
SELECT run_id, status, state_json, error_message, completed_at
FROM workflow_runs
WHERE user_id = <用户 ID>
ORDER BY id DESC;
```

---

## 5. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 发送后提示「智能体不存在」（404） | 前端智能体常量与后端 `CHAT_AGENT_NAMES` 不一致 | 核对 `src/types/agent.ts` 与 `orchestrator_service.py` |
| 出题请求 503 | 未配置 LLM Key | 补齐 `.env` 中的 `LLM_*` 后重启后端 |
| 出题请求 502 | 模型输出非 JSON / 模型异常 | 查看 `logs/app.log` 与 `workflow_runs.error_message` |
| 提交提示「测评流程已失效」 | 后端重启导致 MemorySaver checkpoint 丢失 | 重新发起测评（旧记录已置 failed） |
| 测评入口不出现 | 历史接口未返回 `request_id` / `response_payload`，或两者不匹配 | 检查历史接口响应与前端是否为最新构建 |
| 弹窗没有自动打开 | 同一测评本页面已自动打开过一次 | 点击入口卡片手动打开；刷新页面可再次自动弹出 |
| 评分后入口仍存在 | 前端未刷新成功且本地更新未命中目标消息 | 刷新页面重新拉取历史；确认 `response_payload` 已为 `null` |

---

## 6. 通过标准

- 两个房间的智能体按钮数量、选中 / 取消、发送中禁用符合 2.1。
- 聊天请求统一发往 `/api/agent/tasks/start`，聊天分支流式输出、工作流分支自动刷新会话。
- 学习测评可完成「出题 → 自动弹窗 → 必答校验 → 提交 loading → 评分回显 → 入口消失」闭环。
- 刷新页面后消息状态与评分文本保持一致，历史测评入口可重新打开。
- 控制台无报错，`pnpm build` 通过。
